"""
Token Bucket Rate Limiter

This module provides a token bucket rate limiter implementation that can be used
to control the rate of operations across multiple processes.
"""

import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, Optional, Tuple, Union

from pytest_xdist_rate_limit.shared_json import SharedJson

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RateLimit:
    """
    Represents a rate limit with convenient factory methods for different time units.

    Examples:
        >>> rate = RateLimit.per_second(10)  # 10 calls per second
        >>> rate = RateLimit.per_minute(600)  # 600 calls per minute
        >>> rate = RateLimit.per_hour(3600)  # 3600 calls per hour
        >>> rate = RateLimit.per_day(86400)  # 86400 calls per day
    """

    def __init__(self, calls_per_hour: int):
        if calls_per_hour <= 0:
            raise ValueError("calls_per_hour must be positive")
        self._calls_per_hour = calls_per_hour

    @property
    def calls_per_hour(self) -> int:
        return self._calls_per_hour

    @classmethod
    def per_second(cls, calls: Union[int, float]) -> "RateLimit":
        return cls(int(calls * 3600))

    @classmethod
    def per_minute(cls, calls: Union[int, float]) -> "RateLimit":
        return cls(int(calls * 60))

    @classmethod
    def per_hour(cls, calls: int) -> "RateLimit":
        return cls(calls)

    @classmethod
    def per_day(cls, calls: Union[int, float]) -> "RateLimit":
        return cls(int(calls / 24))

    def __repr__(self) -> str:
        return f"RateLimit({self._calls_per_hour} calls/hour)"


