# QuantOS Frontend UI & Resilience Technical Audit

**Target System**: QuantOS Frontend Dashboard (`frontend/src/`)  
**Auditor**: Frontend Resilience & Visual Specialist  
**Integrity Mode**: Full-Stack Codebase Audit  
**Artifact Path**: `/Users/mac/agent/reports/audit/frontend_resilience_audit.md`  
**Downloads Replica**: `/Users/mac/Downloads/Antigravity_Exports/frontend_resilience_audit.md`  

---

## 1. Executive Summary & Bottom Line Up Front (BLUF)

QuantOS provides a single-page quantitative trading interface built on **React 19.2.6** and **Vite 8.0.12**, styled with a high-density Bloomberg-terminal design system. The user interface exposes 10 specialized tab components and visualization views that display Markov-regime models, Kelly sizing, live order ledgers, macroeconomic sentiment, and a real-time directed acyclic graph (DAG) pipeline visualizer.

Despite strong domain alignment and clear presentation of complex quantitative metrics, the frontend architecture contains critical defects that degrade runtime reliability and developer operations:

1. **Catastrophic Unhandled Null/Undefined Traps (6 of 10 Tabs Unprotected)**:
   Only 4 of the 10 tab components have `ErrorBoundary` encapsulation (`MacroTab`, `FundamentalTab`, `MathModelTab`, and `PipelineVisualizer`). The root application shell (`App.jsx`) and the remaining 6 tabs (`OverviewTab`, `TradingTerminal`, `PaperTradingTab`, `DiagnosticsTab`, `SettingsTab`, `ReportsTab`) lack error boundaries entirely. Across these components, raw numeric methods (`.toFixed()`, `.toLocaleString()`, `.slice()`, `.replace()`) are called directly on unvalidated API payloads. A single null field or missing key from FastAPI crashes the entire React application into an unrecoverable blank white screen.
2. **WebSocket Telemetry Lifecycle Breakdown & Heartbeat State Corruption**:
   The telemetry stream in `PipelineVisualizer.jsx` establishes an unauthenticated native WebSocket connection without reconnection logic, error recovery, or clean unmount handling. In React Strict Mode, closing a connection in `CONNECTING` state triggers unhandled exceptions. Crucially, backend keep-alive heartbeats (`{"type": "heartbeat"}`) are not filtered: each 3-second heartbeat passes `data.component === undefined`, instantly clearing active node highlights and evicting real pipeline log entries from the fixed 20-item display buffer.
3. **Broken Local Development Proxy**:
   `frontend/vite.config.js` defines zero proxy rules. Running `npm run dev` on port 5173 causes all REST requests (`/api/*`) and WebSocket connections (`/api/ws/pipeline`) to fail immediately with 404 or connection refused errors. The frontend cannot be tested locally without an external reverse proxy.
4. **Global 1Hz Re-Render Cascade**:
   `App.jsx` stores a formatted digital clock in top-level state via `setInterval` running every 1000ms. Because this state change occurs at the application root and none of the child tab components use `React.memo`, the entire virtual DOM tree re-evaluates every second.
5. **Ghost CSS Classes, Collapsed Progress Bars, and Token Drift**:
   Ten CSS classes referenced in JSX do not exist in `index.css`: `.text-plasma-green`, `.text-plasma-red`, `.text-plasma-cyan`, `.text-plasma-purple`, `.text-plasma-amber`, `.text-purple`, `.btn-primary`, `.btn-danger`, `.progress-bg`, and `.progress-fill`. Consequently, progress bars in `MathModelTab` render with 0px height (completely invisible), terminal buttons render as unstyled browser defaults, and regime indicator metrics default to monochrome text.
6. **Authentication UI Exclusion in `SettingsTab.jsx`**:
   While `SettingsTab.jsx` manages `apiSecret` in state and writes it to `localStorage.setItem('quantos_api_key', apiSecret)`, the JSX template completely omits an input element for this secret. When backend authentication (`QUANTOS_SECRET`) is enabled, users have no visual mechanism to enter the key, permanently locking them out of administrative trigger operations.

