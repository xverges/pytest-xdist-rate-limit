"""
Rate limit configuration.

This module defines the rate limit configuration class with convenient
factory methods for different time units.
"""
from __future__ import annotations

from typing import Union


class Rate:
    """
    Represents a rate limit with convenient factory methods for different time units.

    Examples:
        >>> rate = Rate.per_second(10)  # 10 calls per second
        >>> rate = Rate.per_minute(600)  # 600 calls per minute
        >>> rate = Rate.per_hour(3600)  # 3600 calls per hour
        >>> rate = Rate.per_day(86400)  # 86400 calls per day
    """

    def __init__(self, calls_per_hour: int):
        if calls_per_hour <= 0:
            raise ValueError("calls_per_hour must be positive")
        self._calls_per_hour = calls_per_hour

    @property
    def calls_per_hour(self) -> int:
        return self._calls_per_hour

    @classmethod
    def per_second(cls, calls: Union[int, float]) -> Rate:
        return cls(int(calls * 3600))

    @classmethod
    def per_minute(cls, calls: Union[int, float]) -> Rate:
        return cls(int(calls * 60))

    @classmethod
    def per_hour(cls, calls: int) -> Rate:
        return cls(calls)

    @classmethod
    def per_day(cls, calls: Union[int, float]) -> Rate:
        return cls(int(calls / 24))

    def __repr__(self) -> str:
        return f"Rate({self._calls_per_hour} calls/hour)"


# Backward compatibility alias
RateLimit = Rate