class TokenBucketRateLimiter:
    """
    A token bucket rate limiter that tracks and limits the rate of operations.

    This class implements the token bucket algorithm, a classical rate limiting
    algorithm that allows for controlled bursts of activity. It is designed to be
    used with pytest-xdist to coordinate rate limiting across multiple worker processes.

    The limiter can be used as a callable context manager:

    Example:
        with pacer() as ctx:
            print(f"Using rate limiter {ctx.id} with rate {ctx.hourly_rate}/hr")
            perform_action()
    """

    def __init__(
        self,
        shared_state: SharedJson,
        hourly_rate: Union[RateLimit, Callable[[], RateLimit]],
        max_drift: float = 0.1,
        on_drift_callback: Optional[Callable[[str, float, float, float], None]] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        max_call_callback: Optional[Callable[[str, int], None]] = None,
    ):
        """
        Initialize a token bucket rate limiter.

        Args:
            shared_state: SharedJson instance for state management across workers
            hourly_rate: Rate limit specification. Can be:
                        - RateLimit: rate limit object (e.g., RateLimit.per_second(10))
                        - Callable: function returning RateLimit
            max_drift: Maximum allowed drift from the expected rate (as a fraction)
            on_drift_callback: Callback function to execute when drift exceeds max_drift
                               Function signature: (id: str, current_rate: float,
                               target_rate: float, drift: float) -> None
            num_calls_between_checks: Number of calls between rate drift checks (default: 10)
            seconds_before_first_check: Minimum elapsed time (seconds) before rate checking begins
                                       (default: 60.0 seconds)
            burst_capacity: Maximum number of tokens that can be stored in the bucket
                           (defaults to 10% of hourly rate or 1, whichever is larger)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            max_call_callback: Callback function to execute when max_calls is reached
                               Function signature: (id: str, call_count: int) -> None
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
        self.max_drift = max_drift
        self.on_drift_callback = on_drift_callback
        self.num_calls_between_checks = num_calls_between_checks
        self.seconds_before_first_check = seconds_before_first_check
        self.burst_capacity = (
            burst_capacity
            if burst_capacity is not None
            else self._calculate_default_burst_capacity(self.hourly_rate)
        )
        self.max_calls = max_calls
        self.max_call_callback = max_call_callback

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

    def _check_rate(self, state: Dict[str, Any]) -> None:
        """Check if the current rate is within acceptable limits."""
        current_time = time.time()
        start_time = state["start_time"]
        elapsed_time = current_time - start_time

        # Only check if we have enough data
        if elapsed_time < self.seconds_before_first_check:
            return

        current_rate = (state["call_count"] / elapsed_time) * 3600
        target_rate = self.hourly_rate

        # Calculate drift as a fraction of the target rate
        if target_rate > 0:
            drift = abs(current_rate - target_rate) / target_rate
        else:
            drift = 0 if current_rate == 0 else float("inf")

        logger.info(
            f"Rate check for {self.shared_state.name}: current={current_rate:.2f}/hr, "
            f"target={target_rate}/hr, drift={drift:.2%}. "
            f"Total calls: {state['call_count']}. Exceptions: {state['exceptions']}"
        )

        if drift > self.max_drift:
            message = (
                f"Rate drift for {self.shared_state.name} exceeds maximum allowed: "
                f"current={current_rate:.2f}/hr, target={target_rate}/hr, "
                f"drift={drift:.2%} (max allowed: {self.max_drift:.2%})"
            )
            logger.error(message)

            if self.on_drift_callback:
                self.on_drift_callback(
                    self.shared_state.name, current_rate, target_rate, drift
                )

    def _calculate_wait_time_and_update(self) -> float:
        """
        Calculate how long to wait before allowing the next call using token bucket algorithm.
        Updates state atomically within the lock.

        The token bucket algorithm works by:
        1. Adding tokens to the bucket at a constant rate (the refill rate)
        2. When a request arrives, it takes a token from the bucket if one is available
        3. If no tokens are available, the request must wait until a token becomes available
        4. The bucket has a maximum capacity to limit bursts

        Returns:
            float: Wait time in seconds (0 if can proceed immediately)
        """
        current_time = time.time()

        with self.shared_state.locked_dict() as state:
            # Initialize if needed
            if not state:
                state.update(
                    {
                        "start_time": current_time,
                        "last_refill_time": current_time,
                        "tokens": self.burst_capacity,
                        "call_count": 0,
                        "exceptions": 0,
                    }
                )

            # Calculate tokens to add based on time elapsed since last refill
            tokens_per_second = self.hourly_rate / 3600
            elapsed_seconds = current_time - state["last_refill_time"]
            new_tokens = elapsed_seconds * tokens_per_second

            # Update tokens (can't exceed burst capacity)
            tokens = min(state["tokens"] + new_tokens, self.burst_capacity)

            # Always consume 1 token immediately, even if it makes tokens negative
            # This ensures proper serialization across multiple threads/processes
            # Negative tokens represent a "debt" that must be paid back with wait time
            state["tokens"] = tokens - 1
            state["last_refill_time"] = current_time

            # If we had at least 1 token, we can proceed immediately
            if tokens >= 1:
                return 0

            # Calculate wait time to pay back the token debt
            # We need to wait until tokens would have refilled to 0
            wait_time = abs(state["tokens"]) / tokens_per_second
            return wait_time

    def _increment_call_count_and_check_rate(self) -> Tuple[int, Dict[str, Any]]:
        """
        Increment call count and check rate if needed.

        Returns:
            tuple: (call_count, state_snapshot)
        """
        with self.shared_state.locked_dict() as state:
            call_count = state["call_count"] + 1
            state["call_count"] = call_count

            # Check rate periodically
            if call_count % self.num_calls_between_checks == 0:
                self._check_rate(state)

            # Create snapshot for context
            state_snapshot = dict(state)

        return call_count, state_snapshot

    def _track_exception(self) -> None:
        """Track that an exception occurred during rate-limited execution."""
        with self.shared_state.locked_dict() as state:
            state["exceptions"] = state.get("exceptions", 0) + 1

    def _check_max_calls(self, call_count: int) -> None:
        """Check if max_calls limit has been reached and invoke callback if configured."""
        if self.max_calls > 0 and call_count >= self.max_calls:
            logger.info(
                f"Rate limiter {self.shared_state.name} reached max_calls limit of {self.max_calls}"
            )
            if self.max_call_callback:
                self.max_call_callback(self.shared_state.name, call_count)

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
        """

        _limiter: "TokenBucketRateLimiter"
        _state: dict

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

    def __call__(self):
        """
        Make the rate limiter callable as a context manager.

        This allows using the rate limiter with cleaner syntax:
            with pacer():
                ...

        Returns:
            Context manager for rate limiting

        Example:
            with pacer() as ctx:
                print(f"Call count: {ctx.call_count}")
                perform_action()
        """
        return self.rate_limited_context()

    @contextlib.contextmanager
    def rate_limited_context(self) -> Generator[RateLimitContext, Any, None]:
        """
        Context manager that rate-limits the enclosed code using token bucket algorithm.

        Example:
            with rate_limiter.rate_limited_context() as ctx:
                print(f"Using rate limiter {ctx.id} with rate {ctx.hourly_rate}/hr")
                print(f"Current call count: {ctx.call_count}")
                print(f"First call at: {ctx.start_time}")
                perform_action()
        """
        # Calculate wait time and update tokens atomically
        wait_time = self._calculate_wait_time_and_update()

        if wait_time > 0:
            logger.debug(
                f"Token bucket rate limiter {self.id} waiting for {wait_time:.2f} seconds"
            )
            time.sleep(wait_time)
        else:
            logger.debug(f"Token bucket rate limiter {self.id} can proceed immediately")

        # Update call count and check rate
        call_count, state_snapshot = self._increment_call_count_and_check_rate()
        context = self.RateLimitContext(self, state_snapshot)

        try:
            yield context
        except Exception:
            self._track_exception()
            raise
        finally:
            self._check_max_calls(call_count)
