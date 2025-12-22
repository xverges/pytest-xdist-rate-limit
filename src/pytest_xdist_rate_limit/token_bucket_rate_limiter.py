"""
Token Bucket Pacer

This module provides a token bucket pacer implementation that can be used
to generate load at a controlled rate across multiple processes.

The pacer tracks distribution-based statistics using TDigest
for percentile calculations without storing all samples.
These statistics are provided via PeriodicCheckEvent callbacks.
"""
from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Generator, List, Optional, Union

from pytest_xdist_rate_limit.events import (
    DriftEvent,
    MaxCallsEvent,
    PeriodicCheckEvent,
)
from pytest_xdist_rate_limit.pacer_metrics import PacerMetrics
from pytest_xdist_rate_limit.rate import Rate
from pytest_xdist_rate_limit.rate_monitor import RateMonitor
from pytest_xdist_rate_limit.shared_json import SharedJson
from pytest_xdist_rate_limit.token_bucket_algorithm import TokenBucketAlgorithm

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TokenBucketPacer:
    """
    A token bucket pacer that generates load at a controlled rate.

    This class uses the token bucket algorithm to pace operations at a target rate,
    allowing for controlled bursts of activity. It is designed to be used with
    pytest-xdist to coordinate call pacing across multiple worker processes.

    The pacer can be used as a callable context manager:

    Example:
        with pacer() as ctx:
            print(f"Using pacer {ctx.id} with rate {ctx.hourly_rate}/hr")
            perform_action()
    """

    def __init__(
        self,
        shared_state: SharedJson,
        hourly_rate: Union[Rate, Callable[[], Rate]],
        max_drift: float = 0.1,
        on_drift_callback: Optional[Callable[[DriftEvent], None]] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        on_max_calls_callback: Optional[Callable[[MaxCallsEvent], None]] = None,
        on_periodic_check_callback: Optional[Callable[[PeriodicCheckEvent], None]] = None,
        rate_windows: Optional[List[int]] = None,
    ):
        """
        Initialize a token bucket pacer.

        Args:
            shared_state: SharedJson instance for state management across workers
            hourly_rate: Target rate specification. Can be:
                        - Rate: target rate object (e.g., Rate.per_second(10))
                        - Callable: function returning Rate
            max_drift: Maximum allowed drift from the target rate (as a fraction)
            on_drift_callback: Callback function to execute when drift exceeds max_drift
                               Function signature: (event: DriftEvent) -> None
            num_calls_between_checks: Number of calls between periodic checks (default: 10)
                                     Used for both drift checking and periodic metrics callbacks
            seconds_before_first_check: Minimum elapsed time (seconds) before rate checking begins
                                       (default: 60.0 seconds)
            burst_capacity: Maximum number of tokens that can be stored in the bucket
                           (defaults to 10% of hourly rate or 1, whichever is larger)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            on_max_calls_callback: Callback function to execute when max_calls is reached
                                   Function signature: (event: MaxCallsEvent) -> None
            on_periodic_check_callback: Callback function for periodic metrics checks
                                       Function signature: (event: PeriodicCheckEvent) -> None
                                       Provides metrics for custom analysis (bottleneck detection, monitoring, etc.)
            rate_windows: Time windows in seconds for rate calculation (default: [60, 300, 900])
        """
        # Validate input parameters
        if not 0 <= max_drift <= 1:
            raise ValueError(f"max_drift must be between 0 and 1, got {max_drift}")
        if num_calls_between_checks < 1:
            raise ValueError(
                f"num_calls_between_checks must be positive, got {num_calls_between_checks}"
            )
        if seconds_before_first_check < 0:
            raise ValueError(
                f"seconds_before_first_check must be non-negative, got {seconds_before_first_check}"
            )
        if burst_capacity is not None and burst_capacity < 1:
            raise ValueError(f"burst_capacity must be positive, got {burst_capacity}")

        self.shared_state = shared_state
        self._hourly_rate = hourly_rate
        self.num_calls_between_checks = num_calls_between_checks
        self.max_calls = max_calls

        calculated_burst_capacity = (
            burst_capacity
            if burst_capacity is not None
            else self._calculate_default_burst_capacity(self.hourly_rate)
        )
        self.burst_capacity = calculated_burst_capacity

        self.algorithm = TokenBucketAlgorithm(
            hourly_rate=self.hourly_rate,
            burst_capacity=calculated_burst_capacity
        )

        self.metrics = PacerMetrics(
            rate_windows=rate_windows if rate_windows is not None else [60, 300, 900]
        )

        self.rate_monitor = RateMonitor(
            max_drift=max_drift,
            seconds_before_first_check=seconds_before_first_check,
            on_drift_callback=on_drift_callback,
            on_periodic_check_callback=on_periodic_check_callback,
            on_max_calls_callback=on_max_calls_callback
        )

    @staticmethod
    def _calculate_default_burst_capacity(hourly_rate: int) -> int:
        """Calculate default burst capacity as 10% of hourly rate, minimum 1."""
        return max(1, int(hourly_rate * 0.1))

    @property
    def id(self) -> str:
        """Get the identifier from the shared state name."""
        return self.shared_state.name

    @property
    def hourly_rate(self) -> int:
        """Get the current hourly rate."""
        rate = self._hourly_rate() if callable(self._hourly_rate) else self._hourly_rate
        return rate.calls_per_hour


    def _track_exception(self) -> None:
        """Track that an exception occurred during rate-limited execution."""
        with self.shared_state.locked_dict() as state:
            state["exceptions"] = state.get("exceptions", 0) + 1


    @dataclass
    class RateLimitContext:
        """
        Context object yielded by rate_limited_context that provides access to rate limiter metrics.

        Properties:
            id: Rate limiter identifier
            hourly_rate: Configured rate limit in calls per hour
            call_count: Total number of calls made
            exceptions: Total number of exceptions encountered
            start_time: Unix timestamp of when the first call was made
            seconds_waited: Number of seconds waited before entering the context
        """

        _limiter: TokenBucketPacer
        _state: dict
        seconds_waited: float = 0.0

        @property
        def id(self) -> str:
            return self._limiter.shared_state.name

        @property
        def hourly_rate(self) -> int:
            return self._limiter.hourly_rate

        @property
        def call_count(self) -> int:
            return self._state["call_count"]

        @property
        def exceptions(self) -> int:
            return self._state["exceptions"]

        @property
        def start_time(self) -> float:
            """Timestamp of when the first call was made (Unix timestamp)."""
            return self._state["start_time"]

    def __call__(self, timeout: Optional[float] = None):
        """
        Make the rate limiter callable as a context manager.

        Equivalent to calling rate_limited_context()
        """
        return self.rate_limited_context(timeout=timeout)

    @contextlib.contextmanager
    def rate_limited_context(
        self, timeout: Optional[float] = None
    ) -> Generator[RateLimitContext, Any, None]:
        """
        Context manager that rate-limits the enclosed code using token bucket algorithm.

        Args:
            timeout: Maximum time in seconds to wait for a token (None for no timeout)

        Example:
            with rate_limiter.rate_limited_context() as ctx:
                print(f"Using rate limiter {ctx.id} with rate {ctx.hourly_rate}/hr")
                print(f"Current call count: {ctx.call_count}")
                print(f"First call at: {ctx.start_time}")
                print(f"Waited {ctx.seconds_waited:.2f} seconds")
                perform_action()

            with rate_limiter.rate_limited_context(timeout=5.0) as ctx:
                print(f"Will timeout after 5 seconds")
                perform_action()
        """
        current_time = time.time()

        # Reserve token slot
        with self.shared_state.locked_dict() as state:
            # Initialize top-level orchestrator fields if needed
            if "start_time" not in state:
                state["start_time"] = current_time
                state["call_count"] = 0
                state["exceptions"] = 0

            wait_time, target_time, updated_algo_state = self.algorithm.reserve_token_slot(
                algorithm_state=state.get("token_bucket"),
                limiter_id=self.id,
                timeout=timeout
            )
            state["token_bucket"] = updated_algo_state

            # Increment call count (orchestrator responsibility)
            state["call_count"] += 1
            call_count = state["call_count"]

            # Collect monitoring data inside lock for callbacks outside lock
            should_check_periodic = call_count % self.num_calls_between_checks == 0

            state_snapshot = dict(state)

        # Invoke monitoring callbacks outside lock to avoid blocking other workers
        if should_check_periodic:
            self.rate_monitor.check_rate(
                state=state_snapshot,
                limiter_id=self.id,
                target_rate=self.hourly_rate,
                limiter=self
            )
            stats_state = state_snapshot.get("statistics", {})
            self.rate_monitor.periodic_check(
                state=state_snapshot,
                stats_state=stats_state,
                limiter_id=self.id,
                target_rate=self.hourly_rate,
                limiter=self,
                metrics=self.metrics
            )
            if self.max_calls > 0 and call_count >= self.max_calls:
                self.rate_monitor.check_max_calls(
                    call_count=call_count,
                    max_calls=self.max_calls,
                    state_snapshot=state_snapshot,
                    limiter_id=self.id,
                    limiter=self
                )

        # Sleep outside lock
        if wait_time > 0:
            actual_wait = target_time - time.time()
            if actual_wait > 0:
                logger.debug(
                    f"Token bucket rate limiter {self.id} waiting for {actual_wait:.2f} seconds"
                )
                time.sleep(actual_wait)

        entry_time = time.perf_counter()
        context = self.RateLimitContext(self, state_snapshot, seconds_waited=wait_time)

        try:
            yield context
        except Exception:
            with self.shared_state.locked_dict() as state:
                state["exceptions"] = state.get("exceptions", 0) + 1
            raise
        finally:
            call_duration = time.perf_counter() - entry_time

            # Update statistics
            with self.shared_state.locked_dict() as state:
                stats_state = state.get("statistics")
                stats_state = self.metrics.update_duration_stats(
                    stats_state=stats_state,
                    duration=call_duration
                )
                stats_state = self.metrics.update_wait_stats(
                    stats_state=stats_state,
                    wait_time=wait_time
                )
                stats_state = self.metrics.track_call_timestamp(
                    stats_state=stats_state,
                    timestamp=entry_time
                )
                state["statistics"] = stats_state