---

## 2. Comprehensive Inventory of React Tab Components

The application shell in `frontend/src/App.jsx` routes between 10 tab views using state-driven conditional mounting. The table below details every tab component, render trigger, state management structure, network transport, and error boundary protection status.

| # | Tab Component | Mount Condition | State / Props Model | Endpoints & Transport | ErrorBoundary | Primary Responsibility |
|---|---|---|---|---|---|---|
| **1** | `OverviewTab.jsx` | `activeTab === 'overview'` | Props: `data`, `timeZone` | `/api/snapshot`, `/api/decision` (Polled in App) | **NONE (UNPROTECTED)** | Executive dashboard: HMM regime, Kelly allocation, market pulse, macro indicators, and trade recommendations. |
| **2** | `TradingTerminal.jsx` | `activeTab === 'terminal'` | Local State: `activeTickers`, `selectedTicker`, `interval`, `portfolio`, `ledger`, `fundamentals` | `/api/trading_settings` (GET/POST), `/api/portfolio?type=backtest`, `/api/fundamentals` | **NONE (UNPROTECTED)** | Multi-asset chart workstation: embeds TradingView iframe, asset toggle sidebar, execution ledger, and position stats. |
| **3** | `PaperTradingTab.jsx` | `activeTab === 'trading'` | Local State: `viewType`, `disabledTickers`, `triggerStatus`, `data`, `nextUpdate`, `refreshing` | `/api/trading_config` (GET/POST), `/api/portfolio?type={viewType}` (10s poll), `/api/trigger` (POST), `/api/chart/{ticker}` (60s poll) | **NONE (UNPROTECTED)** | Paper execution simulator: live vs backtest toggle, ticker configuration, Sharpe ratio, alpha vs SPX, max drawdown, and live price tickers. |
| **4** | `MacroTab.jsx` | `activeTab === 'macro'` | Wrapped in `ErrorBoundary`. State: `macroData`, `loading`, `lastFetch`, `retrying` | `/api/macro` (60s poll), `/api/trigger` (POST) | Protected (`MacroTabContent`) | LLM Macro sentiment reasoning, directional bias (LONG/SHORT/FLAT), conviction score, quantitative divergence warnings, and economic calendar. |
| **5** | `FundamentalTab.jsx` | `activeTab === 'fundamentals'` | Wrapped in `ErrorBoundary`. State: `fundamentals`, `loading` | `/api/fundamentals` (GET on mount) | Protected (`FundamentalTabContent`) | Fundamental equity research: conviction score, valuation reasoning, and categorized qualitative insights. |
| **6** | `MathModelTab.jsx` | `activeTab === 'model'` | Wrapped in `ErrorBoundary`. State: `modelData`, `lastUpdate` | `/api/model` (10s poll) | Protected (`MathModelTabContent`) | Quantitative feature vector inspector (30+ features), Epistemic metrics (Brier score, Kelly), HMM regime probabilities, Kalman filter state, SMC state machine, and MLP consensus. |
| **7** | `DiagnosticsTab.jsx` | `activeTab === 'logs'` | Local State: `logs`, `isAutoScroll`, `terminalEndRef` | `/api/logs` (5s poll) | **NONE (UNPROTECTED)** | Live system diagnostics console: real-time streaming execution logs, log level classification (INFO, WARNING, ERROR), and auto-scroll terminal pane. |
| **8** | `ReportsTab.jsx` | `activeTab === 'reports'` | Local State: `reports`, `selectedReport`, `reportContent`, `triggerStatus` | `/api/reports`, `/reports/{filename}`, `/api/trigger` (POST) | **NONE (UNPROTECTED)** | Manual execution override controls (1H, 1D, 1W, Test), reports markdown archive browser, file previewer, and host for `PipelineVisualizer`. |
| **9** | `SettingsTab.jsx` | `activeTab === 'settings'` | Local State: `settings`, `inputs`, `isSaving`, `saveSuccess`, `apiSecret` | `/api/settings` (GET/POST with `X-Api-Key`) | **NONE (UNPROTECTED)** | API configuration: Google Gemini key, FRED API key, Discord webhook URL, key masking, and local storage credential management. |
| **10** | `PipelineVisualizer.jsx` | Embedded in `ReportsTab.jsx` | Wrapped in `ErrorBoundary`. State: `logs`, `activeComponent`, `activeMessage`, `wsRef` | `ws://<host>/api/ws/pipeline` (WebSocket) | Protected (Inside `ReportsTab`) | Real-time topological DAG execution graph: animated SVG pipeline nodes (Conductor, Ingestion, Filters, Consensus, Risk, Lake) with WebSocket telemetry stream. |

