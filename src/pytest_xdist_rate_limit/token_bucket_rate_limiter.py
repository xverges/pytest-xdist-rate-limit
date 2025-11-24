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


@dataclass
class RateLimitEvent:
    """Base class for all rate limiter events.
    
    Provides common context available to all callback events.
    
    Attributes:
        limiter_id: Unique identifier for the rate limiter
        limiter: Reference to the TokenBucketRateLimiter instance
        state_snapshot: Snapshot of shared state at the time of the event
    """
    limiter_id: str
    limiter: 'TokenBucketRateLimiter'
    state_snapshot: Dict[str, Any]
    
    @property
    def call_count(self) -> int:
        """Total number of calls made."""
        return self.state_snapshot['call_count']
    
    @property
    def exceptions(self) -> int:
        """Total number of exceptions encountered."""
        return self.state_snapshot['exceptions']
    
    @property
    def start_time(self) -> float:
        """Unix timestamp of when the first call was made."""
        return self.state_snapshot['start_time']
    
    @property
    def elapsed_time(self) -> float:
        """Time elapsed since the first call (in seconds)."""
        return time.time() - self.start_time


@dataclass
class DriftEvent(RateLimitEvent):
    """Event fired when rate drift exceeds the configured threshold.
    
    Attributes:
        current_rate: Actual rate in calls per hour
        target_rate: Target rate in calls per hour
        drift: Drift as a fraction of target rate (0.1 = 10% drift)
        max_drift: Maximum allowed drift (from configuration)
    """
    current_rate: float
    target_rate: float
    drift: float
    max_drift: float


@dataclass
class MaxCallsEvent(RateLimitEvent):
    """Event fired when the max_calls limit is reached.
    
    Attributes:
        max_calls: Maximum number of calls allowed (from configuration)
    """
    max_calls: int


