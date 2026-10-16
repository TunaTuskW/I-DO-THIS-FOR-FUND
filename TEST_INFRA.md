# QuantOS Full-Stack Codebase Audit: Test Infrastructure Specification

**Path**: `/Users/mac/agent/TEST_INFRA.md`  
**Downloads Replica**: `/Users/mac/Downloads/Antigravity_Exports/TEST_INFRA.md`  
**Test Suite Directory**: `/Users/mac/agent/tests/audit/`  
**Runner Command**: `python3 -m pytest tests/audit/ -v` or `python3 tests/audit/run_audit_tests.py`  
**Output Artifact**: `/Users/mac/agent/tests/audit/audit_results.json`

---

## 1. Executive Summary & BLUF (Bottom Line Up Front)

The QuantOS Audit Verification Test Suite provides automated, repeatable, and deterministic verification across all four acceptance criteria tiers outlined in `ORIGINAL_REQUEST.md` and `PROJECT.md`. The harness executes without modifying production source code, employing static AST parsing, SQLite WAL inspection of the CodeGraph database, PyArrow metadata analysis, POSIX file boundary profiling, and React component prop hazard evaluation.

### Core Metrics Verified by the Suite:
- **Core Symbol AST Resolution**: 14/14 core symbols verified with exactly 0 unresolved references in CodeGraph.
- **Critical Call Flow Tracing**: 4-stage execution sequence (Orchestrator -> FeatureEngine -> RiskEngine -> PaperBroker) verified via AST call graphs.
- **Frontend Tab Component Auditing**: 10/10 React tabs evaluated across empty `{}` payloads, null field injections, and type mismatches; 6/10 tabs identified lacking `ErrorBoundary` wrapping.
- **Persistence Atomic Writes**: Direct non-atomic `open('w')` writes flagged across `paper_broker.py`, `fundamental_agent/main.py`, and `api.py`.
- **Data Lake Drift Profiling**: 13 distinct schema signatures identified across all 70 raw `.parquet` files; partition contamination between `.parquet` and `.jsonl` verified.
- **POSIX Atomicity Limits**: `market_snapshot.jsonl` record lengths measured up to 24,066 bytes, exceeding the 4,096-byte POSIX atomic append threshold (`PIPE_BUF`).
- **Scheduler Mutex Collisions**: Unlocked subprocess execution in `market_monitor.py:112` and `api.py:511` verified to bypass `execution.lock`.

---

## 2. Test Architecture & Runner Environment

```
                                  [pytest Test Runner]
                                            │
               ┌────────────────────────────┼────────────────────────────┐
               │                            │                            │
               ▼                            ▼                            ▼
     [Tier 1: AST Integrity]     [Tier 2: Frontend Resilience] [Tier 3: Persistence]
     test_ast_integrity.py       test_frontend_resilience.py   test_atomic_persistence.py
     ├── CodeGraph WAL DB        ├── AST Prop Extraction       ├── Open('w') AST Detection
     ├── 14 Core Symbols         ├── 10 Tab Component Matrix   ├── 70 Parquet Schemas (13)
     ├── Critical Path Trace     ├── Empty / Null / Type-Cast  ├── 4096B POSIX PIPE_BUF
     └── Dead Code Catalog       └── Error Boundary Coverage   └── Partition Contamination
                                            │
                                            ▼
                               [Tier 4: Concurrency Mutex]
                               test_scheduler_concurrency.py
                               ├── Lock Bypass in Monitor/API
                               ├── check=False Failure Cascade
                               └── Destructive Lock Truncation
                                            │
                                            ▼
                             [tests/audit/audit_results.json]
```

### Runtime Environment:
- **Operating System**: macOS (Darwin 24.3.0)
- **Primary Runtime**: Python 3.9.6
- **Test Framework**: `pytest` 8.4.2
- **Data & Graph Parsers**:
  - `sqlite3`: Direct query interface into `.codegraph/codegraph.db`
  - `ast`: Standard library Python Abstract Syntax Tree parser
  - `pyarrow`: Apache Arrow Parquet metadata and schema inspector (v19.0.0+)
  - `json` & `fcntl`: File semantics and lock mechanics validation

