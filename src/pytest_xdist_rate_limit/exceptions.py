"""
Exceptions for the pacer.

This module defines exceptions used throughout the pacing system.
"""

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
