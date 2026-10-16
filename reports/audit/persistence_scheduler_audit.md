# QuantOS Data Lake Persistence & Background Automation Scheduler Audit

**Target Engine**: QuantOS v7.0.0 Algorithmic Trading System  
**Audit Scope**: Requirements R3 (Data Lake & Persistence Integrity) and R4 (Automation & Process Scheduling)  
**Analysis Engine**: File I/O Analysis, PyArrow Schema Audit, POSIX Concurrency & Process Tracing  
**Audit Date**: 2026-10-16  
**Auditor**: audit_worker_backend  

---

## 1. Executive Summary (BLUF)

QuantOS relies on an entirely file-based persistence layer and background process execution architecture. Empirical audits of the filesystem, concurrency boundaries, and data pipelines identify five severe architectural vulnerabilities:

1. **Parquet Schema Drift Across All 70 Daily Files**: The Data Lake contains **13 distinct schema signatures** across 70 Parquet files in `data/raw/`, with column counts expanding from 161 to 212. Unordered MultiIndex column flattening in `LakeManager.save_tabular()` causes column sequences to randomize daily based on thread completion order.
2. **Partition Contamination Breaking Standard Query Engines**: `LakeManager` co-locates `.parquet` and `.jsonl` files in identical partition directories (`data/raw/YYYY/MM/DD/`). Executing standard multi-file dataset loaders (`pyarrow.dataset.dataset("data/raw", format="parquet")`) crashes immediately with `ArrowInvalid: Could not open Parquet input source ... events.jsonl: Parquet magic bytes not found in footer`.
3. **Destructive Non-Atomic State Overwrites**: The paper trading portfolio (`paper_portfolio.json`), trade ledger (`paper_ledger.csv`), fundamental analyst scores (`fundamental_scores.json`), and user configurations (`trading_config.json`, `trading_settings.json`) bypass atomic write semantics, using raw `open(path, 'w')`. A crash or concurrent read truncates files to 0 bytes, permanently erasing portfolio equity, cash, and trade configurations.
4. **POSIX Line Atomicity Violations (>4096B)**: Out of 2,685 lines in `data/raw/` JSONL event streams, **823 lines exceed the 4,096-byte POSIX `PIPE_BUF` threshold**, reaching up to **24,117 bytes**. Concurrent multi-process appends interleave characters, permanently corrupting the JSONL stream.
5. **Concurrency Collisions & Lock Bypasses**: While `scheduler.py` uses `execution.lock` for cron jobs, `market_monitor.py:112` and `api.py:489` invoke `fetch_market_data.py` **without acquiring any lock**. If market volatility triggers an emergency event during a scheduled run, both processes execute simultaneously, double-spending cash, duplicating trades, and corrupting shared state files.
6. **Subprocess Failure Suppression**: `scheduler.py:28` executes child pipelines with `subprocess.run(args, check=False)`. Unhandled exceptions in data ingestion exit with code 1, but the scheduler silently suppresses the failure, immediately running report generators and adaptive frequency switches against corrupted or stale state.

---

## 2. Data Lake Schema Drift & Partition Contamination (Requirement R3)

### 2.1 Storage Architecture Inventory
QuantOS maintains no relational or embedded SQL database (zero SQLite, DuckDB, or PostgreSQL instances). All persistence relies on filesystem writes:

| Storage Domain | Filesystem Path | Serialized Formats | Cadence | Concurrency Protection |
|---|---|---|---|---|
| **Raw Data Lake** | `data/raw/YYYY/MM/DD/` | `.parquet`, `.jsonl` | 1h, 4h, 1d cron | None (unlocked direct overwrite & append) |
| **Runtime State** | `data/state/` | `.json` | 1h, 4h, 1d, on-demand | Mixed (partial atomic rename, raw `open('w')`) |
| **Paper Trading** | `data/paper_trading/` | `.json`, `.csv` | 1h, 4h, 1d execution | None (raw `open('w')` and `open('a')`) |
| **Model Predictions** | `data/predictions/` | `.json` | 1h, 4h, 1d inference | Atomic rename without `fsync` |
| **Telemetry & Logs** | `data/telemetry/`, `data/logs/` | `.json`, `.jsonl` | Continuous / event-driven | None (unlocked direct append) |