class RateLimitTimeout(Exception):
    """Raised when rate limiter timeout is exceeded."""

    def __init__(self, limiter_id: str, timeout: float, required_wait: float):
        self.limiter_id = limiter_id
        self.timeout = timeout
        self.required_wait = required_wait
        super().__init__(
            f"Rate limiter '{limiter_id}' timeout of {timeout}s exceeded. "
            f"Would need to wait {required_wait:.2f}s to acquire token."
        )


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
        on_drift_callback: Optional[Callable[[DriftEvent], None]] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        on_max_calls_callback: Optional[Callable[[MaxCallsEvent], None]] = None,
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
                               Function signature: (event: DriftEvent) -> None
            num_calls_between_checks: Number of calls between rate drift checks (default: 10)
            seconds_before_first_check: Minimum elapsed time (seconds) before rate checking begins
                                       (default: 60.0 seconds)
            burst_capacity: Maximum number of tokens that can be stored in the bucket
                           (defaults to 10% of hourly rate or 1, whichever is larger)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            on_max_calls_callback: Callback function to execute when max_calls is reached
                                   Function signature: (event: MaxCallsEvent) -> None
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
        self.on_max_calls_callback = on_max_calls_callback


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
                event = DriftEvent(
                    limiter_id=self.shared_state.name,
                    limiter=self,
                    state_snapshot=dict(state),
                    current_rate=current_rate,
                    target_rate=target_rate,
                    drift=drift,
                    max_drift=self.max_drift,
                )
                self.on_drift_callback(event)


    def _initialize_state(self, state: Dict[str, Any], current_time: float) -> None:
        """Initialize the token bucket state if empty."""
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

    def _refill_tokens(self, tokens: float, last_refill_time: float, current_time: float) -> float:
        """Calculate and return available tokens after refilling.

        Args:
            tokens: Current token count
            last_refill_time: Time of last refill
            current_time: Current time

        Returns:
            float: Available tokens (before consumption)
        """
        if (current_time - last_refill_time) < 0:
            return 0
        tokens_per_second = self.hourly_rate / 3600
        elapsed_seconds = current_time - last_refill_time
        new_tokens = elapsed_seconds * tokens_per_second
        return min(tokens + new_tokens, self.burst_capacity)

    def _consume_token(self, state: Dict[str, Any], tokens: float) -> None:
        """Consume one token from the bucket.

        Args:
            state: The shared state dictionary
            tokens: Available tokens before consumption
        """
        # Always consume 1 token immediately, even if it makes tokens negative
        # Negative tokens represent a "debt" that must be paid back with wait time
        state["tokens"] = tokens - 1

    def _calculate_wait_time(self, tokens: float) -> float:
        """Calculate how long to wait based on token availability.

        Args:
            tokens: Available tokens (before consumption)

        Returns:
            float: Wait time in seconds (0 if can proceed immediately)
        """
        if tokens >= 1:
            return 0

        # Calculate wait time to pay back the token debt
        tokens_per_second = self.hourly_rate / 3600
        # After consuming, tokens will be (tokens - 1), which is negative
        # We need to wait until tokens refill to 0
        return abs(tokens - 1) / tokens_per_second

    def _reserve_slot_and_get_target_time(
        self, state: Dict[str, Any], wait_time: float, current_time: float, tokens: float
    ) -> float:
        """Reserve a slot and calculate the target time when this worker can proceed.

        This method updates the state to reserve a slot for this worker, then returns
        the target time. The caller must release the lock and sleep until the target time.

        Args:
            state: The shared state dictionary
            wait_time: Time to wait in seconds
            current_time: The time when we entered the lock

        Returns:
            float: Target time (Unix timestamp) when this worker can proceed
        """
        if wait_time > 0:
            # Pay token with its wait time equivalent
            target_time = current_time + wait_time
        else:
            # Pay token with one token
            self._consume_token(state, tokens)
            target_time = current_time
        state["last_refill_time"] = target_time
        return target_time

    def _acquire_token_with_wait(self, timeout: Optional[float] = None) -> float:
        """
        Acquire a token from the bucket, waiting if necessary.

        This method implements the token bucket algorithm using a reservation system:
        1. Acquire lock and reserve a slot (updating last_refill_time)
        2. Release lock
        3. Sleep until the reserved time
        4. Proceed

        This prevents race conditions while avoiding lock contention during sleep.

        The token bucket algorithm works by:
        1. Adding tokens to the bucket at a constant rate (the refill rate)
        2. When a request arrives, it takes a token from the bucket if one is available
        3. If no tokens are available, the request must wait until a token becomes available
        4. The bucket has a maximum capacity to limit bursts

        Args:
            timeout: Maximum time in seconds to wait for a token (None for no timeout)

        Returns:
            float: Time waited in seconds (0 if proceeded immediately)

        Raises:
            RateLimitTimeout: If timeout is set and wait time exceeds it
        """
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        current_time = time.time()

        # Reserve a slot while holding the lock
        with self.shared_state.locked_dict() as state:
            self._initialize_state(state, current_time)
            last_refill_time = state["last_refill_time"]
            current_wait = last_refill_time - current_time
            if current_wait > 0:
              # There are reserved slots. No tokens available.
              tokens = 0
              wait_time = current_wait + self._calculate_wait_time(tokens)
            else:
              tokens = self._refill_tokens(state["tokens"], last_refill_time, current_time)
              wait_time = self._calculate_wait_time(tokens)

            # Check timeout before consuming token or reserving slot
            if timeout is not None and wait_time > timeout:
                raise RateLimitTimeout(self.id, timeout, wait_time)

            target_time = self._reserve_slot_and_get_target_time(state, wait_time, current_time, tokens)

        # Sleep outside the lock until our reserved time
        if wait_time > 0:
            actual_wait = target_time - time.time()
            if actual_wait > 0:
                logger.debug(
                    f"Token bucket rate limiter {self.id} waiting for {actual_wait:.2f} seconds"
                )
                time.sleep(actual_wait)

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

    def _check_max_calls(self, call_count: int, state_snapshot: Dict[str, Any]) -> None:
        """Check if max_calls limit has been reached and invoke callback if configured."""
        if self.max_calls > 0 and call_count >= self.max_calls:
            logger.info(
                f"Rate limiter {self.shared_state.name} reached max_calls limit of {self.max_calls}"
            )
            if self.on_max_calls_callback:
                event = MaxCallsEvent(
                    limiter_id=self.shared_state.name,
                    limiter=self,
                    state_snapshot=state_snapshot,
                    max_calls=self.max_calls,
                )
                self.on_max_calls_callback(event)


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

        _limiter: "TokenBucketRateLimiter"
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

        This allows using the rate limiter with cleaner syntax:
            with pacer():
                ...

        Args:
            timeout: Maximum time in seconds to wait for a token (None for no timeout)

        Returns:
            Context manager for rate limiting

        Example:
            with pacer() as ctx:
                print(f"Call count: {ctx.call_count}")
                perform_action()

            with pacer(timeout=5.0) as ctx:
                print(f"Will timeout after 5 seconds")
                perform_action()
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
        # Acquire token with wait if necessary
        # NOTE: The sleep happens inside _acquire_token_with_wait() while holding the lock
        # to prevent race conditions where multiple workers see the same initial state
        wait_time = self._acquire_token_with_wait(timeout=timeout)

        # Update call count and check rate
        call_count, state_snapshot = self._increment_call_count_and_check_rate()
        context = self.RateLimitContext(self, state_snapshot, seconds_waited=wait_time)

        try:
            yield context
        except Exception:
            self._track_exception()
            raise
        finally:
            self._check_max_calls(call_count, state_snapshot)

