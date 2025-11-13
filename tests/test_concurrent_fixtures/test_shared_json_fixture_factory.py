"""Tests for make_shared_json using pytester."""

import pytest


def test_creates_shared_json(pytester, run_with_timeout):
    """Test that factory creates SharedJson instance."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        from pytest_xdist_rate_limit import SharedJson

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test")

        def test_factory_creates_instance(my_shared):
            assert isinstance(my_shared, SharedJson)

            # Can use it
            with my_shared.locked_dict() as data:
                data['test'] = 'value'

            assert my_shared.read() == {'test': 'value'}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_on_first_worker_dict(pytester, run_with_timeout):
    """Test that on_first_worker with dict initializes data."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            initial_data = {'initialized': True, 'count': 0}
            return make_shared_json(
                "test_init_dict",
                on_first_worker=initial_data
            )

        def test_init_with_dict(my_shared):
            assert my_shared.read() == {'initialized': True, 'count': 0}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_on_first_worker_callable(pytester, run_with_timeout):
    """Test that on_first_worker with callable initializes data."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            def init():
                return {'initialized': True, 'count': 0}

            return make_shared_json(
                "test_init_callable",
                on_first_worker=init
            )

        def test_init_with_callable(my_shared):
            assert my_shared.read() == {'initialized': True, 'count': 0}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_on_first_worker_callable_must_return_dict(pytester, run_with_timeout):
    """Test that on_first_worker callable must return a dict."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            def bad_init():
                return "not a dict"

            # This should raise TypeError
            return make_shared_json(
                "test_bad_init",
                on_first_worker=bad_init
            )

        def test_bad_init(my_shared):
            # Should not reach here due to fixture error
            pass
    """)

    result = run_with_timeout(pytester, "-v")
    # Should get an error during fixture setup
    outcomes = result.parseoutcomes()
    assert "errors" in outcomes and outcomes["errors"] == 1, str(result.stdout)
    result.stdout.fnmatch_lines(["*TypeError*must return a dict*"])


def test_on_last_worker_callback(pytester, run_with_timeout):
    """Test that on_last_worker callback is actually called."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)

    # Create a marker file path that will be accessible from both test and verification
    marker_file = pytester.path / "callback_marker.txt"

    pytester.makepyfile(f"""
        import pytest
        from pathlib import Path

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            marker_file = Path(r"{marker_file}")

            def finalize(shared):
                # Write marker file to prove callback was called
                data = shared.read()
                marker_file.write_text(f"callback_executed:count={{data.get('count', 0)}}")

            return make_shared_json(
                "test_final",
                on_first_worker={{'count': 0}},
                on_last_worker=finalize
            )

        def test_finalize_callback(my_shared):
            my_shared.update({{'count': 5}})
            # Verify data was set
            assert my_shared.read() == {{'count': 5}}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)

    # Verify the callback was actually called by checking for the marker file
    assert marker_file.exists(), (
        "on_last_worker callback was not called - marker file not found"
    )
    content = marker_file.read_text()
    assert "callback_executed" in content, f"Unexpected marker content: {content}"
    assert "count=5" in content, (
        f"Callback did not receive correct shared data: {content}"
    )


def test_custom_timeout(pytester, run_with_timeout):
    """Test that custom timeout is passed to SharedJson."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_timeout", timeout=10)

        def test_timeout(my_shared):
            assert my_shared.timeout == 10
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_default_timeout(pytester, run_with_timeout):
    """Test that default timeout is -1 (wait forever)."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_default_timeout")

        def test_default_timeout(my_shared):
            assert my_shared.timeout == -1
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_shared_location(pytester, run_with_timeout):
    """Test that files are created in shared location."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_location")

        def test_location(my_shared, tmp_path_factory):
            # Files should be in parent of worker-specific temp dirs
            expected_parent = tmp_path_factory.getbasetemp().parent
            assert my_shared.data_file.parent == expected_parent
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_factory_with_xdist_workers(pytester, run_with_timeout):
    """Test that factory works correctly with multiple xdist workers."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def shared_data(make_shared_json):
            return make_shared_json(
                "worker_data",
                on_first_worker={'workers': [], 'count': 0}
            )

        @weight(1)
        def test_worker_tracking(shared_data, request, worker_id):
            with shared_data.locked_dict() as data:
                # Track which workers have run
                if worker_id not in data['workers']:
                    data['workers'].append(worker_id)

                data['count'] += 1

                # Stop after 20 runs
                if data['count'] >= 20:
                    stop_load_testing(request, f"Completed 20 runs across {len(data['workers'])} workers")
    """)

    result = run_with_timeout(pytester, "--load-test", "-n", "2", "-v")
    result.stdout.fnmatch_lines(
        [
            "*Interrupted: Completed 20 runs across * workers*",
        ]
    )
    assert result.ret == pytest.ExitCode.INTERRUPTED