---

### 2.2 Parquet Schema Drift Across 70 Daily Files
An exhaustive empirical scan of all 70 on-disk Parquet files in `data/raw/` reveals **13 distinct schema signatures**:

| Signature | Column Count | File Count | Date Range | Index Column Name | Sample First Column |
|:---:|:---:|:---:|---|:---:|---|
| **Sig 1** | 161 | 3 | 2026-05-26 → 2026-05-29 (Daily) | `Datetime` | `^VIX9D_Open` |
| **Sig 2** | 161 | 18 | 2026-05-26 → 2026-06-08 (Hourly) | `Datetime` | `^VVIX_Open` |
| **Sig 3** | 162 | 3 | 2026-05-28 → 2026-05-30 (Hourly) | `Datetime` | `BTC-USD_Open` |
| **Sig 4** | 163 | 1 | 2026-06-06 (Daily) | `__index_level_0__` | `^TASI.SR_Open` |
| **Sig 5** | 162 | 1 | 2026-06-07 (Daily) | `__index_level_0__` | `^KS11_Open` |
| **Sig 6** | 181 | 7 | 2026-06-09 → 2026-06-12 (Mixed) | `Datetime` | `DFMGI.AE_Open` |
| **Sig 7** | 182 | 1 | 2026-06-12 (Daily) | `__index_level_0__` | `^HSI_Open` |
| **Sig 8** | 201 | 9 | 2026-06-13 → 2026-06-17 (Mixed) | `Datetime` | `^NDX_Open` |
| **Sig 9** | 207 | 1 | 2026-06-17 (Daily) | `Datetime` | `^FTSE_Open` |
| **Sig 10** | 206 | 8 | 2026-06-19 → 2026-06-22 (Mixed) | `Datetime` | `SH_Open` |
| **Sig 11** | 211 | 15 | 2026-06-23 → 2026-07-09 (Mixed) | `Datetime` | `TSLA_Open` |
| **Sig 12** | 211 | 2 | 2026-07-03 → 2026-07-05 (Daily) | `Date` | `CL=F_Open` |
| **Sig 13** | 212 | 1 | 2026-07-08 (Daily) | `Datetime` | `SH_Open` |

**Total Files Audited**: $3 + 18 + 3 + 1 + 1 + 7 + 1 + 9 + 1 + 8 + 15 + 2 + 1 = \mathbf{70\text{ files}}$.

#### Root Causes of Schema Drift:
1. **Unconstrained Dynamic Ticker Ingestion**: Over time, new assets were incrementally appended to the ingestion list (`ALL_YF_TICKERS`), expanding the table width from 161 columns on May 26 to 212 columns on July 8. No schema evolution mechanism or column backfilling was applied to historical partitions.
2. **Unordered MultiIndex Column Flattening (`src/data_lake/lake_manager.py:35-36`)**:
   ```python
   if isinstance(df_to_save.columns, pd.MultiIndex):
       df_to_save.columns = ['_'.join(str(c) for c in col).strip() for col in df_to_save.columns.values]
   ```
   `yfinance.download()` returns multi-level column indexes whose internal order depends on non-deterministic network response completion across worker threads. Because `LakeManager` does not sort or enforce column ordering before saving, column positions vary daily. On 2026-05-26 the first column is `^VIX9D_Open`; on 2026-05-28 it is `^VIX_Open`; on 2026-05-29 it is `DX-Y.NYB_Open`.
3. **Temporal Index Column Renaming**: Daily bars downloaded on weekends or holidays set the index name to `Date` or `__index_level_0__`, whereas hourly intraday bars set the index name to `Datetime`.

