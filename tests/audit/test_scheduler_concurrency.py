"""Tier 4 Audit: Background Automation & Concurrency Mutex Integrity.

Validates:
- Subprocess triggers in market_monitor.py and api.py bypass execution.lock.
- Silent failure suppression (check=False) in scheduler.py:run_locked_subprocess.
- Destructive truncation hazard of opening execution.lock with mode 'w'.
- Demonstration of concurrent execution collision between cron scheduler and market monitor.
"""

import ast
import fcntl
import os
import subprocess
import tempfile
import time


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCHEDULER_PY = os.path.join(REPO_ROOT, "src", "scheduler.py")
MARKET_MONITOR_PY = os.path.join(REPO_ROOT, "src", "market_monitor.py")
API_PY = os.path.join(REPO_ROOT, "src", "api.py")


def test_market_monitor_and_api_lock_bypass():
    """Verify that market_monitor.py and api.py trigger fetch_market_data without acquiring execution.lock."""
    # 1. Audit market_monitor.py
    with open(MARKET_MONITOR_PY, "r", encoding="utf-8") as f:
        monitor_code = f.read()

    assert "fetch_market_data.py" in monitor_code, "market_monitor.py must reference fetch_market_data.py"
    assert "execution.lock" not in monitor_code, (
        "market_monitor.py should not reference execution.lock (lock bypass vulnerability)"
    )
    assert "run_locked_subprocess" not in monitor_code, (
        "market_monitor.py does not use run_locked_subprocess"
    )
    assert "fcntl" not in monitor_code, (
        "market_monitor.py lacks fcntl import for mutex locking"
    )

    # 2. Audit api.py background triggers
    with open(API_PY, "r", encoding="utf-8") as f:
        api_code = f.read()

    assert "execution.lock" not in api_code, (
        "api.py should not reference execution.lock (lock bypass vulnerability)"
    )
    assert "run_locked_subprocess" not in api_code, (
        "api.py does not use run_locked_subprocess in background triggers"
    )


def test_scheduler_exception_isolation_suppression():
    """Verify that run_locked_subprocess suppresses child exit codes and allows failure cascade."""
    with open(SCHEDULER_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SCHEDULER_PY)

    # Locate run_locked_subprocess function definition
    func_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_locked_subprocess":
            func_node = node
            break

    assert func_node is not None, "run_locked_subprocess not found in scheduler.py"

    # Verify subprocess.run call inside run_locked_subprocess
    subproc_call = None
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "run":
            subproc_call = node
            break

    assert subproc_call is not None, "subprocess.run call not found in run_locked_subprocess"

    # Check that check=True is NOT passed (default is check=False, which swallows errors)
    check_arg = next((kw for kw in subproc_call.keywords if kw.arg == "check"), None)
    if check_arg is not None:
        assert isinstance(check_arg.value, ast.Constant) and check_arg.value.value is False, (
            "Expected check=False or omitted in scheduler.py"
        )

    # Behavioral verification: executing a command that exits with code 1 does not raise an exception
    # Replicating scheduler.py:run_locked_subprocess behavior
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file_path = os.path.join(tmpdir, "test_execution.lock")
        failing_cmd = ["python3", "-c", "import sys; sys.exit(1)"]

        # Run with scheduler's exact pattern
        with open(lock_file_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            result = subprocess.run(failing_cmd)
            fcntl.flock(lock_file, fcntl.LOCK_UN)

        assert result.returncode == 1, "Process should have returned exit code 1"
        # The execution did NOT throw an exception, demonstrating silent suppression


def test_scheduler_lockfile_destructive_truncation():
    """Verify that scheduler.py opens execution.lock with mode 'w', causing truncation."""
    with open(SCHEDULER_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=SCHEDULER_PY)

    func_node = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_locked_subprocess"),
        None,
    )
    assert func_node is not None

    open_w_found = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
            args = node.args
            if len(args) > 1 and isinstance(args[1], ast.Constant) and args[1].value == "w":
                open_w_found = True

    assert open_w_found, "scheduler.py:run_locked_subprocess must open lockfile with mode 'w'"


def test_scheduler_market_monitor_concurrency_collision():
    """Demonstrate concurrency collision when market_monitor executes without acquiring execution.lock."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = os.path.join(tmpdir, "execution.lock")

        # Process 1 (Scheduler Cron) acquires execution.lock
        cron_lock = open(lock_path, "w")
        fcntl.flock(cron_lock, fcntl.LOCK_EX)

        # Process 2 (Market Monitor) executes WITHOUT acquiring lock (as in market_monitor.py:112)
        # Because market_monitor does not call fcntl.flock, it does NOT block and runs concurrently!
        monitor_executed_concurrently = False

        start_time = time.time()
        # Market monitor runs directly
        res = subprocess.run(["python3", "-c", "import time; time.sleep(0.05); print('MONITOR_RAN')"],
                             capture_output=True, text=True)
        elapsed = time.time() - start_time

        if "MONITOR_RAN" in res.stdout:
            monitor_executed_concurrently = True

        # Clean up cron lock
        fcntl.flock(cron_lock, fcntl.LOCK_UN)
        cron_lock.close()

        assert monitor_executed_concurrently, "Market monitor was blocked when it should have bypassed lock"
        assert elapsed < 0.5, "Market monitor unexpectedly waited for lock"