---

## 3. Deep Analysis of Unhandled Null/Undefined API Payload Vulnerabilities

In JavaScript, calling standard prototype methods (`.toFixed()`, `.replace()`, `.map()`, `.slice()`, `.toLocaleString()`) on `null` or `undefined` throws an immediate `TypeError`. Because React 16+ unmounts the entire component tree when an error is uncaught by an `ErrorBoundary`, these unsafe calls represent catastrophic single-point-of-failure vulnerabilities.

### 3.1 `App.jsx` (Root Shell)
- **Line 81**:
  ```jsx
  <span className="text-cyan">{data.regime.replace(/_/g, ' ')}</span>
  ```
  *Defect*: If `/api/snapshot` returns `{ "regime": null }` or if the initial fetch fails, `data.regime` is null. Calling `.replace()` immediately throws `TypeError: Cannot read properties of null (reading 'replace')`.
- **Line 82**:
  ```jsx
  <span className="text-purple">{(data.regimeProb * 100).toFixed(1)}%</span>
  ```
  *Defect*: If `regimeProb` is `null` or `undefined`, evaluation produces `NaN.toFixed(1)` or throws `TypeError`.

### 3.2 `OverviewTab.jsx`
- **Line 14**: `{data.regime.replace(/_/g, ' ')}`
  *Defect*: Throws `TypeError` if `data.regime` is missing or null.
- **Line 19**: `{(data.regimeProb * 100).toFixed(1)}%`
  *Defect*: Unhandled numeric call without null coalesce.
- **Line 43**: `{(data.kelly * 100).toFixed(1)}%`
  *Defect*: If `data.kelly` is null, crashes the tab.
- **Lines 106 & 110**:
  ```jsx
  <span className="stat-value">{data.decision.entry_score.toFixed(2)}</span>
  ...
  <span className="stat-value">{data.decision.macro_conviction.toFixed(2)}</span>
  ```
  *Defect*: When backend quantitative engines return `None` (serialized as `null` in JSON) for uncalculated scores, calling `.toFixed(2)` throws `TypeError: Cannot read properties of null (reading 'toFixed')`.

### 3.3 `TradingTerminal.jsx`
- **Line 35**:
  ```jsx
  setActiveTickers(data.active_tickers.map(t => t.toUpperCase()));
  ```
  *Defect*: If `/api/trading_settings` returns an error payload (e.g. `{"detail": "Internal Server Error"}`), `data.active_tickers` is `undefined`. Line 35 throws `TypeError: Cannot read properties of undefined (reading 'map')`.
- **Line 70 & Line 207**:
  ```jsx
  setLedger(data.ledger)
  ...
  {ledger.slice(0, 50).map((trade, i) => ...)}
  ```
  *Defect*: If `/api/portfolio` returns `{ "error": "..." }` or `data.ledger` is not an array, `ledger.slice` throws `TypeError: ledger.slice is not a function`.
- **Line 141**: `{fundamentals[selectedTicker].conviction_score.toFixed(2)}`
  *Defect*: If `conviction_score` is null or if `selectedTicker` does not exist in `fundamentals`, throws `TypeError`.
