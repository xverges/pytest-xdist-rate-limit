"""
Pacer Event Classes

This module defines event classes used by the token bucket pacer
for callbacks and monitoring.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastdigest import TDigest

if TYPE_CHECKING:
    from pytest_xdist_rate_limit.token_bucket_rate_limiter import TokenBucketPacer


@dataclass
class PacerEvent:
    """Base class for all pacer events.

    Provides common context available to all callback events.

    Attributes:
        limiter_id: Unique identifier for the pacer
        limiter: Reference to the TokenBucketPacer instance
        state_snapshot: Snapshot of shared state at the time of the event
    """
    limiter_id: str
    limiter: TokenBucketPacer
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
class DriftEvent(PacerEvent):
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
class MaxCallsEvent(PacerEvent):
    """Event fired when the max_calls limit is reached.

    Attributes:
        max_calls: Maximum number of calls allowed (from configuration)
    """
    max_calls: int


@dataclass
class PeriodicCheckEvent(PacerEvent):
    """Event fired during periodic checks with current metrics.

    Provides comprehensive distribution-based statistics for load test analysis and
    bottleneck detection. Uses TDigest for accurate percentile calculations without
    storing all samples.

    Attributes:
        worker_count: Number of workers detected from environment
        duration_digest: TDigest of call durations (None if insufficient data)
        wait_digest: TDigest of wait times (None if insufficient data)
        windowed_rates: Rates for configured time windows in seconds (e.g., {60: 3500, 300: 3450})
        sample_count: Total samples in digests
        target_rate: Target rate in calls/hour (from configuration)
        current_rate: Current actual rate in calls/hour
        drift: Drift as a fraction of target rate (None if insufficient data)
    """
    worker_count: int
    duration_digest: Optional[TDigest]
    wait_digest: Optional[TDigest]
    windowed_rates: Dict[int, float]
    sample_count: int
    target_rate: float
    current_rate: float
    drift: Optional[float]

    @property
    def duration_p50(self) -> Optional[float]:
        """Median call duration in seconds."""
        return self.duration_digest.percentile(50) if self.duration_digest else None

    @property
    def duration_p90(self) -> Optional[float]:
        """90th percentile call duration in seconds."""
        return self.duration_digest.percentile(90) if self.duration_digest else None

    @property
    def duration_p99(self) -> Optional[float]:
        """99th percentile call duration in seconds."""
        return self.duration_digest.percentile(99) if self.duration_digest else None

    @property
    def wait_p50(self) -> Optional[float]:
        """Median wait time in seconds."""
        return self.wait_digest.percentile(50) if self.wait_digest else None

    @property
    def wait_p90(self) -> Optional[float]:
        """90th percentile wait time in seconds."""
        return self.wait_digest.percentile(90) if self.wait_digest else None

    @property
    def wait_p99(self) -> Optional[float]:
        """99th percentile wait time in seconds."""
        return self.wait_digest.percentile(99) if self.wait_digest else None

    @property
    def wait_ratio(self) -> Optional[float]:
        """Ratio of median wait time to median call duration.

        This metric reveals whether your pacer (traffic generator) is constraining
        throughput or if the System Under Test (SUT) is the limiting factor.

        Interpretation:
        - **Low ratio (< 0.1)**: SUT-bound operation
          * Tests spend 10x more time executing than waiting for pacer
          * The pacer is not constraining throughput - SUT capacity may be a bottleneck

        - **High ratio (> 1.0)**: Pacer-bound operation
          * Tests spend more time waiting for pacer than executing
          * SUT is fast relative to the pacing rate
          * SUT can handle higher rates; increase pace if more load needed

        Use this metric to tune your load testing: high ratio means you can push harder;
        low ratio means you've found the SUT's capacity limit.
        """
        if self.duration_p50 and self.wait_p50 and self.duration_p50 > 0:
            return self.wait_p50 / self.duration_p50
        return None

    def __str__(self) -> str:
        """Format periodic check event as a debug message."""
        parts = [
            f"Periodic check for {self.limiter_id}:",
            f"workers={self.worker_count}",
            f"samples={self.sample_count}",
        ]

        if self.duration_p50 is not None:
            parts.append(f"duration_p50={self.duration_p50:.3f}s")
        if self.wait_p50 is not None:
            parts.append(f"wait_p50={self.wait_p50:.3f}s")
        if self.wait_ratio is not None:
            parts.append(f"wait_ratio={self.wait_ratio:.2f}")

        parts.append(f"current_rate={self.current_rate:.0f}/hr")

        if self.drift is not None:
            parts.append(f"drift={self.drift:.2%}")
        else:
            parts.append("drift=N/A")

        return " ".join(parts)