def test_factory_initialization_race_condition(pytester, run_with_timeout):
    """Test that factory handles concurrent initialization correctly."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def shared_init(make_shared_json):
            def initialize():
                # This should only run once despite multiple workers
                return {'initialized': True, 'init_count': 1}

            return make_shared_json(
                "init_test",
                on_first_worker=initialize
            )

        @weight(1)
        def test_single_init(shared_init, request):
            data = shared_init.read()

            # Should always see initialized=True
            assert data['initialized'] is True

            # init_count should remain 1 (not incremented by each worker)
            assert data['init_count'] == 1

            with shared_init.locked_dict() as d:
                d['test_runs'] = d.get('test_runs', 0) + 1

                if d['test_runs'] >= 10:
                    stop_load_testing(request, "Verified single initialization")
    """)

    result = run_with_timeout(pytester, "--load-test", "-n", "2", "-v")
    result.stdout.fnmatch_lines(
        [
            "*Interrupted: Verified single initialization*",
        ]
    )
    assert result.ret == pytest.ExitCode.INTERRUPTED


def test_timeout_on_locked_dict(pytester, run_with_timeout):
    """Test that timeout is respected when acquiring lock for locked_dict."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        import time
        from filelock import Timeout as FileLockTimeout

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_timeout_locked", timeout=0.1)

        def test_timeout_locked_dict(my_shared, tmp_path):
            # Manually acquire the lock to simulate contention
            from filelock import FileLock
            blocking_lock = FileLock(str(my_shared.lock_file), timeout=5)

            with blocking_lock:
                # Try to use locked_dict with a short timeout - should fail
                try:
                    with my_shared.locked_dict() as data:
                        data['should_not_reach'] = True
                    assert False, "Should have raised Timeout"
                except FileLockTimeout:
                    # Expected - timeout occurred
                    pass
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_on_read(pytester, run_with_timeout):
    """Test that timeout is respected when acquiring lock for read."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        from filelock import Timeout as FileLockTimeout

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_timeout_read", timeout=0.1)

        def test_timeout_read(my_shared):
            # Manually acquire the lock to simulate contention
            from filelock import FileLock
            blocking_lock = FileLock(str(my_shared.lock_file), timeout=5)

            with blocking_lock:
                # Try to read with a short timeout - should fail
                try:
                    data = my_shared.read()
                    assert False, "Should have raised Timeout"
                except FileLockTimeout:
                    # Expected - timeout occurred
                    pass
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_on_update(pytester, run_with_timeout):
    """Test that timeout is respected when acquiring lock for update."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        from filelock import Timeout as FileLockTimeout

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_timeout_update", timeout=0.1)

        def test_timeout_update(my_shared):
            # Manually acquire the lock to simulate contention
            from filelock import FileLock
            blocking_lock = FileLock(str(my_shared.lock_file), timeout=5)

            with blocking_lock:
                # Try to update with a short timeout - should fail
                try:
                    my_shared.update({'should_not_reach': True})
                    assert False, "Should have raised Timeout"
                except FileLockTimeout:
                    # Expected - timeout occurred
                    pass
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_infinite_timeout_waits(pytester, run_with_timeout):
    """Test that timeout=-1 waits indefinitely for lock."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        import threading
        import time

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_infinite_timeout", timeout=-1)

        def test_infinite_timeout(my_shared):
            # Acquire lock in background thread and release after delay
            from filelock import FileLock
            blocking_lock = FileLock(str(my_shared.lock_file), timeout=5)

            def hold_lock():
                with blocking_lock:
                    time.sleep(0.5)

            thread = threading.Thread(target=hold_lock)
            thread.start()

            # Give thread time to acquire lock
            time.sleep(0.1)

            # This should wait and eventually succeed (not timeout)
            start = time.time()
            with my_shared.locked_dict() as data:
                data['success'] = True
            elapsed = time.time() - start

            thread.join()

            # Should have waited for the lock (with small tolerance for timing precision)
            assert elapsed >= 0.38, f"Should have waited, but only took {elapsed}s"
            assert my_shared.read() == {'success': True}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_zero_timeout_fails_immediately(pytester, run_with_timeout):
    """Test that timeout=0 fails immediately if lock is held."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest
        import time
        from filelock import Timeout as FileLockTimeout

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("test_zero_timeout", timeout=0)

        def test_zero_timeout(my_shared):
            # Manually acquire the lock
            from filelock import FileLock
            blocking_lock = FileLock(str(my_shared.lock_file), timeout=5)

            with blocking_lock:
                # Should fail immediately with timeout=0
                start = time.time()
                try:
                    with my_shared.locked_dict() as data:
                        data['should_not_reach'] = True
                    assert False, "Should have raised Timeout"
                except FileLockTimeout:
                    elapsed = time.time() - start
                    # Should fail very quickly (within 0.1s)
                    assert elapsed < 0.1, f"Should fail immediately, took {elapsed}s"
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_with_multiple_operations(pytester, run_with_timeout):
    """Test that timeout applies to each operation independently."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json(
                "test_multi_timeout",
                on_first_worker={'count': 0},
                timeout=5
            )

        def test_multiple_operations(my_shared):
            # Each operation should respect the timeout
            assert my_shared.timeout == 5

            # First operation
            with my_shared.locked_dict() as data:
                data['count'] += 1

            # Second operation
            current = my_shared.read()
            assert current['count'] == 1

            # Third operation
            my_shared.update({'count': 2})

            # Verify
            assert my_shared.read()['count'] == 2
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)