---

### 2.3 Partition Contamination & Vectorized Query Failure
`LakeManager` commits an anti-pattern by co-locating heterogeneous file formats inside the same date-partition directory:
- `data/raw/YYYY/MM/DD/raw_daily_ohlcv.parquet`
- `data/raw/YYYY/MM/DD/raw_hourly_ohlcv.parquet`
- `data/raw/YYYY/MM/DD/events.jsonl`
- `data/raw/YYYY/MM/DD/market_snapshot.jsonl`

When invoking standard multi-file dataset loaders:
```python
import pyarrow.dataset as ds
dataset = ds.dataset("data/raw", format="parquet")
```
The scan terminates immediately with an unhandled fatal error:
```
ArrowInvalid: Error creating dataset. Could not read schema from 'data/raw/2026/05/26/events.jsonl'.
Is this a 'parquet' file?: Could not open Parquet input source 'data/raw/2026/05/26/events.jsonl':
Parquet magic bytes not found in footer. Either the file is corrupted or this is not a parquet file.
```
This partition pollution prevents modern vectorized analytics engines (DuckDB, PyArrow Dataset, Polars, Trino) from scanning the raw data lake without custom path-filtering workarounds.

---

### 2.4 The "Black Hole" Data Lake Anti-Pattern
A system-wide caller/callee trace reveals that while `LakeManager.save_tabular()` runs on every cron ingestion cycle consuming disk I/O, **no quantitative engine or backtest module in QuantOS ever reads the Parquet data lake**:
- `src/fetch_market_data.py`: Calls `YahooAdapter.fetch_ohlcv_daily()` and `fetch_ohlcv_hourly()` live over the network every hour.
- `src/quantitative_backtester.py:75`: Calls `yf.download()` over the network on every backtest execution.
- `src/backtest.py`: Re-fetches data over external HTTP APIs.

The Parquet Data Lake functions purely as a write-only sink, accumulating disk storage without providing caching or offline resilience.

---

## 3. State Persistence Integrity & Atomic Write Hazards

### 3.1 Comprehensive Catalog of State File Writes

| Target State File | File Location & Line | Write Implementation | Atomic? | Process/Thread Safe? | Worst-Case Failure Impact |
|---|---|---|:---:|:---:|---|
| **`paper_portfolio.json`** | `src/adapters/paper_broker.py:56` | `with open(..., 'w') as f: json.dump(...)` | **NO (DIRECT)** | **NO** | **CRITICAL: Truncation wipes cash, equity, and position records to 0 bytes.** |
| **`paper_ledger.csv`** | `src/adapters/paper_broker.py:61` | `with open(..., 'a') as f: writer.writerow(...)` | **NO (DIRECT)** | **NO** | **CRITICAL: Concurrent writes interleave CSV rows, corrupting trade accounting.** |
| **`fundamental_scores.json`** | `src/fundamental_agent/main.py:49` | `with open(..., 'w') as f: json.dump(...)` | **NO (DIRECT)** | **NO** | **CRITICAL: RiskEngine reads 0-byte file, bypassing fundamental risk filters.** |
| **`trading_config.json`** | `src/api.py:578` | `with open(..., 'w') as f: json.dump(...)` | **NO (DIRECT)** | **NO** | **HIGH: `fetch_market_data.py:917` crashes on unhandled `json.load()` without try/except.** |
| **`trading_settings.json`** | `src/api.py:427` | `with open(..., 'w') as f: json.dump(...)` | **NO (DIRECT)** | **NO** | **MEDIUM: UI settings truncated during concurrent HTTP POST.** |
| **`raw_daily_ohlcv.parquet`** | `src/data_lake/lake_manager.py:37` | `df.to_parquet(full_path, engine='pyarrow')` | **NO (DIRECT)** | **NO** | **HIGH: Parquet footer metadata overwritten, rendering file permanently unreadable.** |
| **`raw_hourly_ohlcv.parquet`** | `src/data_lake/lake_manager.py:37` | `df.to_parquet(full_path, engine='pyarrow')` | **NO (DIRECT)** | **NO** | **HIGH: Parquet footer metadata overwritten, rendering file permanently unreadable.** |
| `market_snapshot.json` | `src/fetch_market_data.py:761` | `atomic_json_write()` | Partial (no fsync) | No | Missing `fsync`; file loss on power abort or kernel crash. |
| `live_telemetry.json` | `src/fetch_market_data.py:787` | `atomic_json_write()` | Partial (no fsync) | No | WebSocket reader encounters empty file during OS abort. |
| `features_window_{int}.json` | `src/fetch_market_data.py:420` | `atomic_json_write()` | Partial (no fsync) | No | Rolling features window corrupted on OS abort. |
| `entry_quality.json` | `src/fetch_market_data.py:655` | `atomic_json_write()` | Partial (no fsync) | No | OpportunityGate receives stale or missing score. |
| `frequency_state.json` | `src/fetch_market_data.py:1015` | `atomic_json_write()` | Partial (no fsync) | No | Adaptive scheduler reverts to fallback frequency. |

