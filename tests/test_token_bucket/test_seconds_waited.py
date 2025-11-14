"""Tests for RateLimitContext.seconds_waited field."""

# Conftest content to inject into pytester tests
CONFTEST_CONTENT = """
import pytest
from pytest_xdist_rate_limit import make_shared_json

pytest_plugins = ['pytest_xdist_rate_limit.shared_json', 'pytest_xdist_rate_limit.rate_limiter_fixture']
"""


def test_seconds_waited_no_wait(pytester, run_with_timeout):
    """Test that seconds_waited is 0 when no waiting occurs."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_no_wait(make_shared_json):
            shared = make_shared_json(name="no_wait_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(10),
                burst_capacity=5
            )

            # First call should not wait (burst capacity available)
            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0, f"Expected 0 wait, got {ctx.seconds_waited}"
                assert ctx.call_count == 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_seconds_waited_with_wait(pytester, run_with_timeout):
    """Test that seconds_waited reflects actual wait time."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_with_wait(make_shared_json):
            shared = make_shared_json(name="wait_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(1),
                burst_capacity=2
            )

            # First two calls use burst capacity (no wait)
            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0
                assert ctx.call_count == 1

            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0
                assert ctx.call_count == 2

            # Third call should wait approximately 1 second
            with limiter() as ctx:
                assert ctx.seconds_waited > 0.9, f"Expected ~1s wait, got {ctx.seconds_waited}s"
                assert ctx.seconds_waited < 1.2, f"Wait time too long: {ctx.seconds_waited}s"
                assert ctx.call_count == 3
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_seconds_waited_multiple_waits(pytester, run_with_timeout):
    """Test seconds_waited across multiple calls with varying wait times."""
    pytester.makeconftest(CONFTEST_CONTENT)
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_multiple_waits(make_shared_json):
            shared = make_shared_json(name="multiple_wait_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(2),  # 2 calls per second
                burst_capacity=1
            )

            wait_times = []

            # First call: no wait (burst available)
            with limiter() as ctx:
                wait_times.append(ctx.seconds_waited)
                assert ctx.seconds_waited == 0.0

            # Second call: should wait ~0.5 seconds
            with limiter() as ctx:
                wait_times.append(ctx.seconds_waited)
                assert ctx.seconds_waited > 0.4, f"Expected ~0.5s wait, got {ctx.seconds_waited}s"
                assert ctx.seconds_waited < 0.7, f"Wait time too long: {ctx.seconds_waited}s"

            # Third call: should also wait ~0.5 seconds
            with limiter() as ctx:
                wait_times.append(ctx.seconds_waited)
                assert ctx.seconds_waited > 0.4, f"Expected ~0.5s wait, got {ctx.seconds_waited}s"
                assert ctx.seconds_waited < 0.7, f"Wait time too long: {ctx.seconds_waited}s"

            # Verify we tracked different wait times
            assert len(wait_times) == 3
            assert wait_times[0] == 0.0
            assert wait_times[1] > 0
            assert wait_times[2] > 0
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)

