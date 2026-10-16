# QuantOS Full-Stack Codebase Audit: Master Executive Synthesis Report

**System**: QuantOS Algorithmic Trading Platform & Telemetry System  
**Version**: v7.0.0  
**Scope**: Full-Stack Architecture (Core Quantitative Engines, Data Lake Persistence, Frontend React UI, Background Automation)  
**Auditors**: QuantOS Technical Audit Taskforce  
**Date**: 2026-10-16  
**Artifact Path**: `/Users/mac/agent/reports/audit/MASTER_AUDIT_REPORT.md`  
**Downloads Replica**: `/Users/mac/Downloads/Antigravity_Exports/MASTER_AUDIT_REPORT.md`  

---

## 1. Executive Summary & Audit Scorecard (BLUF)

QuantOS is an event-driven quantitative trading system executing multi-regime statistical inference (GARCH volatility, HMM regime detection, SMC structural sweeps, session momentum), neural classification (multi-asset MLPs), fractional Kelly risk sizing, and paper trade execution. 

A full-stack audit across AST call graphs, React client components, Parquet data lake partitions, and background automation schedules identified **25 major findings**: **6 CRITICAL**, **9 HIGH**, **7 MEDIUM**, and **3 LOW**.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       QUANTOS AUDIT RISK SCORECARD                           │
├─────────────────────┬──────────┬──────────┬──────────┬──────────┬────────────┤
│ Domain              │ CRITICAL │   HIGH   │  MEDIUM  │   LOW    │ Total      │
├─────────────────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ AST Architecture    │    1     │    1     │    1     │    2     │     5      │
│ Frontend React UI   │    3     │    3     │    2     │    0     │     8      │
│ Data Lake & Storage │    1     │    3     │    2     │    0     │     6      │
│ Automation & Cron   │    1     │    2     │    2     │    1     │     6      │
├─────────────────────┼──────────┼──────────┼──────────┼──────────┼────────────┤
│ TOTAL FINDINGS      │    6     │    9     │    7     │    3     │    25      │
└─────────────────────┴──────────┴──────────┴──────────┴──────────┴────────────┘
```

### Key Takeaways
1. **Critical Live Execution Disconnection**: In `src/fetch_market_data.py`, `Conductor` never invokes `risk_engine.run_kalman_filter()` or `compute_mcs()`. As a result, `snapshot.kalman_state.dominant_state` remains default `"UNKNOWN"` and Monte Carlo stats remain empty. In live production, risk-off capital preservation gates are bypassed, while backtests execute them properly.
2. **State Destruction & Race Hazard**: Paper trading portfolio state (`paper_portfolio.json`), fundamental scores (`fundamental_scores.json`), and user configuration files bypass atomic writes, opening files with `open(path, 'w')`. An unexpected abort or concurrent read truncates files to 0 bytes, erasing cash, active positions, and order ledgers.
3. **Unprotected Process Collisions**: While `scheduler.py` uses `execution.lock`, emergency volatility triggers in `src/market_monitor.py:112` spawn `fetch_market_data.py` **without acquiring any lock**, causing concurrent pipeline executions that collide on files and double-spend cash.
4. **Widespread UI Single-Point-of-Failure Traps**: 6 of 10 React tabs lack error boundaries. Raw numeric methods (`.toFixed()`, `.replace()`) are invoked directly on unvalidated API payloads, causing blank-screen crashes on partial backend responses.
5. **Data Lake Partition Contamination & Schema Drift**: 13 distinct Parquet schemas exist across 70 daily files (161 to 212 columns), and `.parquet` and `.jsonl` files reside together in the same directory partitions, causing standard dataset query engines (PyArrow Dataset, DuckDB, Polars) to fail on scan.

---

## 2. Full-Stack Audit Domain Findings

### Domain 1: Architectural Topology & AST Call Graph Analysis (Requirement R1)

The CodeGraph knowledge graph was audited across 70 files (53 Python, 13 JSX, 3 JS, 1 YAML), comprising 861 AST nodes and 1,591 edges. Core symbol queries confirmed **0 unresolved references** among the 15 primary classes (`Conductor`, `FeatureEngine`, `RiskEngine`, `TrendEngine`, `SMCEngine`, `SessionEngine`, `LiquidityEngine`, `RegimeEnsemble`, `ConsensusEngine`, `EntryEngine`, `FrequencyController`, `OpportunityGate`, `EventBus`, `LakeManager`, `PaperBroker`).

#### Core Execution Path Trace
The primary execution path traces through five sequential pipeline stages:
```
scheduler.py (Cron) / market_monitor.py / api.py
       │
       ▼
