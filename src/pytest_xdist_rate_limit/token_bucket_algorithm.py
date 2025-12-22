"""
Token Bucket Algorithm

This module implements the core token bucket rate limiting algorithm.
The algorithm allows for controlled bursts of activity while maintaining
an average rate limit.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from pytest_xdist_rate_limit.exceptions import RateLimitTimeout

logger = logging.getLogger(__name__)


class TokenBucketAlgorithm:
    """
    Implements the token bucket algorithm for rate limiting.

    The token bucket algorithm works by:
    1. Adding tokens to the bucket at a constant rate (the refill rate)
    2. When a request arrives, it takes a token from the bucket if one is available
    3. If no tokens are available, the request must wait until a token becomes available
    4. The bucket has a maximum capacity to limit bursts

    Attributes:
        hourly_rate: Target rate in calls per hour
        burst_capacity: Maximum number of tokens that can be stored
    """

    def __init__(self, hourly_rate: int, burst_capacity: int):
        """
        Initialize the token bucket algorithm.

        Args:
            hourly_rate: Target rate in calls per hour
            burst_capacity: Maximum number of tokens that can be stored in the bucket
        """
        self.hourly_rate = hourly_rate
        self.burst_capacity = burst_capacity

    def _initialize_state(self, current_time: float) -> Dict[str, Any]:
        """Return initial algorithm state (no mutation).

        Args:
            current_time: Current Unix timestamp

        Returns:
            Dict containing initial algorithm state
        """
        return {
            "last_refill_time": current_time,
            "tokens": self.burst_capacity,
        }

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


    def reserve_token_slot(
        self,
        algorithm_state: Optional[Dict[str, Any]],
        limiter_id: str,
        timeout: Optional[float] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Reserve a token slot using algorithm state.

        Does not mutate the input state.
        It returns updated algorithm state via return value.

        Args:
            algorithm_state: Algorithm state dict or None if uninitialized
            limiter_id: Identifier for error messages
            timeout: Maximum wait time in seconds (None for no timeout)

        Returns:
            Tuple[float, float, Dict[str, Any]]: (wait_time, target_time, updated_algorithm_state)

        Raises:
            RateLimitTimeout: If timeout is set and wait time exceeds it
        """
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        current_time = time.time()

        if algorithm_state is None:
            algorithm_state = self._initialize_state(current_time)

        # Work with copy to avoid mutation
        state = dict(algorithm_state)

        last_refill_time = state["last_refill_time"]
        current_wait = last_refill_time - current_time

        if current_wait > 0:
            # There are reserved slots. No tokens available.
            tokens = 0
            wait_time = current_wait + self._calculate_wait_time(tokens)
        else:
            tokens = self._refill_tokens(state["tokens"], last_refill_time, current_time)
            wait_time = self._calculate_wait_time(tokens)

        # Check timeout before reserving slot
        if timeout is not None and wait_time > timeout:
            raise RateLimitTimeout(limiter_id, timeout, wait_time)

        # Update state
        if wait_time > 0:
            # Pay token with its wait time equivalent
            target_time = current_time + wait_time
        else:
            # Pay token with one token (consume immediately)
            state["tokens"] = tokens - 1
            target_time = current_time

        state["last_refill_time"] = target_time

        return wait_time, target_time, state