---

## 3. Test Tier Breakdown & Scope

### Tier 1: AST Architectural Topology & Call Graph (`test_ast_integrity.py`)
- **T1.1 CodeGraph Database Integrity**: Confirms `.codegraph/codegraph.db` is initialized in WAL mode, with over 800 nodes and 1,500 edges across 70 indexed files.
- **T1.2 Core Symbol Resolution**: Queries `unresolved_refs` and `nodes` tables to assert exactly 0 unresolved references across the 14 core system classes:
  `LakeManager`, `PaperBroker`, `RiskEngine`, `TrendEngine`, `SMCEngine`, `SessionEngine`, `LiquidityEngine`, `RegimeEnsemble`, `ConsensusEngine`, `EntryEngine`, `FrequencyController`, `OpportunityGate`, `EventBus`, `Conductor`.
- **T1.3 Critical Execution Path Connectivity**: Verifies structural invocation flow from `Conductor.run()` through `handle_data_fetched()`, `handle_features_engineered()`, `RiskEngine.compute_multi_asset_kelly()`, and `PaperBroker.execute_rebalance()`.
- **T1.4 Kalman Filter & MCS Pipeline Disconnection**: Verifies that while `compute_mcs()` and `risk_engine.run_kalman_filter()` are called in `quantitative_backtester.py`, they are omitted in `fetch_market_data.py:Conductor`, leaving `snapshot.kalman_state.dominant_state` defaulting to `"UNKNOWN"`.
- **T1.5 Dead Functions & Deprecated Modules**: Verifies the presence of orphaned functions in `feature_engine.py` (`sign_snapshot_payload`, `check_mathematical_consistency`, `append_to_immutable_chain`, `compute_weekly_liquidity_boundaries`, `calculate_model_tvd`, `calculate_bayesian_conditional_probability`, `compute_mcs`) and deprecated root modules (`backtest.py`, `train_models.py`, `tune_hyperparameters.py`, `visualize_paper_trading.py`, `generate_visual_map.py`).

### Tier 2: Frontend React Resilience & UI Integrity (`test_frontend_resilience.py`)
- **T2.1 Component Catalog Verification**: Asserts all 10 React tab components exist in `frontend/src/components/`:
  1. `OverviewTab.jsx`
  2. `TradingTerminal.jsx`
  3. `PaperTradingTab.jsx`
  4. `MacroTab.jsx`
  5. `FundamentalTab.jsx`
  6. `MathModelTab.jsx`
  7. `DiagnosticsTab.jsx`
  8. `ReportsTab.jsx`
  9. `SettingsTab.jsx`
  10. `PipelineVisualizer.jsx`
- **T2.2 Malformed Payload Resilience Analysis**:
  Evaluates each tab component against three malformed API payload conditions:
  - Empty payload (`{}`)
  - Null field payload (`regime: null`, `entry_score: null`, `portfolio: null`, `active_tickers: null`, etc.)
  - Type-mismatched payload (string instead of array, null instead of object)
  Flags unhandled property chains (`.toFixed()`, `.replace()`, `.map()`, `.slice()`, `.total_equity`).
- **T2.3 The `null !== undefined` Logical Fallacy**:
  Validates detection of the JavaScript null comparison defect in `PaperTradingTab.jsx:222-267`, where `portfolio.win_rate !== undefined` evaluates to `true` when `win_rate` is `null`, triggering a runtime `TypeError`.
- **T2.4 Error Boundary Coverage**:
  Audits AST and JSX structures across all files to assert that only 4 components (`MacroTab`, `FundamentalTab`, `MathModelTab`, `ReportsTab`) are wrapped in `ErrorBoundary`, while 6 tab components and `App.jsx` remain unprotected.

### Tier 3: Data Lake & Persistence Integrity (`test_atomic_persistence.py`)
- **T3.1 Non-Atomic State Dump Detection**:
  Parses AST of `src/adapters/paper_broker.py`, `src/fundamental_agent/main.py`, and `src/api.py` to assert presence of direct `open(..., 'w')` calls on `paper_portfolio.json`, `fundamental_scores.json`, `trading_settings.json`, and `trading_config.json`.
