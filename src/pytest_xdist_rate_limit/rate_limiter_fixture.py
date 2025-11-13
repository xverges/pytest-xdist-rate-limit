"""Rate limiter fixture utilities for pytest-xdist workers.

This module provides fixtures for creating rate limiters that share state
across multiple pytest-xdist workers.
"""

from typing import Callable, Optional, Union

import pytest


@pytest.fixture(scope="session")
def make_rate_limiter(make_shared_json):
    """Factory for creating rate limiter fixtures across pytest-xdist workers.

    This fixture provides a way to create TokenBucketRateLimiter instances
    that share state across workers using SharedJson.

    Example:
        @pytest.fixture(scope="session")
        def pacer(make_rate_limiter):
            from pytest_xdist_rate_limit import RateLimit

            return make_rate_limiter(
                name="pacer",
                hourly_rate=RateLimit.per_second(10)
            )

        def test_api_call(pacer):
            with pacer() as ctx:
                # Entering the context will wait if required to respect the rate
                pass
    """
    from pytest_xdist_rate_limit import (
        RateLimit,
        TokenBucketRateLimiter,
    )

    def factory(
        name: str,
        hourly_rate: Union[RateLimit, Callable[[], RateLimit]],
        max_drift: float = 0.1,
        on_drift_callback: Optional[Callable[[str, float, float, float], None]] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        max_call_callback: Optional[Callable[[str, int], None]] = None,
    ) -> TokenBucketRateLimiter:
        """Create a TokenBucketRateLimiter instance with shared state.

        Args:
            name: Unique name for this rate limiter
            hourly_rate: Rate limit (RateLimit object or callable returning one)
            max_drift: Maximum allowed drift from expected rate (0-1)
            on_drift_callback: Callback when drift exceeds max_drift
            num_calls_between_checks: Number of calls between rate checks
            seconds_before_first_check: Minimum time before rate checking begins
            burst_capacity: Maximum tokens in bucket (defaults to 10% of hourly rate)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            max_call_callback: Callback when max_calls is reached

        Returns:
            TokenBucketRateLimiter: Rate limiter instance
        """
        shared_state = make_shared_json(name=name)

        return TokenBucketRateLimiter(
            shared_state=shared_state,
            hourly_rate=hourly_rate,
            max_drift=max_drift,
            on_drift_callback=on_drift_callback,
            num_calls_between_checks=num_calls_between_checks,
            seconds_before_first_check=seconds_before_first_check,
            burst_capacity=burst_capacity,
            max_calls=max_calls,
            max_call_callback=max_call_callback,
        )

    return factory