src/fetch_market_data.py (Conductor.run)
       ├── Stage 1: Ingestion (YahooAdapter, ForexFactoryAdapter, LakeManager.save_tabular)
       ├── Stage 2: Feature Engineering (GARCH(1,1), VIX Z-Score, 20-D feature vector, MLP inference)
       ├── Stage 3: Quantitative Regimes (TrendEngine, SMCEngine, SessionEngine, RegimeEnsemble)
       ├── Stage 4: Epistemic Risk Sizing (RiskEngine.compute_multi_asset_kelly)  <-- [DEFECT: dominant_state="UNKNOWN"]
       ├── Stage 5: Consensus & Gating (ConsensusEngine, OpportunityGate)
       └── Stage 6: Settlement (PaperBroker.execute_rebalance, paper_ledger.csv)
```

#### Key Architectural Findings
- **Kalman Filter & MCS Omission (AUDIT-001, CRITICAL)**: `src/fetch_market_data.py:514,562,646`. In `Conductor`, `self.snapshot.kalman_state` defaults to `KalmanState()`. While `brier_score_calibration` is calculated, `risk_engine.run_kalman_filter()` is never called. Line 562 passes `dominant_state="UNKNOWN"` into `compute_multi_asset_kelly()`. The regime-specific safe haven hedge (`if dominant_state == "risk_off"`) is dead in production.
- **Monolithic Conductor Bottleneck (AUDIT-002, HIGH)**: `Conductor` tightly couples 12 sub-engines, 3 adapters, and persistence in a single monolithic class affecting 27 downstream symbols.
- **Disconnected Trading Configuration (AUDIT-003, MEDIUM)**: `/api/trading_settings` reads/writes `config/trading_settings.json`, but `Conductor` reads `config/tickers.json` and `data/state/trading_config.json`. Ticker toggle actions in `TradingTerminal.jsx` have zero effect on backend execution.
- **Dead Functions Catalog (AUDIT-004, LOW)**: `sign_snapshot_payload`, `check_mathematical_consistency`, `append_to_immutable_chain`, `compute_weekly_liquidity_boundaries`, `calculate_model_tvd`, `calculate_bayesian_conditional_probability` in `feature_engine.py` have 0 callsites.
- **Superseded Legacy Modules (AUDIT-005, LOW)**: `src/backtest.py` (superseded by `quantitative_backtester.py`), `src/train_models.py` (superseded by `src/training/train_models.py`), and 3 orphaned utility scripts.

---

### Domain 2: Frontend React UI & Error Resilience (Requirement R2)

The single-page dashboard contains 10 tab components and visualizer views: `OverviewTab`, `TradingTerminal`, `PaperTradingTab`, `MacroTab`, `FundamentalTab`, `MathModelTab`, `DiagnosticsTab`, `ReportsTab`, `SettingsTab`, and `PipelineVisualizer`.

#### Key Frontend Findings
- **Unhandled Null/Undefined API Payloads (AUDIT-006, CRITICAL)**: In `OverviewTab.jsx:14` (`data.regime.replace`), lines 106/110 (`entry_score.toFixed(2)`), and `TradingTerminal.jsx:35` (`active_tickers.map`), raw prototype methods are invoked without defensive checks. In `PaperTradingTab.jsx:222,246`, the guard `{portfolio.win_rate !== undefined}` evaluates to `true` when the backend returns `null`, causing `(null).toFixed()` to crash the component.
- **Missing Error Boundaries (AUDIT-007, CRITICAL)**: 6 of 10 tabs and the root application shell (`App.jsx`) have no `ErrorBoundary` protection. A single missing field in `/api/snapshot` or `/api/portfolio` crashes the entire interface into a white screen.
- **WebSocket Telemetry Lifecycle Defects (AUDIT-008, CRITICAL)**: `PipelineVisualizer.jsx` establishes a native WebSocket with no reconnect logic or error handlers. Heartbeat messages (`{"type": "heartbeat"}`) sent by FastAPI every 3 seconds set `activeComponent` to `undefined` (causing SVG DAG nodes to flicker off) and flood the 20-item log circular buffer, displacing real pipeline events.
- **Missing Development Proxy (AUDIT-009, HIGH)**: `frontend/vite.config.js` defines zero proxy rules. On `localhost:5173`, all REST and WebSocket calls fail immediately.
- **Ghost CSS Classes & Collapsed Progress Bars (AUDIT-010, HIGH)**: Ten CSS classes referenced in JSX do not exist in `index.css`: `.text-plasma-green`, `.text-plasma-red`, `.text-plasma-cyan`, `.text-plasma-purple`, `.text-plasma-amber`, `.text-purple`, `.btn-primary`, `.btn-danger`, `.progress-bg`, and `.progress-fill`. In `MathModelTab.jsx:27-28`, regime probability bars render at 0px height (invisible).
- **API Secret Field Missing in UI (AUDIT-011, HIGH)**: `SettingsTab.jsx` manages `apiSecret` in state and saves to `localStorage`, but the JSX omits an input field, preventing users from entering their API key.
- **1Hz Global Re-Render Cascade (AUDIT-012, MEDIUM)**: `App.jsx:66-69` stores a clock in root state via a 1000ms `setInterval`, forcing the entire active tab to re-evaluate 60 times a minute without `React.memo`.
- **Global `setInterval` Variable Shadowing (AUDIT-013, MEDIUM)**: `TradingTerminal.jsx:23` declares `const [interval, setInterval] = useState("D")`, shadowing the browser window timer.

---

### Domain 3: Data Lake & Persistence Integrity (Requirement R3)

QuantOS maintains an entirely file-based storage layer across `data/raw/` (Parquet, JSONL), `data/state/` (JSON), and `data/paper_trading/` (JSON, CSV).

#### Key Persistence Findings
- **Destructive Non-Atomic State Overwrite (AUDIT-014, CRITICAL)**: `PaperBroker._save_portfolio()` (`paper_broker.py:56`), `fundamental_agent/main.py:49`, and `api.py:578` write shared JSON state files using direct `open(path, 'w')`. An interruption truncates files to 0 bytes, erasing cash balance, positions, and user settings.
- **Parquet Schema Drift (AUDIT-015, HIGH)**: 13 distinct schema signatures exist across all 70 Parquet files in `data/raw/`, with column counts ranging from 161 to 212. Unordered MultiIndex flattening in `lake_manager.py:35-36` causes daily column order to randomize depending on thread completion.
- **Partition Contamination (AUDIT-016, HIGH)**: Tabular `.parquet` files and unstructured `.jsonl` files are stored in the same daily partition directory (`data/raw/YYYY/MM/DD/`). Standard loaders (`pyarrow.dataset.dataset("data/raw", format="parquet")`) fail on `events.jsonl`.
- **POSIX Line Atomicity Violations (AUDIT-017, HIGH)**: In `data/raw/` JSONL event streams, 823 lines exceed the 4,096-byte POSIX `PIPE_BUF` threshold (reaching 24,117 bytes). Concurrent appends interleave characters, corrupting JSON syntax.
- **Write-Only "Black Hole" Data Lake (AUDIT-018, MEDIUM)**: Despite writing Parquet files on every cycle, no backend engine or backtester reads from the data lake; all engines repeatedly re-fetch market data over the network.
- **Partial Atomic Write Missing `fsync` (AUDIT-019, MEDIUM)**: `atomic_json_write` in `fetch_market_data.py:48-61` does not invoke `f.flush()` and `os.fsync(fd)` prior to `os.replace`, risking corrupted destination links on abrupt termination.

---

### Domain 4: Automation & Background Scheduling (Requirement R4)

`scheduler.py` manages jobs via `APScheduler.BackgroundScheduler` (1H context scorer, 4H main execution, weekly synthesis).

#### Key Automation Findings
- **Concurrency Collision Between Monitor and Cron (AUDIT-020, CRITICAL)**: While `scheduler.py` uses `execution.lock`, `src/market_monitor.py:112` triggers `fetch_market_data.py` on volatility shocks **without acquiring any lock**. Dual processes collide on `paper_portfolio.json` and Parquet files, duplicating trades and double-spending cash.
- **Unbounded Blocking Mutex & Inode Truncation (AUDIT-021, HIGH)**: `run_locked_subprocess` uses `open(lock_path, 'w')` which truncates the lockfile while held by another process. Furthermore, `fcntl.flock(LOCK_EX)` blocks indefinitely with no timeout, risking thread exhaustion.
- **Child Process Return Code Suppression (AUDIT-022, HIGH)**: `subprocess.run(args)` runs with default `check=False`. Failures in data ingestion exit with code 1, but the scheduler ignores the exit code and proceeds to build reports and switch frequency against missing state.
- **Broken Mutex Boundary on Report Generation (AUDIT-023, MEDIUM)**: `run_4h` and `run_1d` release `execution.lock` immediately after `fetch_market_data.py` completes. `build_report.py` runs outside the lock, colliding with incoming 1H jobs.
- **Adaptive Frequency Rapid Execution Cascade (AUDIT-024, MEDIUM)**: Frequency changes re-add jobs with `next_run_time=datetime.now()`, triggering immediate executions that spam external APIs during volatile transitions.
- **Frequency Controller Hard-Cap (AUDIT-025, LOW)**: `frequency_controller.py:90-98` hard-caps recommendations at `"4h"`, rendering the `"1h"` scheduling branch unreachable in production.

---

## 3. Interactive Visual Audit Matrix Dashboard (Requirement R5)

To satisfy Requirement R5, a standalone, zero-dependency visual audit matrix dashboard has been created at:
**`/Users/mac/agent/reports/audit/dashboard/index.html`**  
*(Replicated to `/Users/mac/Downloads/Antigravity_Exports/dashboard/index.html`)*

### Dashboard Capabilities & Features
1. **Interactive Multi-Domain Matrix**:
   - Displays all 25 findings across AST, Frontend, Persistence, and Automation domains.
   - Dual viewing modes: High-density interactive card grid and structured tabular matrix.
2. **Dynamic Multi-Dimensional Filtering**:
   - Filter pills by severity: ALL (25), CRITICAL (6), HIGH (9), MEDIUM (7), LOW (3).
   - Domain filter pills: ALL, AST Architecture (5), Frontend React (8), Data Lake Persistence (6), Automation Scheduler (6).
   - Instant search bar querying Finding ID, title, affected symbols, blast radius, and code evidence.
3. **Drill-Down Inspection Modal**:
   - Clicking any finding opens an animated glassmorphic modal displaying Finding ID, severity badge, affected symbol chips, concrete evidence snippet with one-click copy, blast radius impact analysis, and step-by-step remediation plan.
4. **Actionable Remediation Tracker**:
   - Built-in interactive checklist drawer allowing engineering leads to toggle remediation status on each item.
   - Real-time progress bar computing resolution percentage live.
   - LocalStorage persistence preserving checklist completion state across sessions.
5. **Data Export Suite**:
   - One-click export to formatted `audit_evidence.json`.
   - One-click export to CSV spreadsheet format.
   - Standalone offline portability: functions directly from disk or web server.

---

## 4. Master Audit Findings Catalog & Severity Matrix

| Finding ID | Category | Severity | Title | Primary Affected Symbols | Blast Radius Summary |
|---|---|---|---|---|---|
| **AUDIT-001** | AST | **CRITICAL** | Kalman Filter and MCS Pipeline Disconnection | `src/fetch_market_data.py:Conductor`, `risk_engine.py` | 26 downstream symbols; risk-off capital preservation gates bypassed during live drawdowns. |
| **AUDIT-002** | AST | **HIGH** | Monolithic Conductor High-Fanout Bottleneck | `src/fetch_market_data.py:Conductor` | Monolithic coupling across 12 sub-engines; schema changes risk full pipeline regression. |
| **AUDIT-003** | AST | **MEDIUM** | Configuration Drift: TradingTerminal vs Conductor | `src/api.py`, `TradingTerminal.jsx` | User ticker toggle interactions fail silently; backend executes against separate files. |
| **AUDIT-004** | AST | **LOW** | Dead Functions in Feature Engine | `src/engines/feature_engine.py` (6 functions) | 6 uncalled functions inflate maintenance surface and obscure active mathematical models. |
| **AUDIT-005** | AST | **LOW** | Deprecated Legacy Modules and Orphaned Utilities | `src/backtest.py`, `src/train_models.py` | 5 outdated standalone files with incompatible schemas and duplicate logic. |
| **AUDIT-006** | Frontend | **CRITICAL** | Unhandled Null/Undefined API Payload Traps | `OverviewTab.jsx`, `TradingTerminal.jsx`, `PaperTradingTab.jsx` | Missing fields or null returns crash the React virtual DOM into an unrecoverable blank screen. |
| **AUDIT-007** | Frontend | **CRITICAL** | Missing Error Boundaries on 6 Tabs & App Shell | `frontend/src/App.jsx:121-131` | 60% of tab views lack error boundaries; local rendering error unmounts entire SPA. |
| **AUDIT-008** | Frontend | **CRITICAL** | WebSocket Lifecycle Breakdown & Heartbeat State Eviction | `PipelineVisualizer.jsx:9-35`, `src/api.py:75` | Silent socket death on disconnect; 3s heartbeats un-highlight nodes and flush real logs. |
| **AUDIT-009** | Frontend | **HIGH** | Missing Development Reverse Proxy in Vite Config | `frontend/vite.config.js` | Local development environment broken; cannot fetch API or connect to WebSocket directly. |
| **AUDIT-010** | Frontend | **HIGH** | Ghost CSS Classes & Collapsed Regime Progress Bars | `frontend/src/index.css`, `MathModelTab.jsx:27-28` | 10 missing CSS classes; regime probability bars render at 0px height (invisible). |
| **AUDIT-011** | Frontend | **HIGH** | API Secret Key Input Missing from Settings UI | `frontend/src/components/SettingsTab.jsx:12,63,85` | Users cannot input API keys when QUANTOS_SECRET is enabled, locking out trigger commands. |
| **AUDIT-012** | Frontend | **MEDIUM** | Cascading 1000ms Clock Re-Render Loop in App Root | `frontend/src/App.jsx:66-69` | Top-level clock state forces all active tab components to re-render 60 times a minute. |
| **AUDIT-013** | Frontend | **MEDIUM** | Global setInterval Variable Shadowing in TradingTerminal | `frontend/src/components/TradingTerminal.jsx:23` | Shadows window.setInterval, creating silent timer dispatch errors. |
| **AUDIT-014** | Persistence | **CRITICAL** | Destructive Non-Atomic State Overwrite Hazards | `paper_broker.py:56`, `fundamental_agent/main.py:49` | Direct `open('w')` writes risk 0-byte file truncation, erasing cash and portfolio positions. |
| **AUDIT-015** | Persistence | **HIGH** | Parquet Schema Drift Across 70 Daily Files | `src/data_lake/lake_manager.py:35-37` | 13 distinct schemas (161 to 212 cols) crash PyArrow and DuckDB multi-file scans. |
| **AUDIT-016** | Persistence | **HIGH** | Partition Directory Contamination | `src/data_lake/lake_manager.py:70,89` | Co-locating .parquet and .jsonl in same directories breaks dataset readers. |
| **AUDIT-017** | Persistence | **HIGH** | JSONL Appends Exceeding 4096B POSIX Limit | `src/data_lake/lake_manager.py:89` | Records up to 24KB split across kernel write buffers, corrupting JSONL log syntax. |
| **AUDIT-018** | Persistence | **MEDIUM** | Write-Only "Black Hole" Data Lake Anti-Pattern | `src/data_lake/lake_manager.py`, `src/fetch_market_data.py` | Parquet files are never read; system repeatedly re-downloads data from external APIs. |
| **AUDIT-019** | Persistence | **MEDIUM** | Partial Atomic Write Utility Lacking fsync Flush | `src/fetch_market_data.py:atomic_json_write` | Missing flush and fsync risks committing 0-byte destination links on abrupt termination. |
| **AUDIT-020** | Automation | **CRITICAL** | Concurrency Collision: Market Monitor vs Scheduler | `src/market_monitor.py:112`, `src/scheduler.py` | Market monitor spawns pipeline without lock, causing dual runs and double-spent cash. |
| **AUDIT-021** | Automation | **HIGH** | Unbounded Blocking Mutex & Inode Truncation | `src/scheduler.py:run_locked_subprocess` | `open('w')` truncates held lockfile; blocking flock risks permanent worker thread hang. |
| **AUDIT-022** | Automation | **HIGH** | Scheduler Child Process Failure Suppression | `src/scheduler.py:run_locked_subprocess` | Default `check=False` suppresses exit code 1; reports generate against missing state. |
| **AUDIT-023** | Automation | **MEDIUM** | Broken Mutex Boundary on Report Generation | `src/scheduler.py:run_4h`, `src/scheduler.py:run_1d` | Releasing lock before build_report.py creates race conditions with new 1H runs. |
| **AUDIT-024** | Automation | **MEDIUM** | Adaptive Frequency Rapid Execution Cascade | `src/scheduler.py:_apply_adaptive_frequency` | `next_run_time=datetime.now()` triggers back-to-back executions during volatile shifts. |
| **AUDIT-025** | Automation | **LOW** | Frequency Controller Hard-Cap at 4H Disconnecting 1H | `src/engines/frequency_controller.py:90-98` | Recommended frequency capped at 4H; 1H execution mode is unreachable dead code. |

---

## 5. Prioritized Engineering Remediation Roadmap

The remediation strategy is structured into five sequential phases to ensure production safety and risk containment:

```
[Phase 1: Week 1] State Persistence & Concurrency Locking (AUDIT-014, AUDIT-020, AUDIT-021)
       │
       ▼
