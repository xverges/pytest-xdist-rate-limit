"""Tests for SharedJson class using pytester."""

import pytest


def test_locked_dict_creates_file(pytester, run_with_timeout):
    """Test that locked_dict creates the JSON file."""
    pytester.makepyfile("""
        import json
        from pathlib import Path
        from pytest_xdist_rate_limit import SharedJson

        def test_creates_file(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            with shared.locked_dict() as data:
                data["count"] = 42

            assert data_file.exists()
            with open(data_file) as f:
                content = json.load(f)
            assert content == {"count": 42}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_locked_dict_reads_existing_file(pytester, run_with_timeout):
    """Test that locked_dict reads existing data."""
    pytester.makepyfile("""
        import json
        from pytest_xdist_rate_limit import SharedJson

        def test_reads_existing(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            # Create initial data
            data_file.write_text('{"count": 10}')

            shared = SharedJson(data_file, lock_file)

            with shared.locked_dict() as data:
                assert data["count"] == 10
                data["count"] += 5

            with open(data_file) as f:
                content = json.load(f)
            assert content == {"count": 15}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_locked_dict_handles_empty_file(pytester, run_with_timeout):
    """Test that locked_dict handles non-existent file."""
    pytester.makepyfile("""
        import json
        from pytest_xdist_rate_limit import SharedJson

        def test_handles_empty(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            with shared.locked_dict() as data:
                assert data == {}
                data["new_key"] = "value"

            with open(data_file) as f:
                content = json.load(f)
            assert content == {"new_key": "value"}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_locked_dict_supports_dict_operations(pytester, run_with_timeout):
    """Test that locked_dict supports standard dict operations."""
    pytester.makepyfile("""
        import json
        from pytest_xdist_rate_limit import SharedJson

        def test_dict_operations(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            with shared.locked_dict() as data:
                # setdefault
                data.setdefault("count", 0)
                data["count"] += 1

                # list operations
                data.setdefault("items", []).append("item1")
                data["items"].append("item2")

                # nested dicts
                data.setdefault("metadata", {})["version"] = "1.0"

            with open(data_file) as f:
                content = json.load(f)

            assert content == {
                "count": 1,
                "items": ["item1", "item2"],
                "metadata": {"version": "1.0"}
            }
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_read_returns_copy(pytester, run_with_timeout):
    """Test that read() returns a snapshot."""
    pytester.makepyfile("""
        from pytest_xdist_rate_limit import SharedJson

        def test_read_snapshot(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            data_file.write_text('{"count": 10}')

            shared = SharedJson(data_file, lock_file)

            data = shared.read()
            assert data == {"count": 10}

            # Modifying returned dict doesn't affect file
            data["count"] = 999

            data2 = shared.read()
            assert data2 == {"count": 10}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_read_empty_file(pytester, run_with_timeout):
    """Test that read() returns empty dict for non-existent file."""
    pytester.makepyfile("""
        from pytest_xdist_rate_limit import SharedJson

        def test_read_empty(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            data = shared.read()
            assert data == {}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_update_merges_data(pytester, run_with_timeout):
    """Test that update() merges new data."""
    pytester.makepyfile("""
        from pytest_xdist_rate_limit import SharedJson

        def test_update_merge(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            with shared.locked_dict() as data:
                data["a"] = 1
                data["b"] = 2

            shared.update({"b": 20, "c": 30})

            data = shared.read()
            assert data == {"a": 1, "b": 20, "c": 30}
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_json_serialization_types(pytester, run_with_timeout):
    """Test that only JSON-serializable types work."""
    pytester.makepyfile("""
        from pytest_xdist_rate_limit import SharedJson

        def test_json_types(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            shared = SharedJson(data_file, lock_file)

            # Valid JSON types
            with shared.locked_dict() as data:
                data["string"] = "text"
                data["int"] = 42
                data["float"] = 3.14
                data["bool"] = True
                data["null"] = None
                data["list"] = [1, 2, 3]
                data["dict"] = {"nested": "value"}

            result = shared.read()
            assert result == {
                "string": "text",
                "int": 42,
                "float": 3.14,
                "bool": True,
                "null": None,
                "list": [1, 2, 3],
                "dict": {"nested": "value"}
            }
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_parameter(pytester, run_with_timeout):
    """Test that timeout parameter is respected."""
    pytester.makepyfile("""
        from pytest_xdist_rate_limit import SharedJson

        def test_timeout(tmp_path):
            data_file = tmp_path / "test.json"
            lock_file = tmp_path / "test.lock"

            # Create with custom timeout
            shared = SharedJson(data_file, lock_file, timeout=5)
            assert shared.timeout == 5

            # Default timeout is -1 (wait forever)
            shared_default = SharedJson(data_file, lock_file)
            assert shared_default.timeout == -1
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_name_property_strips_prefix(pytester, run_with_timeout):
    """Test that name property returns clean name without pytest_shared_ prefix."""
    pytester.makeconftest("""
        pytest_plugins = ['pytest_xdist_rate_limit.shared_json']
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(scope="session")
        def my_shared(make_shared_json):
            return make_shared_json("my_fixture")

        def test_name_property(my_shared):
            # Name should be clean without pytest_shared_ prefix
            assert my_shared.name == "my_fixture"

            # But the actual file should have the prefix
            assert "pytest_shared_my_fixture" in str(my_shared.data_file)
    """)

    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_concurrent_access_with_xdist(pytester, run_with_timeout):
    """Test that SharedJson works correctly with concurrent xdist workers."""
    pytester.makepyfile("""
        import pytest
        from pytest_xdist_rate_limit import SharedJson
        from pytest_load_testing import weight, stop_load_testing

        @pytest.fixture(scope="session")
        def shared_counter(tmp_path_factory):
            base = tmp_path_factory.getbasetemp().parent
            data_file = base / "counter.json"
            lock_file = base / "counter.lock"
            return SharedJson(data_file, lock_file)

        @weight(1)
        def test_increment_counter(shared_counter, request):
            import os
            worker_id = os.environ.get('PYTEST_XDIST_WORKER', "master")

            with shared_counter.locked_dict() as data:
                count = data.get("count", 0)
                data["count"] = count + 1

                # Track which workers have run
                workers = data.get("workers", [])
                if worker_id not in workers:
                    workers.append(worker_id)
                    data["workers"] = workers

                # Stop after 10 increments
                if data["count"] >= 10:
                    stop_load_testing(request, "Counter reached 10")
    """)

    result = run_with_timeout(pytester, "--load-test", "-n", "2", "-v")
    result.stdout.fnmatch_lines(
        [
            "*Interrupted: Counter reached 10*",
        ]
    )
    assert result.ret == pytest.ExitCode.INTERRUPTED

    output = result.stdout.str()
    assert "[gw0]" in output, "Worker gw0 should have run tests"
    assert "[gw1]" in output, "Worker gw1 should have run tests"

    # Count how many times each worker appears
    gw0_count = output.count("[gw0]")
    gw1_count = output.count("[gw1]")

    assert gw0_count > 0, (
        f"Worker gw0 should have run at least one test, ran {gw0_count}"
    )
    assert gw1_count > 0, (
        f"Worker gw1 should have run at least one test, ran {gw1_count}"
    )

    # Both workers should have participated
    total_tests = gw0_count + gw1_count
    assert total_tests >= 10, f"Expected at least 10 test runs, got {total_tests}"