- **Line 174**: `{portfolio.equity.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
  *Defect*: If `portfolio.equity` is null, throws `TypeError`.
- **Line 23**: Variable Shadowing Hazard:
  ```jsx
  const [interval, setInterval] = useState("D");
  ```
  *Defect*: Declaring a state setter named `setInterval` directly shadows `window.setInterval` inside the component closure, preventing any timer usage.

### 3.4 `PaperTradingTab.jsx`
- **Lines 133–134**:
  ```jsx
  const { portfolio, ledger } = data;
  const pnl = portfolio.total_equity - 10000.0;
  ```
  *Defect*: If `/api/portfolio` returns an error status or malformed object, `data.portfolio` is `undefined`. Line 134 throws `TypeError: Cannot read properties of undefined (reading 'total_equity')`.
- **The `null !== undefined` Logical Fallacy (Lines 222, 246, 255, 261, 267)**:
  ```jsx
  {portfolio.win_rate !== undefined && (
    <p>{portfolio.win_rate.toFixed(1)}%</p>
  )}
  {portfolio.sharpe_ratio !== undefined && (
    <p>{portfolio.sharpe_ratio.toFixed(2)}</p>
  )}
  {portfolio.alpha_vs_spx !== undefined && (
    <p>{portfolio.alpha_vs_spx.toFixed(2)}%</p>
  )}
  {portfolio.max_drawdown !== undefined && (
    <p>{portfolio.max_drawdown.toFixed(1)}%</p>
  )}
  ```
  *Defect*: In JavaScript, `null !== undefined` evaluates to **`true`**. When Python serializes a `None` float as JSON `null`, the guard condition passes, and `(null).toFixed()` is immediately invoked, crashing the component with `TypeError: Cannot read properties of null (reading 'toFixed')`!
- **Lines 295 & 306**:
  ```jsx
  Object.keys(portfolio.positions).length
  Object.entries(portfolio.positions).map(...)
  ```
  *Defect*: If `portfolio.positions` is null, `Object.keys(null)` throws `TypeError: Cannot convert undefined or null to object`.

### 3.5 `FundamentalTab.jsx`
- **Line 32**: `if (data.reasoning === "Not an equity.")`
  *Defect*: If an asset entry in `fundamentals` is a primitive or null, throws `TypeError`.
- **Line 37**: `{data.conviction_score.toFixed(2)}`
  *Defect*: If `conviction_score` is null, throws `TypeError`.

### 3.6 `MathModelTab.jsx`
- **Lines 207–208**:
  ```jsx
  {mlp_deep_state && Object.entries(mlp_deep_state).map(([asset, preds]) => {
    const bullP = (preds.bull_probability || 0) * 100;
  ```
  *Defect*: If `preds` is null (e.g. `{"SPX": null}`), reading `preds.bull_probability` throws `TypeError: Cannot read properties of null`.

### 3.7 `ReportsTab.jsx`
- **Line 154**: `{r.filename.replace('updates/', '')}`
  *Defect*: If an item in `reports` lacks `filename`, throws `TypeError: Cannot read properties of undefined (reading 'replace')`.
- **Line 158**: `formatSize(r.size)` -> `(bytes / 1024).toFixed(1)`
  *Defect*: If `r.size` is undefined, `(NaN).toFixed(1)` outputs `"NaN KB"`; if `r` is null, throws `TypeError`.

---

## 4. WebSocket Telemetry Lifecycle Defects

The WebSocket client for real-time pipeline visualization is implemented in `frontend/src/components/PipelineVisualizer.jsx`:

```jsx
// PipelineVisualizer.jsx:9-35
useEffect(() => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/api/ws/pipeline`;
  
  wsRef.current = new WebSocket(wsUrl);

  wsRef.current.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      setLogs(prev => [...prev, data].slice(-20));
      
      setActiveComponent(data.component);
      setActiveMessage(data.message);

      if (data.message && data.message.includes("Complete")) {
          setActiveComponent("complete");
      }
    } catch (e) {
      console.error("WS Parse Error", e);
    }
  };

  return () => {
    if (wsRef.current) wsRef.current.close();
  };
}, []);
```

### 4.1 Lack of Reconnection Logic (Silent Failure)
The component defines only `wsRef.current.onmessage`. There are no handlers for `onerror` or `onclose`. If the backend process reloads (e.g., during uvicorn hot-reload or scheduled restart) or a network packet drops, the socket closes silently. The visualizer remains permanently disconnected and frozen until the user reloads the browser tab.

### 4.2 Backend Heartbeat Collision Bug
In `src/api.py:75-76`, FastAPI sends periodic heartbeat frames:
```python
await websocket.send_json({"type": "heartbeat", "ts": datetime.utcnow().isoformat()})
```
When `PipelineVisualizer.jsx` parses this JSON:
1. `data.component` is `undefined`.
2. `setActiveComponent(data.component)` sets `activeComponent` to `undefined`.
3. The currently highlighted active node in the SVG DAG immediately loses its highlight, causing erratic flickering every 3 seconds.
4. `setLogs(prev => [...prev, data].slice(-20))` pushes the heartbeat object into the log array. Because the buffer retains only the last 20 entries, continuous heartbeats displace and wipe out actual pipeline execution logs.

### 4.3 Strict Mode Unmount Race Condition
In React 18/19 StrictMode, components mount, unmount, and remount immediately upon initial load. If the cleanup function executes while `wsRef.current` is still in the `WebSocket.CONNECTING` state (`readyState === 0`), calling `.close()` produces a browser console warning or DOMException. Furthermore, event handlers are not cleared, leading to dangling references.

### 4.4 Vite Development Proxy Void
In `frontend/vite.config.js`:
```javascript
export default defineConfig({
  plugins: [react()],
})
```
Because no proxy configuration exists, `window.location.host` evaluates to `localhost:5173`. The browser attempts to open `ws://localhost:5173/api/ws/pipeline`. Vite's HTTP server does not handle this route and immediately terminates the handshake with a 404 or connection error. Local development without an external Nginx proxy is impossible.

---

## 5. Render Efficiency, Design Token Consistency & CSS Audit

### 5.1 1Hz Clock Re-Render Cascade in `App.jsx`
In `frontend/src/App.jsx:66-69`:
```jsx
const [clock, setClock] = useState(() => formatClock(new Date(), 'Local'));
...
useEffect(() => {
  const tick = setInterval(() => setClock(formatClock(new Date(), timeZone)), 1000);
  return () => clearInterval(tick);
}, [timeZone]);
```
- **Cascade Mechanism**: `clock` is declared at the root of `App`. Every 1000ms, `setClock` triggers a complete re-render of `App`.
- **Downstream Waste**: None of the 10 tab components are wrapped in `React.memo`. Consequently, whichever tab is currently mounted (`OverviewTab`, `TradingTerminal`, `PaperTradingTab`, etc.) is re-evaluated 60 times every minute, wasting CPU cycles and recalculating complex layouts.
- **Remediation**: Extract the clock into an isolated leaf component (`<ClockDisplay timeZone={timeZone} />`) that maintains its own internal timer, isolating updates completely from `App`.

### 5.2 The "Ghost" CSS Classes Audit
Multiple components reference CSS utility classes that do not exist in `frontend/src/index.css`:

| Missing CSS Class | File & Line References | Visual Impact |
|---|---|---|
| `.text-plasma-green` | `OverviewTab.jsx:23, 42, 55, 71, 81, 83, 141` | Indicator numbers have no green accent; fallback to monochrome amber. |
| `.text-plasma-red` | `OverviewTab.jsx:55, 82` | Negative risk indicators lack red accent. |
| `.text-plasma-cyan` | `OverviewTab.jsx:13` | Regime heading lacks cyan styling. |
| `.text-plasma-purple` | `OverviewTab.jsx:19` | Probability percentages lack purple styling. |
| `.text-plasma-amber` | `OverviewTab.jsx:68, 69, 84, 115` | Warnings lack amber alert color. |
| `.text-purple` | `PaperTradingTab.jsx:283` | Conviction metrics lack purple styling. |
| `.btn-primary` | `MacroTab.jsx:67`, `ReportsTab.jsx:102, 105, 108` | Action buttons render as plain unstyled browser buttons without border, background, or hover states. |
| `.btn-danger` | `ReportsTab.jsx:112` | Diagnostic backtest button lacks red danger styling. |
| `.progress-bg` | `MathModelTab.jsx:27` | Progress container lacks height, background, and border-radius. |
| `.progress-fill` | `MathModelTab.jsx:28` | Progress fill has no height specified; **bars render at 0px height (completely invisible)**. |

### 5.3 Missing `:root` CSS Variables
- In `DiagnosticsTab.jsx:67, 73`:
  ```jsx
  backgroundColor: 'var(--void)'
  border: '1px solid var(--glass-border)'
  ```
  Neither `--void` nor `--glass-border` is defined in `index.css :root`. The terminal pane background defaults to transparent and border to invalid.

### 5.4 Dead Starter Template Residue
`frontend/src/App.css` contains 185 lines of default Vite template CSS (`.counter`, `.hero`, `.base`, `#center`, `#docs`, `#spacer`). This stylesheet is never imported by `App.jsx` or any component, representing unreferenced dead code.

---

## 6. Actionable Remediation Blueprints

### Blueprint 1: Vite Development Proxy Configuration
Update `frontend/vite.config.js` to route API and WebSocket requests to the local FastAPI backend on port 8000:

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/reports': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
```

### Blueprint 2: Universal Tab-Level Error Boundary Wrapping
Wrap the active tab switchboard in `frontend/src/App.jsx` with individual `<ErrorBoundary>` components to prevent a single tab failure from unmounting the root shell:

```jsx
import ErrorBoundary from './components/ErrorBoundary';

{/* Main Tab Content */}
<main>
  <ErrorBoundary>
    {activeTab === 'overview' && <OverviewTab data={data} timeZone={timeZone} />}
    {activeTab === 'terminal' && <TradingTerminal timeZone={timeZone} />}
    {activeTab === 'trading' && <PaperTradingTab timeZone={timeZone} />}
    {activeTab === 'macro' && <MacroTab timeZone={timeZone} />}
    {activeTab === 'fundamentals' && <FundamentalTab />}
    {activeTab === 'model' && <MathModelTab timeZone={timeZone} />}
    {activeTab === 'logs' && <DiagnosticsTab timeZone={timeZone} />}
    {activeTab === 'reports' && <ReportsTab timeZone={timeZone} />}
    {activeTab === 'settings' && <SettingsTab />}
  </ErrorBoundary>
</main>
```

### Blueprint 3: Resilient WebSocket Telemetry Hook with Heartbeat Filtering
Replace the unmanaged WebSocket in `frontend/src/components/PipelineVisualizer.jsx` with an auto-reconnecting lifecycle hook:

```javascript
useEffect(() => {
  let ws = null;
  let reconnectTimer = null;
  let isMounted = true;
  let retryCount = 0;

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    ws = new WebSocket(`${protocol}//${host}/api/ws/pipeline`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Guard against heartbeat collision
        if (data.type === 'heartbeat') return;
        
        setLogs(prev => [...prev, data].slice(-20));
        if (data.component) setActiveComponent(data.component);
        if (data.message) setActiveMessage(data.message);
        if (data.message?.includes("Complete")) setActiveComponent("complete");
      } catch (e) {
        console.error("WS Parse Error", e);
      }
    };

    ws.onclose = () => {
      if (!isMounted) return;
      const timeout = Math.min(1000 * Math.pow(1.5, retryCount), 10000);
      reconnectTimer = setTimeout(() => {
        retryCount++;
        connect();
      }, timeout);
    };

    ws.onerror = () => {
      if (ws.readyState === WebSocket.OPEN) ws.close();
    };
  };

  connect();

  return () => {
    isMounted = false;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) {
      ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }
  };
}, []);
```

### Blueprint 4: Restoring Ghost CSS Classes and Progress Bars
Append the missing class definitions and `:root` variables to `frontend/src/index.css`:

```css
/* Missing Plasma & Utility Classes */
.text-plasma-cyan { color: var(--term-cyan); }
.text-plasma-purple { color: var(--term-purple); }
.text-plasma-amber { color: var(--term-amber); }
.text-plasma-green { color: var(--term-green); }
.text-plasma-red { color: var(--term-red); }
.text-purple { color: var(--term-purple); }

/* Missing Button Classes */
.btn-primary {
  background: rgba(0, 255, 0, 0.1);
  color: var(--term-green);
  border: 1px solid var(--term-green);
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  text-transform: uppercase;
  transition: all 0.2s ease;
}
.btn-primary:hover {
  background: var(--term-green);
  color: #000;
}
.btn-danger {
  background: rgba(255, 0, 0, 0.1);
  color: var(--term-red);
  border: 1px solid var(--term-red);
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  text-transform: uppercase;
  transition: all 0.2s ease;
}
.btn-danger:hover {
  background: var(--term-red);
  color: #000;
}

/* Missing Progress Bar Styles */
.progress-bg {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

/* Missing Theme Variables */
:root {
  --void: #050505;
  --glass-border: #222222;
}
```

### Blueprint 5: API Secret Input in `SettingsTab.jsx`
Add the missing input field for `apiSecret` inside `frontend/src/components/SettingsTab.jsx`:

```jsx
<div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '16px' }}>
  <label style={{ fontWeight: 'bold' }}>QuantOS API Key (Secret)</label>
  <p className="text-muted" style={{ fontSize: '0.8rem' }}>Required for authenticated trigger commands.</p>
  <input 
    type="password"
    placeholder="Enter QuantOS API Secret..."
    value={apiSecret}
    onChange={(e) => setApiSecret(e.target.value)}
    style={{ padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'monospace' }}
  />