---

### 3.2 Deficiencies in Existing `atomic_json_write` Utility
`src/fetch_market_data.py:48-61` provides an `atomic_json_write` function:
```python
def atomic_json_write(data, filepath):
    dir_name = os.path.dirname(filepath)
    os.makedirs(dir_name, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_name, text=True)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temp_path, filepath)
    except Exception as e:
        logger.error(f"Failed atomic write to {filepath}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
```

#### Flaws Identified:
1. **Omission of `os.fsync`**: `with os.fdopen(fd, 'w') as f:` closes the Python file object, flushing userspace libc buffers. However, it does not call `f.flush()` followed by `os.fsync(fd)` prior to `os.replace`. Under POSIX semantics, `os.replace` updates directory metadata immediately, while file dirty blocks may remain in the OS page cache for up to 30 seconds. If an OS crash, kernel panic, or host reboot occurs, the target file path links to a 0-byte or partially written file on disk.
2. **Missing Floating-Point NaN/Inf Sanitization**: If indicators contain `float('nan')` or `float('inf')` (e.g. zero-volume holiday bars), Python's `json.dump` outputs unquoted `NaN` or `Infinity`. Standard RFC 8259 JSON parsers (including JavaScript's `JSON.parse` in React) fail with `SyntaxError: Unexpected token 'N', "NaN"... is not valid JSON`.
3. **Local Scope Isolation**: The function is scoped exclusively inside `fetch_market_data.py` and is not imported by `PaperBroker`, `fundamental_agent`, or `api.py`.

---

## 4. JSONL POSIX Pipe Buffer Atomicity Violations

In `src/data_lake/lake_manager.py`, events and market snapshots are appended to JSONL files:
- Line 70: `with open(full_path, "a") as f: f.write(json.dumps(event_data) + "\n")`
- Line 89: `with open(full_path, "a") as f: f.write(json.dumps(data) + "\n")`

### 4.1 Empirical Line Length Audit
An audit across all 2,685 JSONL lines in `data/raw/` yielded the following distribution:
- **Total JSONL Lines Audited**: 2,685 lines
- **Lines Exceeding 4,096 Bytes**: **823 lines (30.65% of all records)**
- **Maximum Line Length**: **24,117 bytes** at `data/raw/2026/07/08/events.jsonl:100`