[Phase 2: Week 1] Live Quantitative Pipeline Reconnection (AUDIT-001, AUDIT-003, AUDIT-022)
       │
       ▼
[Phase 3: Week 2] Frontend Error Resilience & Token Restoration (AUDIT-006, AUDIT-007, AUDIT-008, AUDIT-009, AUDIT-010, AUDIT-011)
       │
       ▼
[Phase 4: Week 2] Data Lake Partitioning & Schema Normalization (AUDIT-015, AUDIT-016, AUDIT-017, AUDIT-018)
       │
       ▼
[Phase 5: Week 3] Architectural Decoupling & Dead Code Purge (AUDIT-002, AUDIT-004, AUDIT-005, AUDIT-012, AUDIT-024, AUDIT-025)
```

### Phase 1: State Persistence & Concurrency Locking (Immediate)
1. **Centralized Atomic State I/O**: Deploy `src/persistence/atomic_io.py` using `tempfile.mkstemp`, `f.flush()`, `os.fsync(fd)`, and `os.replace`. Refactor `PaperBroker`, `fundamental_agent`, and `api.py` to use atomic writes.
2. **Unified Process Locking**: Wrap `market_monitor.py:112` in `run_locked_subprocess`. Modify `run_locked_subprocess` to open the lockfile in append mode (`'a'`) and apply a 600-second execution timeout.

### Phase 2: Live Quantitative Pipeline Reconnection
1. **Kalman Filter & MCS Activation**: In `src/fetch_market_data.py`, invoke `self.snapshot.kalman_state = self.risk_engine.run_kalman_filter(...)` and `compute_mcs(self.features_vector)`. Pass the resolved `dominant_state` to Kelly sizing and entry scoring.
2. **Configuration Synchronization**: Align `/api/trading_settings` to read/write `config/tickers.json` and `data/state/trading_config.json`.
3. **Subprocess Failure Handling**: In `scheduler.py`, assert `completed_process.returncode == 0` before triggering reports.

### Phase 3: Frontend Error Resilience & Design Tokens
1. **Defensive Coalescing**: Apply `?.` and `??` across all tab components to eliminate null/undefined exceptions.
2. **Tab-Level Error Boundaries**: Wrap every tab component in `App.jsx` with `<ErrorBoundary>`.
3. **Telemetry Lifecycle**: Add exponential backoff reconnect, filter out heartbeats (`if (data.type === 'heartbeat') return;`), and safely close sockets in `PipelineVisualizer.jsx`.
4. **Vite Development Proxy**: Configure `/api` and `/api/ws` reverse proxies in `vite.config.js`.
5. **CSS Token Fix**: Define missing plasma text classes and set `.progress-bg` and `.progress-fill` heights in `index.css`.
6. **Settings Tab Input**: Add input field for `apiSecret` in `SettingsTab.jsx`.

### Phase 4: Data Lake Schema Migration & Partition Separation
1. **Partition Segregation**: Separate tabular Parquet storage (`data/raw/ohlcv/`) from unstructured logs (`data/raw/events/`).
2. **Schema Standardization**: Enforce sorted column order and strict schema types in `LakeManager.save_tabular`.
3. **Local Cache Ingestion**: Update `YahooAdapter` to query local Parquet files before issuing external network requests.

### Phase 5: Architecture Modularization & Housekeeping
1. **Conductor Refactoring**: Split monolithic orchestrator into pipeline stages.
2. **Dead Code Deletion**: Purge uncalled functions from `feature_engine.py` and archive obsolete scripts.
3. **Clock Decoupling**: Extract leaf `<ClockDisplay>` component to eliminate root 1Hz re-render cascades.

---

## 6. Acceptance Criteria Verification Matrix

| Requirement Area | Acceptance Criterion (ORIGINAL_REQUEST.md) | Audit Status | Evidence / Verification Method |
|---|---|:---:|---|
| **AST & Architectural Integrity** | CodeGraph AST graph fully synced with zero unresolved dependencies on core symbols | **PASSED** | CodeGraph SQLite index verified (70 files, 861 nodes, 1591 edges, 0 unresolved refs on 15 core symbols). |
| **AST & Architectural Integrity** | Critical execution paths documented with call graph traces | **PASSED** | Complete call traces documented for Orchestrator → Feature Engine → Risk Engine → Paper Broker. |
| **AST & Architectural Integrity** | Dead functions or deprecated endpoints cataloged | **PASSED** | 6 dead functions in `feature_engine.py` and 5 superseded modules cataloged with line numbers. |
| **Frontend & UI Resilience** | All 10 React tab components tested against malformed or missing API payloads with no unhandled exceptions | **FAILED (Vulnerabilities Found)** | 6 of 10 tabs lack error boundaries; unhandled null traps cataloged with exact line numbers and reproduction proofs. |
| **Data Lake & Persistence** | State dumps verified to use atomic write semantics across all engines | **FAILED (Vulnerabilities Found)** | `paper_portfolio.json`, `fundamental_scores.json`, and `trading_config.json` use non-atomic `open('w')`. |
| **Automation & Concurrency** | Concurrent scheduler subprocesses verified not to collide on shared state files | **FAILED (Vulnerabilities Found)** | `market_monitor.py:112` bypasses `execution.lock`, colliding with scheduled cron jobs on shared files. |
| **Interactive Synthesis** | Synthesize all findings into an interactive visual matrix dashboard | **PASSED** | Interactive Visual Audit Matrix delivered in `reports/audit/dashboard/index.html` with filters, modals, checklist, and JSON/CSV export. |

---

## 7. Artifact Deliverables Index

All deliverables have been generated and replicated to the mandatory exports folder:

1. **Master Executive Report**:
   - Primary: `/Users/mac/agent/reports/audit/MASTER_AUDIT_REPORT.md`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/MASTER_AUDIT_REPORT.md`
2. **Frontend UI & Resilience Audit**:
   - Primary: `/Users/mac/agent/reports/audit/frontend_resilience_audit.md`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/frontend_resilience_audit.md`
3. **AST Architecture & Call Graph Audit**:
   - Primary: `/Users/mac/agent/reports/audit/ast_architecture_audit.md`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/ast_architecture_audit.md`
4. **Data Lake & Scheduler Concurrency Audit**:
   - Primary: `/Users/mac/agent/reports/audit/persistence_scheduler_audit.md`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/persistence_scheduler_audit.md`
5. **Master Consolidated Audit Evidence JSON**:
   - Primary: `/Users/mac/agent/reports/audit/audit_evidence.json`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/audit_evidence.json`
6. **Interactive Visual Audit Matrix Dashboard**:
   - Primary: `/Users/mac/agent/reports/audit/dashboard/index.html`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/dashboard/index.html`
   - Replica: `/Users/mac/Downloads/Antigravity_Exports/audit_matrix_dashboard.html`
