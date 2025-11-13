"""Tests for RateLimit class."""

import pytest

from pytest_xdist_rate_limit import RateLimit


def test_rate_limit_per_second():
    """Test RateLimit.per_second factory method."""
    rate = RateLimit.per_second(10)
    assert rate.calls_per_hour == 36000

    rate = RateLimit.per_second(1)
    assert rate.calls_per_hour == 3600

    rate = RateLimit.per_second(0.5)
    assert rate.calls_per_hour == 1800


def test_rate_limit_per_minute():
    """Test RateLimit.per_minute factory method."""
    rate = RateLimit.per_minute(100)
    assert rate.calls_per_hour == 6000

    rate = RateLimit.per_minute(60)
    assert rate.calls_per_hour == 3600

    rate = RateLimit.per_minute(1)
    assert rate.calls_per_hour == 60


def test_rate_limit_per_hour():
    """Test RateLimit.per_hour factory method."""
    rate = RateLimit.per_hour(3600)
    assert rate.calls_per_hour == 3600

    rate = RateLimit.per_hour(1000)
    assert rate.calls_per_hour == 1000


def test_rate_limit_per_day():
    """Test RateLimit.per_day factory method."""
    rate = RateLimit.per_day(86400)
    assert rate.calls_per_hour == 3600

    rate = RateLimit.per_day(24000)
    assert rate.calls_per_hour == 1000

    rate = RateLimit.per_day(2400)
    assert rate.calls_per_hour == 100


def test_rate_limit_direct_construction():
    """Test direct RateLimit construction."""
    rate = RateLimit(5000)
    assert rate.calls_per_hour == 5000


def test_rate_limit_invalid_rate():
    """Test that invalid rates raise ValueError."""
    with pytest.raises(ValueError, match="calls_per_hour must be positive"):
        RateLimit(0)

    with pytest.raises(ValueError, match="calls_per_hour must be positive"):
        RateLimit(-100)


def test_rate_limit_repr():
    """Test RateLimit string representation."""
    rate = RateLimit.per_hour(3600)
    assert repr(rate) == "RateLimit(3600 calls/hour)"

    rate = RateLimit.per_second(10)
    assert repr(rate) == "RateLimit(36000 calls/hour)"


def test_rate_limit_with_token_bucket(pytester, run_with_timeout):
    """Test using RateLimit with TokenBucketRateLimiter."""
    pytester.makeconftest("""
import pytest
from pytest_xdist_rate_limit import make_shared_json

pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
""")
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_with_rate_limit(make_shared_json):
            shared = make_shared_json(name="rate_limit_test")

            # Use RateLimit.per_second
            rate = RateLimit.per_second(1)
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=rate,
                burst_capacity=2
            )

            # Verify the rate is correctly converted
            assert limiter.hourly_rate == 3600

            # Test it works
            with limiter() as ctx:
                assert ctx.call_count == 1
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_rate_limit_callable_with_token_bucket(pytester, run_with_timeout):
    """Test using callable RateLimit with TokenBucketRateLimiter."""
    pytester.makeconftest("""
import pytest
from pytest_xdist_rate_limit import make_shared_json

pytest_plugins = ['pytest_xdist_rate_limit.concurrent_fixtures']
""")
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_callable_rate_limit(make_shared_json):
            shared = make_shared_json(name="callable_rate_test")

            # Use callable that returns RateLimit
            rate_value = [RateLimit.per_second(1)]

            def get_rate():
                return rate_value[0]

            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=get_rate,
                burst_capacity=2
            )

            # Verify initial rate
            assert limiter.hourly_rate == 3600

            # Change rate
            rate_value[0] = RateLimit.per_second(2)

            # Verify new rate is used
            assert limiter.hourly_rate == 7200
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)