### 4.2 POSIX Atomicity Breakdown
POSIX (IEEE Std 1003.1) guarantees atomic append operations only for writes up to `PIPE_BUF` (4,096 bytes on Linux and macOS). When an append write exceeds 4,096 bytes:
1. The kernel splits the write into multiple sequential page cache buffers.
2. If two processes (e.g., `market_monitor.py` and `scheduler.py`) append to `events.jsonl` simultaneously, their write buffers **interleave**.
3. Characters from one JSON payload are injected into the middle of another JSON payload, resulting in malformed strings:
   ```json
   {"timestamp_utc": "2026-07-08T12:00:00Z", "payload": {"sp{"timestamp_utc": "2026-07-08T12:00:01Z", ...x": 5800.0}}
   ```
4. Subsequent reads in report generators or observability loggers throw fatal `json.decoder.JSONDecodeError` exceptions.

---

## 5. Concurrency Collisions Between `market_monitor.py` and `scheduler.py`

### 5.1 Architecture of the Concurrency Hazard
`src/scheduler.py` implements an advisory file lock `run_locked_subprocess` on `execution.lock`:
```python
def run_locked_subprocess(args, lock_name="execution.lock"):
    lock_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'state', lock_name)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, 'w') as lock_file:
        try:
            logger.info(f"Waiting for lock on {lock_name} for {' '.join(args)}...")
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            subprocess.run(args)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
```

However, two major execution paths **completely bypass this lock**:
1. **`src/market_monitor.py:112`**:
   ```python
   if should_run and (now_ts - last_event_trigger_time) > COOLDOWN_SECONDS:
       logger.info(f"Event trigger firing pipeline (interval={interval}): {reason}")
       subprocess.run(["python3", "src/fetch_market_data.py", "--interval", interval])
       subprocess.run(["python3", "src/build_report.py"])
   ```
2. **`src/api.py:489–514` (`run_job_background`)**:
   ```python
   def run_job_background(job_type: str, start_date: str = None, end_date: str = None):
       if job_type == "1h":
           subprocess.run(["python3", "src/fetch_market_data.py", "--interval", "1h"])
           subprocess.run(["python3", "src/build_report.py"])
   ```

Neither `market_monitor.py` nor `api.py` imports or invokes `run_locked_subprocess`. They launch `fetch_market_data.py` directly.

---

### 5.2 Concurrency Collision Trace & Race Condition Breakdown

```
┌────────────────────────────────────────────────────────┐
│                   scheduler.py                         │
│  APScheduler 4H Cron (Hour 12:05)                      │
│  └─ Holds execution.lock                               │
│     └─ fetch_market_data.py --interval 4h              │
└──────────────────────────┬─────────────────────────────┘
                           │
                           │  CONCURRENT EXECUTION!
                           │  (ZERO LOCK ON MONITOR)
                           │
┌──────────────────────────┴─────────────────────────────┐
│                market_monitor.py                       │
│  Detects VIX Spike / Stop Loss                         │
│  Line 112: subprocess.run(fetch_market_data.py 1h)     │
│  └─ DOES NOT ACQUIRE execution.lock                    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
          ═════════════════════════════════
          COLLISION ON SHARED RESOURCES:
          1. paper_portfolio.json (Cash double-spent; positions clobbered)
          2. paper_ledger.csv (Interleaved CSV rows)
          3. raw_daily_ohlcv.parquet (PyArrow footer write race)
          4. events.jsonl / market_snapshot.jsonl (>4KB interleave)
          5. market_snapshot.json (State file torn write)
          ═════════════════════════════════
```

#### High-Severity Race Conditions:
1. **Paper Broker Cash Double-Spending & Position Obliteration**:
   `PaperBroker` (`src/adapters/paper_broker.py:41-58`) reads `paper_portfolio.json` into memory on startup, evaluates position differences, and writes the entire updated portfolio back using `open(self.portfolio_path, 'w')`.
   - Process A (4H Cron) reads portfolio cash: `$10,000.00`.
   - Process B (Market Monitor) reads portfolio cash: `$10,000.00`.
   - Process A buys `$4,000.00` of SPX; sets cash to `$6,000.00`.
   - Process B buys `$4,000.00` of GLD; sets cash to `$6,000.00`.
   - Process B writes last: cash is saved as `$6,000.00`, but total asset value is `$8,000.00`. Process A's SPX position is overwritten and erased, creating phantom equity and untracked holdings.
