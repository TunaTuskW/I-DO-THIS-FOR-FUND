"""Tier 1 Audit: AST Topology, CodeGraph Index & Call Graph Integrity.

Validates:
- CodeGraph sync state and database metrics.
- 0 unresolved references across all 14 core QuantOS symbols.
- Critical execution path call graph connectivity (Orchestrator -> FeatureEngine -> RiskEngine -> Broker).
- Verification of Kalman filter and MCS live pipeline omission.
- Catalog of dead functions, superseded modules, and disconnected endpoints.
"""

import ast
import os
import sqlite3
import subprocess
from typing import List, Set


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CODEGRAPH_DB = os.path.join(REPO_ROOT, ".codegraph", "codegraph.db")

CORE_SYMBOLS = [
    "LakeManager",
    "PaperBroker",
    "RiskEngine",
    "TrendEngine",
    "SMCEngine",
    "SessionEngine",
    "LiquidityEngine",
    "RegimeEnsemble",
    "ConsensusEngine",
    "EntryEngine",
    "FrequencyController",
    "OpportunityGate",
    "EventBus",
    "Conductor",
]

DEAD_FUNCTIONS_FEATURE_ENGINE = [
    "sign_snapshot_payload",
    "check_mathematical_consistency",
    "append_to_immutable_chain",
    "compute_weekly_liquidity_boundaries",
    "calculate_model_tvd",
    "calculate_bayesian_conditional_probability",
]

DEPRECATED_MODULES = [
    "src/backtest.py",
    "src/train_models.py",
    "src/tune_hyperparameters.py",
    "src/visualize_paper_trading.py",
    "src/generate_visual_map.py",
]


def test_codegraph_sync_and_status():
    """Verify that the CodeGraph AST database is populated, synced, and covers the codebase."""
    assert os.path.exists(CODEGRAPH_DB), f"CodeGraph DB missing at {CODEGRAPH_DB}"

    conn = sqlite3.connect(CODEGRAPH_DB)
    cursor = conn.cursor()

    # Check indexed files count
    file_count = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert file_count >= 65, f"Expected at least 65 indexed files, found {file_count}"

    # Check AST node count
    node_count = cursor.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert node_count >= 800, f"Expected at least 800 AST nodes, found {node_count}"

    # Check edge count
    edge_count = cursor.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert edge_count >= 1400, f"Expected at least 1400 AST edges, found {edge_count}"

    conn.close()


def test_core_symbols_zero_unresolved_refs():
    """Verify zero unresolved references for all 14 core system symbols."""
    assert os.path.exists(CODEGRAPH_DB), "CodeGraph DB must exist"

    conn = sqlite3.connect(CODEGRAPH_DB)
    cursor = conn.cursor()

    # Verify each core symbol exists in nodes
    for symbol in CORE_SYMBOLS:
        row = cursor.execute(
            "SELECT name, kind, file_path FROM nodes WHERE name=? LIMIT 1",
            (symbol,),
        ).fetchone()
        assert row is not None, f"Core symbol '{symbol}' not found in CodeGraph nodes"

    # Verify zero unresolved references for any of the 14 core symbols
    placeholders = ",".join(["?"] * len(CORE_SYMBOLS))
    query = f"""
        SELECT id, file_path, reference_name, name_tail, line, status
        FROM unresolved_refs
        WHERE reference_name IN ({placeholders}) OR name_tail IN ({placeholders})
    """
    unresolved = cursor.execute(query, CORE_SYMBOLS + CORE_SYMBOLS).fetchall()
    conn.close()

    assert len(unresolved) == 0, (
        f"Found {len(unresolved)} unresolved references on core symbols: {unresolved}"
    )


def test_critical_execution_path_connectivity():
    """Verify AST call path connectivity from Conductor -> Feature Ingestion -> RiskEngine -> PaperBroker."""
    fetch_path = os.path.join(REPO_ROOT, "src", "fetch_market_data.py")
    assert os.path.exists(fetch_path), f"File {fetch_path} does not exist"

    with open(fetch_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=fetch_path)

    conductor_class = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Conductor":
            conductor_class = node
            break

    assert conductor_class is not None, "Conductor class not found in fetch_market_data.py"

    conductor_methods = {
        m.name: m for m in conductor_class.body if isinstance(m, ast.FunctionDef)
    }

    # Verify critical event handler methods exist
    required_handlers = [
        "__init__",
        "run",
        "handle_system_start",
        "handle_data_fetched",
        "handle_features_engineered",
        "handle_engines_completed",
        "handle_pipeline_complete",
    ]
    for handler in required_handlers:
        assert handler in conductor_methods, f"Conductor missing handler: {handler}"

    # Verify Conductor instantiates adapters and engines in __init__
    init_ast = conductor_methods["__init__"]
    init_code = ast.unparse(init_ast)
    assert "RiskEngine(" in init_code, "Conductor does not instantiate RiskEngine"
    assert "PaperBroker(" in init_code, "Conductor does not instantiate PaperBroker"
    assert "LakeManager(" in init_code, "Conductor does not instantiate LakeManager"
    assert "EventBus(" in init_code, "Conductor does not instantiate EventBus"

    # Verify execution of RiskEngine.compute_multi_asset_kelly in handle_features_engineered
    feat_ast = conductor_methods["handle_features_engineered"]
    feat_code = ast.unparse(feat_ast)
    assert "compute_multi_asset_kelly" in feat_code, (
        "compute_multi_asset_kelly not called in handle_features_engineered"
    )

    # Verify execution of PaperBroker.execute_rebalance in handle_pipeline_complete
    pipe_ast = conductor_methods["handle_pipeline_complete"]
    pipe_code = ast.unparse(pipe_ast)
    assert "execute_rebalance" in pipe_code, (
        "execute_rebalance not called in handle_pipeline_complete"
    )