- **T3.2 Direct Write Truncation Hazard Proof**:
  Executes verification proving that `open(path, 'w')` instantly truncates file length to 0 bytes before `json.dump()` completes, creating a window where concurrent reads fail with `json.decoder.JSONDecodeError`.
- **T3.3 Parquet Schema Drift across Raw Partitions**:
  Scans all 70 Parquet files in `data/raw/` using `pyarrow.parquet.read_schema()`, extracts column set signatures, and asserts detection of the 13 distinct schema variations (ranging from 161 to 212 columns).
- **T3.4 POSIX Line Length Atomicity Limit**:
  Scans all 33 `market_snapshot.jsonl` files in `data/raw/`, measuring maximum line length. Asserts that peak line length (24,066 bytes) exceeds the POSIX atomic write guarantee (`PIPE_BUF` = 4,096 bytes).
- **T3.5 Data Lake Partition Pollution**:
  Tests reading `data/raw/` partitions with standard vectorized Parquet dataset readers, demonstrating failure when `.parquet` and `.jsonl` files reside in the same directory.

### Tier 4: Background Automation & Concurrency Mutex (`test_scheduler_concurrency.py`)
- **T4.1 Subprocess Mutex Collision**:
  Analyzes `src/market_monitor.py:112` and `src/api.py:511` to assert that background invocations of `fetch_market_data.py` do not acquire `execution.lock` or use `run_locked_subprocess()`.
- **T4.2 Exception Isolation & Return Code Suppression**:
  Verifies that `run_locked_subprocess()` in `src/scheduler.py` invokes `subprocess.run(args)` without `check=True`, suppressing non-zero exit codes and allowing downstream report generation to run on failed states.
- **T4.3 Lockfile Destructive Truncation**:
  Verifies that `scheduler.py:216` opens `execution.lock` with mode `'w'`, causing inode truncation prior to `fcntl.flock()`.

---

## 4. Test Execution & Reporting Instructions

### Running the Entire Suite via Pytest:
```bash
python3 -m pytest tests/audit/ -v
```

### Running Individual Test Modules:
```bash
python3 -m pytest tests/audit/test_ast_integrity.py -v
python3 -m pytest tests/audit/test_frontend_resilience.py -v
python3 -m pytest tests/audit/test_atomic_persistence.py -v
python3 -m pytest tests/audit/test_scheduler_concurrency.py -v
```

### Running with Automated JSON Artifact Generation:
```bash
python3 tests/audit/run_audit_tests.py
```

---

## 5. Machine-Readable Result Schema (`tests/audit/audit_results.json`)

The test suite outputs execution findings conforming to the following structure:

```json
{
  "timestamp": "2026-10-16T04:30:00Z",
  "summary": {
    "total_tests": 15,
    "passed": 15,
    "failed": 0,
    "skipped": 0,
    "execution_time_seconds": 1.25
  },
  "tiers": {
    "tier_1_ast_integrity": {
      "status": "PASSED",
      "codegraph_synced": true,
      "core_symbols_verified": 14,
      "unresolved_core_references": 0,
      "kalman_mcs_disconnection_verified": true,
      "dead_functions_verified": 7
    },
    "tier_2_frontend_resilience": {
      "status": "PASSED",
      "tab_components_tested": 10,
      "components_with_error_boundary": 4,
      "components_lacking_error_boundary": 6,
      "null_trap_vulnerabilities_detected": 12
    },
    "tier_3_persistence_integrity": {
      "status": "PASSED",
      "direct_open_w_locations": 5,
      "parquet_files_scanned": 70,
      "distinct_parquet_schemas": 13,
      "max_jsonl_line_bytes": 24066,
      "posix_pipe_buf_exceeded": true
    },
    "tier_4_scheduler_concurrency": {
      "status": "PASSED",
      "market_monitor_mutex_isolated": false,
      "api_subprocess_mutex_isolated": false,
      "return_code_suppressed": true,
      "destructive_lock_truncation": true
    }
  },
  "tests": [
    {
      "nodeid": "tests/audit/test_ast_integrity.py::test_codegraph_sync_and_status",
      "outcome": "passed",
      "duration": 0.045
    }
  ]
}
```
