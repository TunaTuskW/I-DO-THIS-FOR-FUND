"""Tier 3 Audit: Data Lake & Persistence Integrity.

Validates:
- State dump atomic write semantics across paper_broker.py, fundamental_agent/main.py, and api.py.
- Detection of direct open('w') truncation hazards.
- Parquet schema drift across raw partitions (detects the 13 distinct schema variations across 70 parquet files).
- POSIX atomic append line length limits on market_snapshot.jsonl (> 4096 bytes).
- Data lake partition directory pollution (mixing .parquet and .jsonl).
"""

import ast
import glob
import json
import os
import tempfile
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DATA_DIR = os.path.join(REPO_ROOT, "data", "raw")
PIPE_BUF_POSIX = 4096


def _find_direct_open_w_calls(file_path: str):
    """Parse a python file with AST and return list of (lineno, target_var_or_name)."""
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    open_w_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                expr = item.context_expr
                if isinstance(expr, ast.Call):
                    func_id = getattr(expr.func, "id", None)
                    if func_id == "open":
                        args = expr.args
                        if len(args) > 1 and isinstance(args[1], ast.Constant) and args[1].value == "w":
                            target_file = ast.unparse(args[0])
                            open_w_calls.append((node.lineno, target_file))
    return open_w_calls


def test_non_atomic_state_dumps_ast():
    """Verify that paper_broker, fundamental_agent, and api.py use direct open('w') instead of atomic writes."""
    targets = {
        os.path.join(REPO_ROOT, "src", "adapters", "paper_broker.py"): "portfolio_path",
        os.path.join(REPO_ROOT, "src", "fundamental_agent", "main.py"): "out_path",
        os.path.join(REPO_ROOT, "src", "api.py"): "config_path",
    }

    all_found = {}
    for path, expected_token in targets.items():
        assert os.path.exists(path), f"File {path} missing"
        calls = _find_direct_open_w_calls(path)
        assert len(calls) > 0, f"Expected direct open('w') calls in {path}"
        matching = [c for c in calls if expected_token in c[1]]
        assert len(matching) > 0, f"Expected direct open('w') for {expected_token} in {path}, got {calls}"
        all_found[path] = calls

    # Verify that these files do not import atomic_json_write or use atomic rename
    for path in targets.keys():
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "atomic_json_write" not in content, f"{path} should not be using atomic_json_write"
        assert "os.replace" not in content, f"{path} should not be using os.replace"

    assert len(all_found) == 3


