#!/usr/bin/env python3
"""Audit Verification Test Suite Runner for QuantOS.

Executes all audit test tiers using pytest, outputs structured results to
tests/audit/audit_results.json, and synchronizes a duplicate copy to
/Users/mac/Downloads/Antigravity_Exports/.
"""

import json
import os
import shutil
import sys
import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUDIT_DIR = os.path.join(REPO_ROOT, "tests", "audit")
RESULTS_PATH = os.path.join(AUDIT_DIR, "audit_results.json")
EXPORTS_DIR = "/Users/mac/Downloads/Antigravity_Exports"
EXPORT_RESULTS_PATH = os.path.join(EXPORTS_DIR, "audit_results.json")


def main():
    print("=" * 80)
    print("QuantOS Full-Stack Codebase Audit: Verification Test Suite Runner")
    print(f"Target Directory: {AUDIT_DIR}")
    print("=" * 80)

    # Clean any stale pytest audit items in memory
    if hasattr(pytest, "_audit_items"):
        pytest._audit_items = []

    # Run pytest
    args = [
        AUDIT_DIR,
        "-v",
        "--tb=short",
    ]
    exit_code = pytest.main(args)

    print("\n" + "=" * 80)
    print("Audit Verification Suite Execution Completed")
    print("=" * 80)

    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        summary = data.get("summary", {})
        tiers = data.get("tiers", {})

        print(f"Total Tests Executed : {summary.get('total_tests', 0)}")
        print(f"Passed               : {summary.get('passed', 0)}")
        print(f"Failed               : {summary.get('failed', 0)}")
        print(f"Execution Duration   : {summary.get('execution_time_seconds', 0.0)}s")
        print("-" * 80)

        for tier_key, tier_data in tiers.items():
            name = tier_data.get("name", tier_key)
            status = tier_data.get("status", "UNKNOWN")
            passed = tier_data.get("tests_passed", 0)
            print(f"[{status}] {name}: {passed} tests verified")

        print("=" * 80)

        # Synchronize to Antigravity_Exports
        if os.path.exists(EXPORTS_DIR):
            shutil.copy2(RESULTS_PATH, EXPORT_RESULTS_PATH)
            print(f"✓ Copied results artifact to: {EXPORT_RESULTS_PATH}")
    else:
        print(f"WARNING: Results artifact not found at {RESULTS_PATH}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