</div>
```

### Blueprint 6: Decouple Clock Leaf Component to Stop 1Hz Root Re-Renders
Extract the clock from `App.jsx` into an isolated component:

```jsx
function ClockDisplay({ timeZone }) {
  const [clock, setClock] = useState(() => formatClock(new Date(), timeZone));
  useEffect(() => {
    const tick = setInterval(() => setClock(formatClock(new Date(), timeZone)), 1000);
    return () => clearInterval(tick);
  }, [timeZone]);
  return <span className="text-muted" style={{ marginLeft: "8px" }}>{clock}</span>;
}
```

---

## 7. Verification Method

1. **Proxy Verification**: Start Vite dev server with proxy enabled. Execute `curl -I http://localhost:5173/api/snapshot` and verify that requests return `HTTP/1.1 200 OK` from the FastAPI backend.
2. **Null Injection Resilience**: Mock `/api/snapshot`, `/api/decision`, `/api/portfolio`, `/api/macro`, and `/api/model` with `{}` and null values. Verify that each tab renders fallback UI without unhandled exceptions or unmounting the root tree.
3. **WebSocket Disconnect & Reconnect**: Connect `PipelineVisualizer` to the backend WebSocket stream, terminate the backend server, restart it, and confirm the client automatically reconnects within 3 seconds.
4. **CSS Token & Visual Test**: Inspect `MathModelTab` in browser developer tools and verify that `.progress-fill` has computed `height: 6px` and that `.btn-primary` renders green borders and text.
5. **Settings Key Persistence**: Enter an API secret in `SettingsTab`, save, and inspect `localStorage.getItem('quantos_api_key')` to confirm storage and header attachment on `/api/trigger`.
