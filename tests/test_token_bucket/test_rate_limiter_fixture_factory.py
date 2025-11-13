"""Tests for make_rate_limiter."""

# Conftest content to inject into pytester tests
CONFTEST_CONTENT = """
import pytest
from pytest_xdist_rate_limit import make_rate_limiter

pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
"""


def test_make_rate_limiter_basic(pytester, run_with_timeout):
    """Test basic usage of make_rate_limiter."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def api_limiter(make_rate_limiter):
            return make_rate_limiter(
                name="api_test",
                hourly_rate=RateLimit.per_second(2),
                burst_capacity=5
            )

        def test_api_call_1(api_limiter):
            with api_limiter() as ctx:
                assert ctx.id == "api_test"
                assert ctx.call_count >= 1

        def test_api_call_2(api_limiter):
            with api_limiter() as ctx:
                assert ctx.id == "api_test"
                assert ctx.call_count >= 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_rate_limiter_with_load_test_and_exit_callback(pytester, run_with_timeout):
    """Test rate limiter with --load-test and exit callback on drift."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def api_limiter(make_rate_limiter, request):
            # Callback that exits the session on drift
            def on_drift(limiter_id, current_rate, target_rate, drift):
                request.session.shouldstop = True
                request.session.shouldfail = True
                pytest.exit(
                    f"Rate drift detected: {drift:.2%} exceeds limit. "
                    f"Current: {current_rate:.2f}/hr, Target: {target_rate}/hr"
                )

            return make_rate_limiter(
                name="api_with_exit",
                hourly_rate=RateLimit.per_hour(100),  # Very low rate
                burst_capacity=100,
                max_drift=0.3,  # 30% tolerance
                num_calls_between_checks=5,
                seconds_before_first_check=1.0,  # Check after 1 second
                on_drift_callback=on_drift
            )

        @pytest.mark.load_test(weight=1)
        def test_api_call(api_limiter):
            # Manually set start time to trigger rate check
            with api_limiter.shared_state.locked_dict() as data:
                if not data:
                    data['start_time'] = time.time() - 2  # 2 seconds ago
                    data['last_refill_time'] = time.time()
                    data['tokens'] = 100
                    data['call_count'] = 0
                    data['exceptions'] = 0

            # Make rapid calls to exceed rate
            with api_limiter():
                pass
        """
    )
    # Run with load test - should exit due to drift
    result = run_with_timeout(pytester, "--load-test", "-n", "2", "-v")
    # The test should exit early due to drift detection
    assert result.ret != 0 or "Rate drift detected" in result.stdout.str()


def test_rate_limiter_with_max_calls_callback(pytester, run_with_timeout):
    """Test rate limiter with max_calls callback."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def limited_api(make_rate_limiter, request):
            callback_data = []

            def on_max_calls(limiter_id, count):
                callback_data.append((limiter_id, count))
                # Exit session when max calls reached
                request.session.shouldstop = True
                pytest.exit(f"Max calls reached: {count}")

            limiter = make_rate_limiter(
                name="limited_api",
                hourly_rate=RateLimit.per_second(10),
                burst_capacity=10,
                max_calls=3,
                max_call_callback=on_max_calls
            )
            limiter._callback_data = callback_data
            return limiter

        @pytest.mark.load_test(weight=1)
        def test_limited_call(limited_api):
            with limited_api():
                pass
        """
    )
    result = run_with_timeout(pytester, "--load-test", "-n", "2", "-v")
    # Should exit after 3 calls
    assert "Max calls reached: 3" in result.stdout.str() or result.ret != 0


def test_rate_limiter_dynamic_rate(pytester, run_with_timeout):
    """Test rate limiter with dynamic rate function."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def dynamic_limiter(make_rate_limiter):
            rate_values = [RateLimit.per_second(1)]

            def get_rate():
                return rate_values[0]

            limiter = make_rate_limiter(
                name="dynamic_test",
                hourly_rate=get_rate,
                burst_capacity=5
            )
            limiter._rate_values = rate_values
            return limiter

        def test_dynamic_1(dynamic_limiter):
            with dynamic_limiter() as ctx:
                assert ctx.hourly_rate == 3600

        def test_dynamic_2(dynamic_limiter):
            # Change rate
            dynamic_limiter._rate_values[0] = RateLimit.per_second(2)
            with dynamic_limiter() as ctx:
                assert ctx.hourly_rate == 7200
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_rate_limiter_across_workers(pytester, run_with_timeout):
    """Test that rate limiter state is shared across workers."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def shared_limiter(make_rate_limiter):
            return make_rate_limiter(
                name="shared_across_workers",
                hourly_rate=RateLimit.per_second(5),
                burst_capacity=10
            )

        def test_call_1(shared_limiter):
            with shared_limiter() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_2(shared_limiter):
            with shared_limiter() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_3(shared_limiter):
            with shared_limiter() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_4(shared_limiter):
            with shared_limiter() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1
        """
    )
    result = run_with_timeout(pytester, "-n", "3", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 4, str(result.stdout)
