"""Pacer fixture for pytest-xdist workers.

This module provides fixtures for creating pacers that share state
across multiple pytest-xdist workers.
"""

from typing import Callable, Optional, Union

import pytest

from pytest_xdist_rate_limit.events import (
    DriftEvent,
    MaxCallsEvent,
    PeriodicCheckEvent,
)
from pytest_xdist_rate_limit.rate import Rate
from pytest_xdist_rate_limit.token_bucket_rate_limiter import TokenBucketPacer

# Type aliases for callback signatures
DriftCallback = Callable[[DriftEvent], None]
MaxCallsCallback = Callable[[MaxCallsEvent], None]
PeriodicCheckCallback = Callable[[PeriodicCheckEvent], None]


@pytest.fixture(scope="session")
def make_pacer(make_shared_json):
    """Factory for creating pacer fixtures across pytest-xdist workers.

    This fixture provides a way to create TokenBucketPacer instances
    that share state across workers using SharedJson.

    Example:
        @pytest.fixture(scope="session")
        def pacer(make_pacer):
            from pytest_xdist_rate_limit import Rate

            return make_pacer(
                name="pacer",
                hourly_rate=Rate.per_second(10)
            )

        def test_api_call(pacer):
            with pacer() as ctx:
                # Entering the context will wait if required to respect the rate
                pass
    """

    def factory(
        name: str,
        hourly_rate: Union[Rate, Callable[[], Rate]],
        max_drift: float = 0.1,
        on_drift_callback: Optional[DriftCallback] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        on_max_calls_callback: Optional[MaxCallsCallback] = None,
        on_periodic_check_callback: Optional[PeriodicCheckCallback] = None,
    ) -> TokenBucketPacer:
        """Create a TokenBucketPacer instance with shared state.

        Args:
            name: Unique name for this pacer
            hourly_rate: Target rate (Rate object or callable returning one)
            max_drift: Maximum allowed drift from expected rate (0-1)
            on_drift_callback: Callback when drift exceeds max_drift
            num_calls_between_checks: Number of calls between periodic checks (default: 10)
            seconds_before_first_check: Minimum time before rate checking begins
            burst_capacity: Maximum tokens in bucket (defaults to 10% of hourly rate)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            on_max_calls_callback: Callback when max_calls is reached
            on_periodic_check_callback: Callback for periodic metrics checks

        Returns:
            TokenBucketPacer: Pacer instance with shared state across workers

        Note:
            For detailed parameter documentation, see TokenBucketPacer.__init__
        """
        shared_state = make_shared_json(name=name)

        return TokenBucketPacer(
            shared_state=shared_state,
            hourly_rate=hourly_rate,
            max_drift=max_drift,
            on_drift_callback=on_drift_callback,
            num_calls_between_checks=num_calls_between_checks,
            seconds_before_first_check=seconds_before_first_check,
            burst_capacity=burst_capacity,
            max_calls=max_calls,
            on_max_calls_callback=on_max_calls_callback,
            on_periodic_check_callback=on_periodic_check_callback,
        )

    return factory


@pytest.fixture(scope="session")
def make_rate_limiter(make_pacer):
    """Deprecated: Use make_pacer instead.

    Factory for creating pacer fixtures across pytest-xdist workers.
    This fixture is deprecated and will be removed in a future version.
    Please use make_pacer instead.
    """
    import warnings
    warnings.warn(
        "make_rate_limiter is deprecated, use make_pacer instead",
        DeprecationWarning,
        stacklevel=3
    )
    return make_pacer