2. **Parquet Footer Corruption**:
   `LakeManager.save_tabular()` invokes `df.to_parquet()` directly on `raw_daily_ohlcv.parquet`. PyArrow writes the file header, data pages, and footer metadata sequentially. When two processes write to the same file simultaneously, their data pages and footer offsets overlap, corrupting the Parquet magic bytes and rendering the partition unreadable.
3. **Broken Lock Scope in `scheduler.py:40, 46`**:
   In `run_4h` and `run_1d`, `build_report.py` is called **after** the lock is released:
   ```python
   def run_4h():
       run_locked_subprocess(["python3", "src/fetch_market_data.py", "--interval", "4h"])
       # LOCK IS RELEASED HERE!
       subprocess.run(["python3", "src/build_report.py", "--title", "4H Execution Report"])
       _apply_adaptive_frequency()
   ```
   If a 1H context run triggers as `fetch_market_data.py` completes, it acquires `execution.lock` and begins rewriting `market_snapshot.json` while `build_report.py` is concurrently reading it.

---

## 6. Scheduler Error Suppression & Cadence Anomalies (Requirement R4)

### 6.1 Child Process Error Suppression
In `src/scheduler.py:28`:
```python
subprocess.run(args)
```
`subprocess.run` defaults to `check=False`. If `fetch_market_data.py` encounters an unhandled exception (e.g., Yahoo Finance rate limit, network timeout, corrupt config JSON) and exits with code 1:
- `run_locked_subprocess` swallows the failure and returns `CompletedProcess(returncode=1)` silently.
- In `run_4h`, execution proceeds directly to `build_report.py`, generating an execution report based on stale or missing state.
- `_apply_adaptive_frequency()` executes next, making scheduling decisions based on obsolete data.

### 6.2 Destructive Open on Lock File
In `src/scheduler.py:24`:
```python
with open(lock_path, 'w') as lock_file:
    fcntl.flock(lock_file, fcntl.LOCK_EX)
```
`open(lock_path, 'w')` truncates the lockfile before `fcntl.flock()` is invoked. If Process A holds the lock, Process B opens the file with `'w'`, immediately truncating the underlying inode while Process A is actively executing. The lock file should be opened with `'a'` or `os.open` with `O_CREAT | O_RDWR`.

### 6.3 Unbounded Blocking Wait & Lack of Execution Timeout
`fcntl.flock(lock_file, fcntl.LOCK_EX)` uses blocking mode without `fcntl.LOCK_NB`. In addition, `subprocess.run(args)` specifies no `timeout`. If a child process hangs on a network socket read, the APScheduler worker thread blocks indefinitely, eventually exhausting the scheduler thread pool.

### 6.4 FrequencyController Cadence Disconnect
In `src/engines/frequency_controller.py:90-98`:
```python
if score >= 1:
    freq = "4h"  # Capped at 4H even if score >= 4
else:
    freq = "1d"
```
The frequency controller **never returns `"1h"`**. Even if market conditions are optimal and score reaches maximum confidence, the output is hard-capped at `"4h"`. Consequently, the 1H adaptive branch in `scheduler.py:69-72` is dead code under automated operation.

### 6.5 Cascading Immediate Execution Hazard
In `src/scheduler.py:72, 76, 80`:
```python
scheduler.add_job(..., next_run_time=datetime.now())
```
Passing `next_run_time=datetime.now()` causes APScheduler to execute the newly configured job immediately upon frequency transition. If rapid metric fluctuations alternate the recommendation between 4H and 1D, the scheduler triggers cascading immediate pipeline executions, flooding market data APIs and overloading system resources.

---

## 7. Concrete Actionable Remediation Blueprints