def test_direct_open_w_truncation_hazard():
    """Demonstrate the zero-byte truncation vulnerability of open('w') vs atomic tempfile replace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "state.json")

        # Step 1: Write initial valid state
        with open(test_file, "w") as f:
            json.dump({"cash": 10000.0, "positions": {"SPX": 5}}, f)

        assert os.path.getsize(test_file) > 0

        # Step 2: Simulate direct open('w') truncation window
        f_direct = open(test_file, "w")
        # Notice: file size is immediately truncated to 0 BEFORE json.dump runs!
        truncated_size = os.path.getsize(test_file)
        assert truncated_size == 0, "open('w') must truncate file size to 0 bytes immediately"

        # A concurrent reader at this instant reads 0 bytes and raises JSONDecodeError
        with pytest.raises(json.decoder.JSONDecodeError):
            with open(test_file, "r") as reader:
                json.load(reader)

        f_direct.close()

        # Step 3: Contrast with atomic write (tempfile + os.replace)
        with open(test_file, "w") as f:
            json.dump({"cash": 10000.0, "positions": {"SPX": 5}}, f)

        fd, temp_path = tempfile.mkstemp(dir=tmpdir)
        with os.fdopen(fd, "w") as tf:
            json.dump({"cash": 12000.0, "positions": {"SPX": 6}}, tf)

        # Before rename, destination file is completely intact
        with open(test_file, "r") as reader:
            data = json.load(reader)
            assert data["cash"] == 10000.0

        os.replace(temp_path, test_file)

        # After atomic rename, destination file atomically transitions to new state
        with open(test_file, "r") as reader:
            data = json.load(reader)
            assert data["cash"] == 12000.0


def test_parquet_schema_drift_detection():
    """Scan all raw Parquet files and assert detection of the 13 distinct schema variations across 70 files."""
    parquet_files = glob.glob(os.path.join(RAW_DATA_DIR, "**", "*.parquet"), recursive=True)
    assert len(parquet_files) == 70, f"Expected exactly 70 parquet files in data/raw, found {len(parquet_files)}"

    signatures = {}
    for fpath in parquet_files:
        schema = pq.read_schema(fpath)
        col_names = schema.names
        col_set = frozenset(col_names)
        signature = (len(col_names), col_set)
        signatures.setdefault(signature, []).append(fpath)

    # Acceptance criteria verification: exactly 13 distinct column-set schema signatures
    distinct_count = len(signatures)
    assert distinct_count == 13, (
        f"Expected exactly 13 distinct schema signatures across raw parquet files, found {distinct_count}"
    )

    # Column counts range from 161 to 212
    col_counts = sorted(list({sig[0] for sig in signatures.keys()}))
    assert col_counts[0] == 161, f"Expected minimum column count 161, got {col_counts[0]}"
    assert col_counts[-1] == 212, f"Expected maximum column count 212, got {col_counts[-1]}"


def test_jsonl_posix_line_length_atomicity_hazard():
    """Verify that market_snapshot.jsonl line lengths exceed POSIX PIPE_BUF (4096 bytes)."""
    snapshot_files = glob.glob(os.path.join(RAW_DATA_DIR, "**", "market_snapshot.jsonl"), recursive=True)
    assert len(snapshot_files) > 0, "No market_snapshot.jsonl files found in data/raw"

    max_line_bytes = 0
    oversized_lines_count = 0

    for fpath in snapshot_files:
        with open(fpath, "rb") as f:
            for line in f:
                length = len(line)
                if length > max_line_bytes:
                    max_line_bytes = length
                if length > PIPE_BUF_POSIX:
                    oversized_lines_count += 1

    # Acceptance criteria: records exceed 4096 bytes (reaching ~24KB)
    assert max_line_bytes > PIPE_BUF_POSIX, (
        f"Peak line length ({max_line_bytes}) did not exceed POSIX PIPE_BUF ({PIPE_BUF_POSIX})"
    )
    assert max_line_bytes >= 20000, (
        f"Expected snapshot records ~24KB, found max length {max_line_bytes}"
    )
    assert oversized_lines_count > 0, "Expected multiple oversized records violating POSIX atomic append"


def test_data_lake_partition_format_pollution():
    """Verify that co-locating parquet and jsonl files in raw partitions causes PyArrow dataset scan failure."""
    # Find partition directories containing both .parquet and .jsonl
    partitions = glob.glob(os.path.join(RAW_DATA_DIR, "*", "*", "*"))
    polluted_partitions = []
    for p in partitions:
        if os.path.isdir(p):
            has_parquet = len(glob.glob(os.path.join(p, "*.parquet"))) > 0
            has_jsonl = len(glob.glob(os.path.join(p, "*.jsonl"))) > 0
            if has_parquet and has_jsonl:
                polluted_partitions.append(p)

    assert len(polluted_partitions) > 0, "Expected at least one partition with mixed parquet and jsonl"

    # Attempting to scan a polluted partition with format='parquet' without file extension filtering must fail
    target_partition = polluted_partitions[0]
    with pytest.raises(Exception):
        # pyarrow.dataset.dataset scans all files in directory by default unless ignoring non-parquet
        dataset = ds.dataset(target_partition, format="parquet")
        # Reading table triggers file format validation on jsonl files
        dataset.to_table()
