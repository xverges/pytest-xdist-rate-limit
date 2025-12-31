"""
Pacer Metrics

This module provides statistics tracking functionality for the pacer,
including TDigest-based percentile calculations and windowed rate tracking.
"""

import time
from typing import Any, Dict, List, Optional

from fastdigest import TDigest


class PacerMetrics:
    """
    Tracks comprehensive distribution-based statistics for pacer analysis.

    Uses TDigest for accurate percentile calculations without storing all samples,
    enabling efficient tracking of call durations, wait times, and windowed rates.

    Attributes:
        rate_windows: Time windows in seconds for rate calculation (e.g., [60, 300, 900])
    """

    def __init__(self, rate_windows: List[int]):
        """
        Initialize the pacer metrics.

        Args:
            rate_windows: Time windows in seconds for rate calculation
        """
        self.rate_windows = rate_windows

    def update_duration_stats(
        self,
        stats_state: Optional[Dict[str, Any]],
        duration: float
    ) -> Dict[str, Any]:
        """Return updated statistics state with new duration sample.

        TDigest provides accurate percentile estimates with O(1) space complexity,
        making it ideal for distributed systems where storing all samples is impractical.

        Args:
            stats_state: Statistics state dict or None if uninitialized
            duration: New call duration to incorporate (in seconds)

        Returns:
            Updated statistics state dict
        """
        if stats_state is None:
            stats_state = {
                "duration_digest": TDigest().to_dict(),
                "sample_count": 0
            }

        # Work with copy to avoid mutation
        state = dict(stats_state)

        # Deserialize, update, and re-serialize
        digest = TDigest.from_dict(state.get("duration_digest", TDigest().to_dict()))
        digest.update(duration)
        state["duration_digest"] = digest.to_dict()
        state["sample_count"] = state.get("sample_count", 0) + 1

        return state

    def update_wait_stats(
        self,
        stats_state: Optional[Dict[str, Any]],
        wait_time: float
    ) -> Dict[str, Any]:
        """Return updated statistics state with new wait time sample.

        Tracks time spent waiting for pacer tokens, enabling analysis of
        whether the system is SUT-bound (low wait times) or pacer-bound (high wait times).

        Args:
            stats_state: Statistics state dict or None if uninitialized
            wait_time: Time waited for token acquisition (in seconds)

        Returns:
            Updated statistics state dict
        """
        if stats_state is None:
            stats_state = {"wait_digest": TDigest().to_dict()}

        # Work with copy to avoid mutation
        state = dict(stats_state)

        # Deserialize, update, and re-serialize
        digest = TDigest.from_dict(state.get("wait_digest", TDigest().to_dict()))
        digest.update(wait_time)
        state["wait_digest"] = digest.to_dict()

        return state

    def calculate_windowed_rates(
        self,
        stats_state: Optional[Dict[str, Any]]
    ) -> Dict[int, float]:
        """Calculate rates for configured time windows (read-only).

        Uses a sliding window approach with timestamps to calculate accurate rates
        over different time periods (e.g., last 60s, 300s, 900s).

        Args:
            stats_state: Statistics state dict or None if uninitialized

        Returns:
            Dictionary mapping window size (seconds) to rate (calls/hour)
        """
        if stats_state is None or "call_timestamps" not in stats_state:
            return {window: 0.0 for window in self.rate_windows}

        timestamps = stats_state["call_timestamps"]
        current_time = time.perf_counter()
        rates = {}

        for window in self.rate_windows:
            # Count calls within this window
            cutoff_time = current_time - window
            calls_in_window = sum(1 for ts in timestamps if ts >= cutoff_time)

            # Calculate rate in calls/hour
            if window > 0:
                rates[window] = (calls_in_window / window) * 3600
            else:
                rates[window] = 0.0

        return rates

    def track_call_timestamp(
        self,
        stats_state: Optional[Dict[str, Any]],
        timestamp: float
    ) -> Dict[str, Any]:
        """Return updated statistics state with new timestamp.

        Maintains a sliding window of timestamps, removing old entries to prevent
        unbounded memory growth.

        Args:
            stats_state: Statistics state dict or None if uninitialized
            timestamp: Monotonic timestamp from time.perf_counter()

        Returns:
            Updated statistics state dict
        """
        if stats_state is None:
            stats_state = {"call_timestamps": []}

        # Work with copy to avoid mutation
        state = dict(stats_state)
        timestamps = list(state.get("call_timestamps", []))

        # Add timestamp
        timestamps.append(timestamp)

        # Remove timestamps older than the largest window
        if self.rate_windows:
            max_window = max(self.rate_windows)
            cutoff_time = timestamp - max_window
            # Keep only recent timestamps
            timestamps = [ts for ts in timestamps if ts >= cutoff_time]

        state["call_timestamps"] = timestamps
        return state

    def get_duration_digest(
        self,
        stats_state: Optional[Dict[str, Any]],
        min_samples: int = 10
    ) -> Optional[TDigest]:
        """Extract duration digest from statistics state if sufficient samples exist.

        Args:
            stats_state: Statistics state dict or None if uninitialized
            min_samples: Minimum number of samples required to return digest

        Returns:
            TDigest instance or None if insufficient samples
        """
        if stats_state is None:
            return None

        sample_count = stats_state.get("sample_count", 0)
        if "duration_digest" in stats_state and sample_count >= min_samples:
            return TDigest.from_dict(stats_state["duration_digest"])
        return None

    def get_wait_digest(
        self,
        stats_state: Optional[Dict[str, Any]],
        min_samples: int = 10
    ) -> Optional[TDigest]:
        """Extract wait digest from statistics state if sufficient samples exist.

        Args:
            stats_state: Statistics state dict or None if uninitialized
            min_samples: Minimum number of samples required to return digest

        Returns:
            TDigest instance or None if insufficient samples
        """
        if stats_state is None:
            return None

        sample_count = stats_state.get("sample_count", 0)
        if "wait_digest" in stats_state and sample_count >= min_samples:
            return TDigest.from_dict(stats_state["wait_digest"])
        return None

    def get_sample_count(
        self,
        stats_state: Optional[Dict[str, Any]]
    ) -> int:
        """Get the total number of samples in the statistics state.

        Args:
            stats_state: Statistics state dict or None if uninitialized

        Returns:
            Number of samples (0 if uninitialized)
        """
        if stats_state is None:
            return 0
        return stats_state.get("sample_count", 0)
