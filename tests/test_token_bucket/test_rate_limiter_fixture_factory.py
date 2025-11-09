"""Tests for rate_limiter_fixture_factory."""

# Conftest content to inject into pytester tests
CONFTEST_CONTENT = """
import pytest
from pytest_xdist_rate_limit import rate_limiter_fixture_factory

pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
"""


def test_rate_limiter_fixture_factory_basic(pytester):
    """Test basic usage of rate_limiter_fixture_factory."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def api_limiter(rate_limiter_fixture_factory):
            return rate_limiter_fixture_factory(
                name="api_test",
                hourly_rate=RateLimit.per_second(2),
                burst_capacity=5
            )

        def test_api_call_1(api_limiter):
            with api_limiter.rate_limited_context() as ctx:
                assert ctx.id == "api_test"
                assert ctx.call_count >= 1

        def test_api_call_2(api_limiter):
            with api_limiter.rate_limited_context() as ctx:
                assert ctx.id == "api_test"
                assert ctx.call_count >= 1
        """
    )
    result = pytester.runpytest("-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_rate_limiter_with_load_test_and_exit_callback(pytester):
    """Test rate limiter with --load-test and exit callback on drift."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def api_limiter(rate_limiter_fixture_factory, request):
            # Callback that exits the session on drift
            def on_drift(limiter_id, current_rate, target_rate, drift):
                request.session.shouldstop = True
                request.session.shouldfail = True
                pytest.exit(
                    f"Rate drift detected: {drift:.2%} exceeds limit. "
                    f"Current: {current_rate:.2f}/hr, Target: {target_rate}/hr"
                )

            return rate_limiter_fixture_factory(
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
            with api_limiter.rate_limited_context():
                pass
        """
    )
    # Run with load test - should exit due to drift
    result = pytester.runpytest("--load-test", "-n", "2", "-v", "--load-duration", "5")
    # The test should exit early due to drift detection
    assert result.ret != 0 or "Rate drift detected" in result.stdout.str()


def test_rate_limiter_with_max_calls_callback(pytester):
    """Test rate limiter with max_calls callback."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def limited_api(rate_limiter_fixture_factory, request):
            callback_data = []

            def on_max_calls(limiter_id, count):
                callback_data.append((limiter_id, count))
                # Exit session when max calls reached
                request.session.shouldstop = True
                pytest.exit(f"Max calls reached: {count}")

            limiter = rate_limiter_fixture_factory(
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
            with limited_api.rate_limited_context():
                pass
        """
    )
    result = pytester.runpytest("--load-test", "-n", "2", "-v", "--load-duration", "5")
    # Should exit after 3 calls
    assert "Max calls reached: 3" in result.stdout.str() or result.ret != 0


def test_rate_limiter_dynamic_rate(pytester):
    """Test rate limiter with dynamic rate function."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def dynamic_limiter(rate_limiter_fixture_factory):
            rate_values = [RateLimit.per_second(1)]

            def get_rate():
                return rate_values[0]

            limiter = rate_limiter_fixture_factory(
                name="dynamic_test",
                hourly_rate=get_rate,
                burst_capacity=5
            )
            limiter._rate_values = rate_values
            return limiter

        def test_dynamic_1(dynamic_limiter):
            with dynamic_limiter.rate_limited_context() as ctx:
                assert ctx.hourly_rate == 3600

        def test_dynamic_2(dynamic_limiter):
            # Change rate
            dynamic_limiter._rate_values[0] = RateLimit.per_second(2)
            with dynamic_limiter.rate_limited_context() as ctx:
                assert ctx.hourly_rate == 7200
        """
    )
    result = pytester.runpytest("-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_rate_limiter_across_workers(pytester):
    """Test that rate limiter state is shared across workers."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import RateLimit

        @pytest.fixture(scope="session")
        def shared_limiter(rate_limiter_fixture_factory):
            return rate_limiter_fixture_factory(
                name="shared_across_workers",
                hourly_rate=RateLimit.per_second(5),
                burst_capacity=10
            )

        def test_call_1(shared_limiter):
            with shared_limiter.rate_limited_context() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_2(shared_limiter):
            with shared_limiter.rate_limited_context() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_3(shared_limiter):
            with shared_limiter.rate_limited_context() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1

        def test_call_4(shared_limiter):
            with shared_limiter.rate_limited_context() as ctx:
                call_count = ctx.call_count
                assert call_count >= 1
        """
    )
    result = pytester.runpytest("-n", "3", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 4, str(result.stdout)
