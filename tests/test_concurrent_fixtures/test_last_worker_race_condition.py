"""Test for race condition in last worker detection."""

import pytest


def test_last_worker_callback_runs_exactly_once(pytester, run_with_timeout):
    """Test that on_last_worker callback runs exactly once, not multiple times.

    This test exposes the race condition where multiple workers could
    simultaneously determine they are the "last" worker due to the >= check
    instead of == check, combined with the read-modify-write race.
    """
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)

    # Create a counter file that will track callback executions
    counter_file = pytester.path / "callback_counter.txt"

    pytester.makepyfile(f"""
        import pytest
        from pathlib import Path
        import time
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def shared_counter(make_shared_json):
            counter_file = Path(r"{counter_file}")

            def on_last_worker_callback(shared):
                # This callback should run EXACTLY ONCE
                # Use the shared JSON itself to track callback executions thread-safely
                with shared.locked_dict() as data:
                    data['callback_count'] = data.get('callback_count', 0) + 1
                    callback_count = data['callback_count']

                # Write to marker file for test verification
                # (safe because only one worker should call this)
                counter_file.write_text(str(callback_count))

                # Add a small delay to increase chance of race condition
                time.sleep(0.1)

            return make_shared_json(
                "race_test",
                on_first_worker={{'test_count': 0, 'callback_count': 0}},
                on_last_worker=on_last_worker_callback
            )

        @weight(1)
        def test_concurrent_execution(shared_counter, request):
            # Run multiple tests to ensure all workers participate
            with shared_counter.locked_dict() as data:
                data['test_count'] = data.get('test_count', 0) + 1

                # Stop after enough iterations to ensure all workers have run
                if data['test_count'] >= 50:
                    stop_load_testing(request, "Completed test runs")
    """)

    # Run with multiple workers to trigger race condition
    result = run_with_timeout(pytester, "--load-test", "-n", "4", "-v")

    # Test should complete
    assert result.ret == pytest.ExitCode.INTERRUPTED, f"stderr: {result.stderr}"

    # The critical assertion: callback should have run exactly once
    assert counter_file.exists(), "Callback was never executed"
    callback_count = int(counter_file.read_text().strip())

    # This will FAIL with current implementation due to race condition
    # Multiple workers will think they're "last" and execute the callback
    assert callback_count == 1, (
        f"on_last_worker callback executed {callback_count} times, "
        f"expected exactly 1. This indicates a race condition where "
        f"multiple workers determined they were the 'last' worker."
    )


def test_last_worker_detection_with_delayed_workers(pytester, run_with_timeout):
    """Test last worker detection when workers finish at different times.

    This test creates a scenario where workers finish their teardown
    at staggered intervals, increasing the likelihood of exposing
    the race condition.
    """
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)

    execution_log = pytester.path / "execution_log.txt"

    pytester.makepyfile(f"""
        import pytest
        from pathlib import Path
        import time
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def delayed_fixture(make_shared_json, worker_id):
            log_file = Path(r"{execution_log}")

            def log_callback(shared):
                # Log each callback execution with timestamp
                timestamp = time.time()
                log_entry = f"{{worker_id}}:{{timestamp}}\\n"

                if log_file.exists():
                    content = log_file.read_text()
                    log_file.write_text(content + log_entry)
                else:
                    log_file.write_text(log_entry)

            return make_shared_json(
                "delayed_test",
                on_first_worker={{'runs': 0}},
                on_last_worker=log_callback
            )

        @weight(1)
        def test_with_delays(delayed_fixture, request, worker_id):
            # Add variable delays based on worker_id to stagger teardowns
            worker_num = int(worker_id.replace('gw', '')) if 'gw' in worker_id else 0
            time.sleep(0.01 * worker_num)

            with delayed_fixture.locked_dict() as data:
                data['runs'] = data.get('runs', 0) + 1

                if data['runs'] >= 30:
                    stop_load_testing(request, "Test complete")
    """)

    result = run_with_timeout(pytester, "--load-test", "-n", "3", "-v")
    assert result.ret == pytest.ExitCode.INTERRUPTED

    # Check how many times the callback was executed
    assert execution_log.exists(), "Callback log not found"
    log_lines = [
        line for line in execution_log.read_text().strip().split("\\n") if line
    ]

    # Should be exactly 1 callback execution
    assert len(log_lines) == 1, (
        f"Expected 1 callback execution, got {len(log_lines)}. "
        f"Log entries: {log_lines}. This indicates the race condition "
        "where multiple workers executed the on_last_worker callback."
    )


def test_race_condition_with_exact_worker_count(pytester, run_with_timeout):
    """Test that verifies the >= vs == issue in last worker detection.

    The current code uses >= which allows multiple workers to pass
    the is_last check when there's a race condition in the
    read-modify-write sequence.
    """
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)

    callback_marker = pytester.path / "callback_executions.txt"

    pytester.makepyfile(f"""
        import pytest
        from pathlib import Path
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def exact_count_fixture(make_shared_json):
            marker = Path(r"{callback_marker}")

            def count_callback(shared):
                # Use the shared JSON itself to track callback executions
                # This is thread-safe across workers
                with shared.locked_dict() as data:
                    data['callback_count'] = data.get('callback_count', 0) + 1

                # Also write to marker file for test verification
                # (this write is safe because only one worker should call this)
                marker.write_text(str(data['callback_count']))

            return make_shared_json(
                "exact_count",
                on_first_worker={{'counter': 0, 'callback_count': 0}},
                on_last_worker=count_callback
            )

        @weight(1)
        def test_exact_count(exact_count_fixture, request):
            with exact_count_fixture.locked_dict() as data:
                data['counter'] += 1

                if data['counter'] >= 40:
                    stop_load_testing(request, "Done")
    """)

    # Use exactly 3 workers
    result = run_with_timeout(pytester, "--load-test", "-n", "3", "-v")
    assert result.ret == pytest.ExitCode.INTERRUPTED

    # Verify callback ran exactly once
    assert callback_marker.exists()
    execution_count = int(callback_marker.read_text())

    assert execution_count == 1, (
        f"Callback executed {execution_count} times instead of 1. "
        "The race condition allowed multiple workers to pass the "
        "'is_last' check (len(finished_workers) >= total_workers)."
    )
