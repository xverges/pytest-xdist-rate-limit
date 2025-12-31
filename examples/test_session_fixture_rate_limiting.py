"""
Example: Pacing session-scoped fixture creation across workers

This demonstrates how to pace the creation of session-scoped fixtures
across multiple pytest-xdist workers. Each worker creates the fixture once,
and the pacer ensures they don't all create it simultaneously.

Run with:
  pytest examples/test_session_fixture_rate_limiting.py -n 4 -v --capture=no -p no:terminalprogress

Key concepts:
1. Session fixtures are created once per worker
2. Pacer coordinates fixture creation across workers
3. Tests wait for all workers to complete fixture creation before verifying
4. Tracker fixture provides visibility into the pacing behavior
5. on_last_worker callback generates a final report when all workers complete

TEST_CODE:
```python
result = run_with_timeout(pytester, '-n', '2', '-v', timeout=60)
result.stdout.fnmatch_lines([
    '*PASSED*test_worker*',
    '*PASSED*test_verify_rate_limiting*',
])
assert result.ret == pytest.ExitCode.OK
```
"""

import logging
import os
import sys
import time
from datetime import datetime

import pytest

from pytest_xdist_rate_limit import Rate

logger = logging.getLogger(__name__)


def log_output(message):
    """Write to stderr to bypass pytest capture in xdist workers."""
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


@pytest.fixture(scope="session")
def fixture_tracker(make_shared_json):
    """Shared tracker for monitoring fixture creation across workers.

    Uses on_last_worker callback to print a final report when all workers complete.
    """
    def print_report(shared_json):
        """Print final report of fixture creation across all workers."""
        data = shared_json.read()
        workers = data.get("workers", {})

        if not workers:
            logger.warning("No workers recorded in tracker")
            return

        # Sort workers by entry time (when they entered the rate limiter)
        sorted_workers = sorted(workers.items(), key=lambda x: x[1]["entry_time"])

        # Build report
        report_lines = [
            "",
            "=" * 70,
            "SESSION FIXTURE PACING REPORT",
            "=" * 70,
            f"Total workers: {len(workers)}",
            "Target rate: 15 calls/minute (1 every 4 seconds)",
            "Burst capacity: 1",
        ]

        for i, (wid, info) in enumerate(sorted_workers):
            report_lines.append(f"\nWorker {i+1} ({wid}):")
            report_lines.append(f"  • Waited: {info['waited']:.2f} seconds")
            report_lines.append(f"  • Call count: {info['call_count']}")
            entry_time = datetime.fromtimestamp(info['entry_time']).strftime('%H:%M:%S')
            exit_time = datetime.fromtimestamp(info['exit_time']).strftime('%H:%M:%S')
            report_lines.append(f"  • Entry time: {entry_time}")
            report_lines.append(f"  • Exit time: {exit_time}")

        # Calculate statistics
        total_wait = sum(w["waited"] for _, w in sorted_workers)
        report_lines.append(f"\n{'=' * 70}")
        report_lines.append(f"Total wait time across all workers: {total_wait:.2f}s")

        if len(workers) >= 2:
            first_entry = min(w["entry_time"] for _, w in sorted_workers)
            last_exit = max(w["exit_time"] for _, w in sorted_workers)
            total_duration = last_exit - first_entry
            report_lines.append(f"Time from first entry to last exit: {total_duration:.2f}s")

            if total_wait > 2:
                report_lines.append("✓ Call pacing verified successfully!")
            else:
                report_lines.append("⚠ Warning: Expected more wait time for call pacing")

        report_lines.append("=" * 70)


        log_output("\n" + "\n".join(report_lines))

    return make_shared_json(
        name="session_fixture_tracker",
        on_last_worker=print_report
    )


@pytest.fixture(scope="session")
def session_throttler(make_pacer):
    """Pacer for session fixture creation."""
    return make_pacer(
        name="session_fixture_throttler",
        hourly_rate=Rate.per_minute(15),  # 15 calls per minute = 1 every 4 seconds
        max_drift=0.3,
        burst_capacity=1,
    )


@pytest.fixture(scope="session")
def throttled_session_fixture(session_throttler, fixture_tracker, worker_id):
    """Session fixture that is paced during creation."""
    entry_time = time.time()

    with session_throttler() as ctx:
        exit_time = time.time()

        # Record this worker's timing information
        with fixture_tracker.locked_dict() as data:
            if "workers" not in data:
                data["workers"] = {}
                data["total_workers"] = 0

            data["workers"][worker_id] = {
                "entry_time": entry_time,
                "exit_time": exit_time,
                "waited": ctx.seconds_waited,
                "call_count": ctx.call_count,
            }
            data["total_workers"] = len(data["workers"])

        # Log fixture creation - write to stderr to bypass capture
        log_output(
            f"[FIXTURE] Worker {worker_id} created session fixture "
            f"(waited: {ctx.seconds_waited:.2f}s, call_count: {ctx.call_count})"
        )

        # Simulate some initialization work
        time.sleep(0.1)

        return {
            "worker_id": worker_id,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "waited": ctx.seconds_waited,
            "call_count": ctx.call_count,
        }


def wait_for_all_workers(tracker, expected_workers, timeout=30):
    """Wait for all workers to complete fixture creation."""
    start = time.time()
    while time.time() - start < timeout:
        data = tracker.read()
        if data.get("total_workers", 0) >= expected_workers:
            return True
        time.sleep(0.1)
    return False


# Generate one test per expected worker
@pytest.mark.parametrize("worker_num", range(int(os.getenv("PYTEST_XDIST_WORKER_COUNT", 2))))
def test_worker(worker_num, throttled_session_fixture, fixture_tracker):
    """Test that uses the throttled session fixture.

    Each worker gets assigned one of these tests, ensuring all workers
    create the session fixture.
    """
    # Wait for all workers to complete fixture creation
    assert wait_for_all_workers(fixture_tracker, expected_workers=2, timeout=30), \
        "Timeout waiting for all workers to create fixtures"

    # Verify this worker's fixture was created
    assert throttled_session_fixture is not None
    assert throttled_session_fixture["waited"] >= 0



def test_verify_rate_limiting(throttled_session_fixture, fixture_tracker):
    """Verify that fixture creation was actually paced across workers."""
    # Wait for all workers to complete
    assert wait_for_all_workers(fixture_tracker, expected_workers=2, timeout=30), \
        "Timeout waiting for all workers"

    data = fixture_tracker.read()
    workers = data.get("workers", {})

    # Should have 2 workers (gw0 and gw1)
    assert len(workers) >= 1, f"Expected at least 1 worker, got {len(workers)}"


    # Verify pacing worked
    total_wait = sum(w["waited"] for w in workers.values())
    # With rate of 15/minute (4s between calls) and burst_capacity=1,
    # at least one worker should have waited significantly
    assert total_wait > 2, (
            f"Expected significant wait time (>2s) across workers, "
            f"got {total_wait:.2f}s total"
    )

    log_output("✓ Call pacing verified successfully!")
