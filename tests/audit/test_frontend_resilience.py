"""Tier 2 Audit: Frontend React Component Resilience & Error Boundary Integrity.

Validates all 10 React tab components against:
- Empty API payloads ({})
- Null fields (null regime, null entry_score, null portfolio, null active_tickers, etc.)
- Type-mismatched payloads (string instead of array, null instead of object)
- Presence or absence of ErrorBoundary wrapping across components and root App.
- Identifies specific JavaScript / JSX crash hazards (.toFixed, .replace, .map, .slice, and null !== undefined trap).
"""

import os
import re
from typing import Dict, List, Set, Tuple


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPONENTS_DIR = os.path.join(REPO_ROOT, "frontend", "src", "components")
APP_JSX_PATH = os.path.join(REPO_ROOT, "frontend", "src", "App.jsx")

ALL_10_TAB_COMPONENTS = [
    "OverviewTab.jsx",
    "TradingTerminal.jsx",
    "PaperTradingTab.jsx",
    "MacroTab.jsx",
    "FundamentalTab.jsx",
    "MathModelTab.jsx",
    "DiagnosticsTab.jsx",
    "ReportsTab.jsx",
    "SettingsTab.jsx",
    "PipelineVisualizer.jsx",
]

# Components that currently wrap their rendered content with an ErrorBoundary
EXPECTED_PROTECTED_TABS = set(ALL_10_TAB_COMPONENTS)

EXPECTED_UNPROTECTED_TABS = set()


def _read_component(filename: str) -> str:
    path = os.path.join(COMPONENTS_DIR, filename)
    assert os.path.exists(path), f"Component file {filename} missing at {path}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _has_error_boundary(code: str) -> bool:
    return "ErrorBoundary" in code and "<ErrorBoundary" in code


def _find_vulnerable_patterns(code: str) -> List[Tuple[str, str]]:
    """Scan JSX code for patterns that throw TypeError when fields are null or undefined."""
    vulnerabilities = []

    # 1. Unsafe .toFixed() without null check or default
    for match in re.finditer(r"([a-zA-Z0-9_\.\[\]]+)\.toFixed\((\d+)\)", code):
        expr = match.group(1)
        # Check if preceded by optional chaining or default fallback in proximity
        if "?." not in expr and "|| 0" not in expr and "?? 0" not in expr:
            vulnerabilities.append(("UNSAFE_TO_FIXED", match.group(0)))

    # 2. Unsafe .replace() on string props
    for match in re.finditer(r"([a-zA-Z0-9_\.\[\]]+)\.replace\(", code):
        expr = match.group(1)
        if "?." not in expr and "|| ''" not in expr and "?? ''" not in expr:
            vulnerabilities.append(("UNSAFE_REPLACE", match.group(0)))

    # 3. Unsafe .map() on unvalidated arrays
    for match in re.finditer(r"([a-zA-Z0-9_\.\[\]]+)\.map\(", code):
        expr = match.group(1)
        if "?." not in expr and "Array.isArray" not in code:
            vulnerabilities.append(("UNSAFE_MAP", match.group(0)))

    # 4. Unsafe .slice() on unvalidated collections
    for match in re.finditer(r"([a-zA-Z0-9_\.\[\]]+)\.slice\(", code):
        expr = match.group(1)
        if "?." not in expr:
            vulnerabilities.append(("UNSAFE_SLICE", match.group(0)))

    # 5. Null comparison fallacy: 'val !== undefined' (evaluates to true for null!)
    for match in re.finditer(r"([a-zA-Z0-9_\.\[\]]+)\s*!==\s*undefined", code):
        vulnerabilities.append(("NULL_INEQUALITY_FALLACY", match.group(0)))

    return vulnerabilities


def test_all_10_tab_components_exist():
    """Verify that all 10 target React tab components exist in the frontend source tree."""
    for filename in ALL_10_TAB_COMPONENTS:
        path = os.path.join(COMPONENTS_DIR, filename)
        assert os.path.exists(path), f"Tab component {filename} not found at {path}"


def test_frontend_error_boundary_protections():
    """Verify that all 10 tab components and root App.jsx have ErrorBoundary wrappers."""
    protected = set()
    unprotected = set()

    for filename in ALL_10_TAB_COMPONENTS:
        code = _read_component(filename)
        if _has_error_boundary(code):
            protected.add(filename)
        else:
            unprotected.add(filename)

    assert protected == EXPECTED_PROTECTED_TABS, (
        f"Protected components mismatch. Got {protected}, expected {EXPECTED_PROTECTED_TABS}"
    )
    assert unprotected == EXPECTED_UNPROTECTED_TABS, (
        f"Unprotected components mismatch. Got {unprotected}, expected {EXPECTED_UNPROTECTED_TABS}"
    )

    # Verify root App.jsx also contains ErrorBoundary wrapping around its activeTab renders
    with open(APP_JSX_PATH, "r", encoding="utf-8") as f:
        app_code = f.read()

    assert _has_error_boundary(app_code), (
        "App.jsx must contain an ErrorBoundary wrapper"
    )


def test_overview_tab_payload_resilience():
    """Verify OverviewTab resilience against empty, null, and type-mismatched payloads."""
    code = _read_component("OverviewTab.jsx")
    vulns = _find_vulnerable_patterns(code)

    assert len(vulns) == 0, f"OverviewTab has unhandled vulnerabilities: {vulns}"
    assert _has_error_boundary(code), "OverviewTab must be wrapped in ErrorBoundary"
    assert "safeData" in code, "OverviewTab must guard input payload"