def test_kalman_and_mcs_pipeline_disconnection():
    """Verify that Kalman filter and MCS are properly connected in live Conductor as remediated in Phase 1."""
    fetch_path = os.path.join(REPO_ROOT, "src", "fetch_market_data.py")
    backtest_path = os.path.join(REPO_ROOT, "src", "quantitative_backtester.py")

    with open(fetch_path, "r", encoding="utf-8") as f:
        fetch_tree = ast.parse(f.read(), filename=fetch_path)

    with open(backtest_path, "r", encoding="utf-8") as f:
        backtest_tree = ast.parse(f.read(), filename=backtest_path)

    # In fetch_market_data: verify compute_mcs is imported
    imported_mcs = False
    for node in ast.walk(fetch_tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "compute_mcs":
                    imported_mcs = True
    assert imported_mcs, "compute_mcs was expected to be imported in fetch_market_data.py"

    # In fetch_market_data: verify both compute_mcs and run_kalman_filter are called in Conductor
    called_mcs = False
    called_kalman = False
    for node in ast.walk(fetch_tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "compute_mcs") or (isinstance(func, ast.Attribute) and func.attr == "compute_mcs"):
                called_mcs = True
            elif (isinstance(func, ast.Name) and func.id == "run_kalman_filter") or (isinstance(func, ast.Attribute) and func.attr == "run_kalman_filter"):
                called_kalman = True

    assert called_mcs, "Phase 1 remediation check: compute_mcs must be called in fetch_market_data.py"
    assert called_kalman, "Phase 1 remediation check: run_kalman_filter must be called in fetch_market_data.py"

    # In quantitative_backtester: verify run_kalman_filter IS called
    bt_called_kalman = False
    for node in ast.walk(backtest_tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run_kalman_filter":
                bt_called_kalman = True

    assert bt_called_kalman, "Expected run_kalman_filter to be called in quantitative_backtester.py"

    # In fetch_market_data.py: verify Conductor passes initialized kalman_state or dominant_state
    fetch_code = ast.unparse(fetch_tree)
    assert "kalman_state" in fetch_code or "dominant_state" in fetch_code, (
        "Expected Conductor to reference kalman state"
    )


def test_dead_functions_catalog():
    """Verify presence of dead/orphaned functions in feature_engine.py that are never called in live pipeline."""
    feat_engine_path = os.path.join(REPO_ROOT, "src", "engines", "feature_engine.py")
    assert os.path.exists(feat_engine_path), f"File {feat_engine_path} missing"

    with open(feat_engine_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=feat_engine_path)

    top_level_funcs = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }

    # Verify each dead function is actually defined in feature_engine.py
    for dead_func in DEAD_FUNCTIONS_FEATURE_ENGINE:
        assert dead_func in top_level_funcs, (
            f"Expected dead function '{dead_func}' to exist in feature_engine.py"
        )

    # Verify that in fetch_market_data.py, none of these 6 dead functions are ever executed in Conductor
    fetch_path = os.path.join(REPO_ROOT, "src", "fetch_market_data.py")
    with open(fetch_path, "r", encoding="utf-8") as f:
        fetch_tree = ast.parse(f.read(), filename=fetch_path)

    calls_in_fetch: Set[str] = set()
    for node in ast.walk(fetch_tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls_in_fetch.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls_in_fetch.add(node.func.attr)

    for dead_func in DEAD_FUNCTIONS_FEATURE_ENGINE:
        assert dead_func not in calls_in_fetch, (
            f"Dead function '{dead_func}' unexpectedly invoked in fetch_market_data.py"
        )

    # And verify that compute_mcs is successfully wired and called
    assert "compute_mcs" in calls_in_fetch, (
        "compute_mcs must be wired and called in fetch_market_data.py"
    )


def test_deprecated_modules_and_endpoints():
    """Verify presence of deprecated root scripts and disconnected API trading settings endpoint."""
    # Verify deprecated files exist on disk (orphaned or superseded)
    for mod in DEPRECATED_MODULES:
        full_path = os.path.join(REPO_ROOT, mod)
        assert os.path.exists(full_path), f"Expected deprecated module {mod} on disk"

    # Verify disconnected trading settings endpoint in api.py
    api_path = os.path.join(REPO_ROOT, "src", "api.py")
    with open(api_path, "r", encoding="utf-8") as f:
        api_text = f.read()

    assert "/api/trading_settings" in api_text, "Expected /api/trading_settings route in api.py"
    assert "trading_settings.json" in api_text, "Expected trading_settings.json in api.py"

    # Verify fetch_market_data.py never references trading_settings.json
    fetch_path = os.path.join(REPO_ROOT, "src", "fetch_market_data.py")
    with open(fetch_path, "r", encoding="utf-8") as f:
        fetch_text = f.read()

    assert "trading_settings.json" not in fetch_text, (
        "fetch_market_data.py should not reference trading_settings.json (disconnected configuration)"
    )