### Blueprint 1: Universal Atomic File Writer with `fsync` & File Locking
Create `src/persistence/atomic_io.py` to centralize safe state persistence:

```python
import os
import json
import tempfile
import fcntl
from typing import Any

def atomic_write_json(filepath: str, data: Any, indent: int = 4) -> None:
    """
    Atomically writes data to filepath using tempfile + flush + fsync + os.replace.
    Ensures kernel buffers are committed to non-volatile disk before directory update.
    """
    dir_name = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dir_name, exist_ok=True)
    
    fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

def safe_load_json(filepath: str, default: Any = None) -> Any:
    """
    Safely loads JSON with error tolerance on corrupted or partial files.
    """
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default
```

---

### Blueprint 2: Unified Subprocess Mutex Lock with Timeout & Non-Destructive Open
Refactor `src/scheduler.py` to prevent deadlocks and ensure full mutex coverage:

```python
import fcntl
import os
import subprocess
import logging

logger = logging.getLogger("scheduler")

def run_locked_subprocess(args: list[str], lock_name: str = "execution.lock", timeout: int = 600) -> bool:
    lock_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'state', lock_name)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    
    # Open with 'a' to avoid truncating file before lock acquisition
    with open(lock_path, 'a') as lock_file:
        try:
            logger.info(f"Acquiring lock {lock_name} for {' '.join(args)}...")
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            logger.info(f"Lock acquired. Executing subprocess: {' '.join(args)}")
            
            result = subprocess.run(args, timeout=timeout, check=True)
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"Subprocess timed out after {timeout}s: {' '.join(args)}")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Subprocess failed with exit code {e.returncode}: {' '.join(args)}")
            return False
        except Exception as e:
            logger.error(f"Lock execution error: {e}")
            return False
        finally:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except Exception:
                pass
```

And update `src/market_monitor.py:112` and `src/api.py:489` to route all pipeline runs through `run_locked_subprocess`.

---

### Blueprint 3: Data Lake Partitioning & Atomic Parquet Persistence
Refactor `src/data_lake/lake_manager.py` to separate tabular Parquet tables from JSONL event streams, and enforce atomic writes:

```python
import os
import tempfile
import pandas as pd
from datetime import datetime, timezone

class LakeManager:
    def __init__(self, base_dir=None):
        if base_dir is None:
            self.base_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'raw')
        else:
            self.base_dir = base_dir

    def _get_table_partition_dir(self, table_name: str) -> str:
        now = datetime.now(timezone.utc)
        path = os.path.join(self.base_dir, "tables", table_name, f"year={now.year}", f"month={now.month:02d}", f"day={now.day:02d}")
        os.makedirs(path, exist_ok=True)
        return path

    def _get_stream_partition_dir(self, stream_name: str) -> str:
        now = datetime.now(timezone.utc)
        path = os.path.join(self.base_dir, "streams", stream_name, f"year={now.year}", f"month={now.month:02d}", f"day={now.day:02d}")
        os.makedirs(path, exist_ok=True)
        return path

    def save_tabular(self, data: pd.DataFrame, table_name: str):
        if data is None or data.empty:
            return
            
        part_dir = self._get_table_partition_dir(table_name)
        target_path = os.path.join(part_dir, f"{table_name}.parquet")
        
        df_to_save = data.copy()
        # Sort columns to enforce deterministic schema ordering
        if isinstance(df_to_save.columns, pd.MultiIndex):
            df_to_save.columns = sorted(['_'.join(str(c) for c in col).strip() for col in df_to_save.columns.values])
        else:
            df_to_save = df_to_save.reindex(sorted(df_to_save.columns), axis=1)

        fd, temp_path = tempfile.mkstemp(dir=part_dir, prefix=".tmp_", suffix=".parquet")
        os.close(fd)
        try:
            df_to_save.to_parquet(temp_path, engine='pyarrow', index=True)
            os.replace(temp_path, target_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
```