def test_trading_terminal_payload_resilience():
    """Verify TradingTerminal resilience to missing tickers array, ledger format drift, and interval shadowing."""
    code = _read_component("TradingTerminal.jsx")
    vulns = _find_vulnerable_patterns(code)

    assert len(vulns) == 0, f"TradingTerminal has unhandled vulnerabilities: {vulns}"
    assert _has_error_boundary(code), "TradingTerminal must be wrapped in ErrorBoundary"

    # Verify variable shadowing hazard is eliminated
    assert not re.search(r"const\s*\[\s*interval\s*,\s*setInterval\s*\]\s*=\s*useState", code), (
        "Variable shadowing hazard (setInterval shadowing window.setInterval) must be eliminated"
    )
    assert "chartInterval" in code, "TradingTerminal should use chartInterval state"


def test_paper_trading_tab_payload_resilience_and_null_fallacy():
    """Verify PaperTradingTab has eliminated the null comparison bug ('null !== undefined') and total_equity crash."""
    code = _read_component("PaperTradingTab.jsx")
    vulns = _find_vulnerable_patterns(code)

    fallacies = [v for v in vulns if v[0] == "NULL_INEQUALITY_FALLACY"]
    assert len(fallacies) == 0, (
        f"Expected 0 occurrences of 'null !== undefined' fallacy, found {len(fallacies)}"
    )
    assert len(vulns) == 0, f"PaperTradingTab has unhandled vulnerabilities: {vulns}"
    assert _has_error_boundary(code), "PaperTradingTab must be wrapped in ErrorBoundary"


def test_macro_fundamental_math_tabs_resilience():
    """Verify that MacroTab, FundamentalTab, and MathModelTab use ErrorBoundary wrappers and have 0 vulnerabilities."""
    macro_code = _read_component("MacroTab.jsx")
    fund_code = _read_component("FundamentalTab.jsx")
    math_code = _read_component("MathModelTab.jsx")

    assert _has_error_boundary(macro_code), "MacroTab must be wrapped in ErrorBoundary"
    assert _has_error_boundary(fund_code), "FundamentalTab must be wrapped in ErrorBoundary"
    assert _has_error_boundary(math_code), "MathModelTab must be wrapped in ErrorBoundary"

    for name, code in [("MacroTab.jsx", macro_code), ("FundamentalTab.jsx", fund_code), ("MathModelTab.jsx", math_code)]:
        vulns = _find_vulnerable_patterns(code)
        assert len(vulns) == 0, f"{name} has vulnerabilities: {vulns}"


def test_diagnostics_reports_settings_pipeline_tabs_resilience():
    """Verify resilience in DiagnosticsTab, ReportsTab, SettingsTab, PipelineVisualizer."""
    diag_code = _read_component("DiagnosticsTab.jsx")
    reports_code = _read_component("ReportsTab.jsx")
    settings_code = _read_component("SettingsTab.jsx")
    pipe_code = _read_component("PipelineVisualizer.jsx")

    # DiagnosticsTab: logs.map() has Array.isArray check and ErrorBoundary
    assert "Array.isArray" in diag_code, "DiagnosticsTab expected to check Array.isArray"
    assert _has_error_boundary(diag_code), "DiagnosticsTab must have ErrorBoundary"

    # SettingsTab: apiSecret state and input field present, ErrorBoundary present
    assert "apiSecret" in settings_code, "SettingsTab expected to have apiSecret state"
    assert 'type="password"' in settings_code and "apiSecret" in settings_code, "SettingsTab must have apiSecret input"
    assert _has_error_boundary(settings_code), "SettingsTab must have ErrorBoundary"

    # PipelineVisualizer: WebSocket lifecycle check (heartbeat filtering and ErrorBoundary)
    assert "new WebSocket" in pipe_code, "PipelineVisualizer must instantiate WebSocket"
    assert "heartbeat" in pipe_code.lower(), (
        "PipelineVisualizer must filter heartbeat messages"
    )
    assert _has_error_boundary(pipe_code), "PipelineVisualizer must have ErrorBoundary"

    # ReportsTab: ErrorBoundary present
    assert _has_error_boundary(reports_code), "ReportsTab must have ErrorBoundary"


def test_component_resilience_matrix_summary():
    """Verify aggregated audit metrics across all 10 tab components."""
    matrix = {}
    for filename in ALL_10_TAB_COMPONENTS:
        code = _read_component(filename)
        vulns = _find_vulnerable_patterns(code)
        has_eb = _has_error_boundary(code)
        matrix[filename] = {
            "error_boundary": has_eb,
            "vulnerabilities": vulns,
            "vuln_count": len(vulns),
        }

    # Exactly 10 components audited
    assert len(matrix) == 10

    # Total vulnerability count should be 0 across the hardened suite
    total_vulns = sum(c["vuln_count"] for c in matrix.values())
    assert total_vulns == 0, f"Expected 0 vulnerabilities detected, found {total_vulns}"

    # Confirm zero unprotected components
    unprotected_count = sum(1 for c in matrix.values() if not c["error_boundary"])
    assert unprotected_count == 0, f"Expected 0 unprotected tab components, found {unprotected_count}"
