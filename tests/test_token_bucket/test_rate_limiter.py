"""Tests for TokenBucketRateLimiter."""

# Conftest content to inject into pytester tests
CONFTEST_CONTENT = """
import pytest
from pytest_xdist_rate_limit import shared_json_fixture_factory

pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
"""


def test_basic_rate_limiting(pytester, run_with_timeout):
    """Test basic rate limiting functionality."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_rate_limiter(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="rate_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(1),
                burst_capacity=2
            )

            # First two calls should be immediate (burst capacity)
            start = time.time()
            with limiter.rate_limited_context() as ctx:
                assert ctx.call_count == 1
            with limiter.rate_limited_context() as ctx:
                assert ctx.call_count == 2
            elapsed = time.time() - start
            assert elapsed < 0.1, f"Burst should be immediate, took {elapsed}s"

            # Third call should wait
            start = time.time()
            with limiter.rate_limited_context() as ctx:
                assert ctx.call_count == 3
            elapsed = time.time() - start
            assert elapsed >= 0.9, f"Should wait ~1s, took {elapsed}s"
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_hourly_rate_function(pytester, run_with_timeout):
    """Test rate limiter with dynamic hourly rate."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_dynamic_rate(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="dynamic_rate")

            rate_value = [RateLimit.per_second(1)]  # Start at 1/sec

            def get_rate():
                return rate_value[0]

            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=get_rate,
                burst_capacity=1
            )

            # First call uses initial rate
            with limiter.rate_limited_context():
                pass

            # Change rate
            rate_value[0] = RateLimit.per_second(2)  # 2/sec

            # Verify new rate is used
            assert limiter.hourly_rate == 7200
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_exception_tracking(pytester, run_with_timeout):
    """Test that exceptions are tracked."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_exception_tracking(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="exception_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(1),
                burst_capacity=10
            )

            # Successful call
            with limiter.rate_limited_context() as ctx:
                assert ctx.exceptions == 0

            # Failed call
            try:
                with limiter.rate_limited_context() as ctx:
                    raise ValueError("Test error")
            except ValueError:
                pass

            # Check exception was tracked
            with limiter.rate_limited_context() as ctx:
                assert ctx.exceptions == 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_max_calls_limit(pytester, run_with_timeout):
    """Test max_calls limit and callback."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_max_calls(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="max_calls_test")

            callback_data = []

            def on_max_calls(limiter_id, count):
                callback_data.append((limiter_id, count))

            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(10),  # High rate to avoid waiting
                burst_capacity=10,
                max_calls=3,
                max_call_callback=on_max_calls
            )

            # Make 3 calls
            for _ in range(3):
                with limiter.rate_limited_context():
                    pass

            # Callback should have been triggered
            assert len(callback_data) == 1
            assert callback_data[0] == ("max_calls_test", 3)
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_rate_drift_detection(pytester, run_with_timeout):
    """Test rate drift detection and callback."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_drift_callback(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="drift_test")

            drift_data = []

            def on_drift(limiter_id, current_rate, target_rate, drift):
                drift_data.append({
                    'id': limiter_id,
                    'current': current_rate,
                    'target': target_rate,
                    'drift': drift
                })

            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_hour(100),  # Very low rate for testing
                burst_capacity=100,
                max_drift=0.5,  # 50% tolerance
                num_calls_between_checks=5,  # Check every 5 calls
                on_drift_callback=on_drift
            )

            # Manually set start_time to 61 seconds ago to trigger rate check
            import time
            with shared.locked_dict() as data:
                data['start_time'] = time.time() - 61
                data['last_refill_time'] = time.time()
                data['tokens'] = 100
                data['call_count'] = 0
                data['exceptions'] = 0

            # Make calls rapidly to exceed rate
            for i in range(10):
                with limiter.rate_limited_context():
                    pass

            # Drift callback should have been triggered at call 5 and 10
            assert len(drift_data) >= 1, f"Expected drift callback, got {len(drift_data)} calls"
            assert drift_data[0]['id'] == 'drift_test'
            assert drift_data[0]['drift'] > 0.5
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v", "-s")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_context_properties(pytester, run_with_timeout):
    """Test RateLimitContext properties."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_context_props(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="context_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(2),
                burst_capacity=5
            )

            with limiter.rate_limited_context() as ctx:
                assert ctx.id == "context_test"
                assert ctx.hourly_rate == 7200
                assert ctx.call_count == 1
                assert ctx.exceptions == 0

            with limiter.rate_limited_context() as ctx:
                assert ctx.call_count == 2

        def test_start_time(shared_json_fixture_factory):
            \"\"\"Test that start_time property returns the timestamp of the first call.\"\"\"
            shared = shared_json_fixture_factory(name="start_time_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(10),
                burst_capacity=5
            )

            # Record time before first call
            before_first_call = time.time()

            # Make first call
            with limiter.rate_limited_context() as ctx:
                start_time = ctx.start_time
                assert ctx.call_count == 1

            # Record time after first call
            after_first_call = time.time()

            # Verify start_time is within expected range
            assert before_first_call <= start_time <= after_first_call, (
                f"start_time {start_time} should be between "
                f"{before_first_call} and {after_first_call}"
            )

            # Make second call and verify start_time hasn't changed
            time.sleep(0.1)
            with limiter.rate_limited_context() as ctx:
                assert ctx.start_time == start_time, (
                    "start_time should remain constant across calls"
                )
                assert ctx.call_count == 2
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_concurrent_workers(pytester, run_with_timeout):
    """Test rate limiter across multiple xdist workers."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        @pytest.fixture(scope="session")
        def rate_limiter(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="concurrent_test")
            return TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(1),
                burst_capacity=2
            )

        def test_worker_1(rate_limiter):
            with rate_limiter.rate_limited_context() as ctx:
                assert ctx.call_count >= 1

        def test_worker_2(rate_limiter):
            with rate_limiter.rate_limited_context() as ctx:
                assert ctx.call_count >= 1

        def test_worker_3(rate_limiter):
            with rate_limiter.rate_limited_context() as ctx:
                assert ctx.call_count >= 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 3, str(result.stdout)


def test_burst_capacity_default(pytester, run_with_timeout):
    """Test default burst capacity calculation."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_default_burst(shared_json_fixture_factory):
            shared = shared_json_fixture_factory(name="burst_default")

            # For rate of 1000/hr, default burst should be 100 (10%)
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_hour(1000)
            )

            # Trigger initialization
            with limiter.rate_limited_context():
                pass

            assert limiter.burst_capacity == 100

            # For very low rates, minimum should be 1
            shared2 = shared_json_fixture_factory(name="burst_min")
            limiter2 = TokenBucketRateLimiter(
                shared_state=shared2,
                hourly_rate=RateLimit.per_hour(5)
            )

            with limiter2.rate_limited_context():
                pass

            assert limiter2.burst_capacity == 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)
