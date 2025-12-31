"""
Rate Monitor

This module provides monitoring functionality for the rate limiter,
including drift detection, periodic metrics callbacks, and max calls monitoring.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from pytest_xdist_rate_limit.events import DriftEvent, MaxCallsEvent, PeriodicCheckEvent

if TYPE_CHECKING:
    from pytest_xdist_rate_limit.pacer_metrics import PacerMetrics
    from pytest_xdist_rate_limit.token_bucket_rate_limiter import TokenBucketPacer

logger = logging.getLogger(__name__)

# Constants
SECONDS_PER_HOUR = 3600


class RateMonitor:
    """
    Monitors rate limiter performance and coordinates callback invocations.

    Handles drift detection, periodic metrics checks, and max calls monitoring,
    providing a centralized location for all monitoring and callback logic.

    Attributes:
        max_drift: Maximum allowed drift from the expected rate (as a fraction)
        seconds_before_first_check: Minimum elapsed time before rate checking begins
        on_drift_callback: Callback function to execute when drift exceeds max_drift
        on_periodic_check_callback: Callback function for periodic metrics checks
        on_max_calls_callback: Callback function to execute when max_calls is reached
    """

    def __init__(
        self,
        max_drift: float,
        seconds_before_first_check: float,
        on_drift_callback: Optional[Callable[[DriftEvent], None]] = None,
        on_periodic_check_callback: Optional[Callable[[PeriodicCheckEvent], None]] = None,
        on_max_calls_callback: Optional[Callable[[MaxCallsEvent], None]] = None,
    ):
        """
        Initialize the rate monitor.

        Args:
            max_drift: Maximum allowed drift from the expected rate (as a fraction)
            seconds_before_first_check: Minimum elapsed time before rate checking begins
            on_drift_callback: Callback function to execute when drift exceeds max_drift
            on_periodic_check_callback: Callback function for periodic metrics checks
            on_max_calls_callback: Callback function to execute when max_calls is reached
        """
        self.max_drift = max_drift
        self.seconds_before_first_check = seconds_before_first_check
        self.on_drift_callback = on_drift_callback
        self.on_periodic_check_callback = on_periodic_check_callback
        self.on_max_calls_callback = on_max_calls_callback

    def check_rate(
        self,
        state: Dict[str, Any],
        limiter_id: str,
        target_rate: float,
        limiter: TokenBucketPacer
    ) -> None:
        """Check if the current rate is within acceptable limits.

        Args:
            state: Shared state dictionary
            limiter_id: Identifier for the rate limiter
            target_rate: Target rate in calls per hour
            limiter: Reference to the TokenBucketPacer instance
        """
        current_time = time.time()
        elapsed_time = current_time - state["start_time"]

        # Only check if we have enough data
        if elapsed_time < self.seconds_before_first_check:
            return

        current_rate = self._calculate_current_rate(state["call_count"], elapsed_time)
        drift = self._calculate_drift(current_rate, target_rate)

        self._log_rate_check(limiter_id, current_rate, target_rate, drift, state)

        if drift > self.max_drift:
            self._handle_drift_violation(
                limiter_id, current_rate, target_rate, drift, state, limiter
            )

    def _calculate_current_rate(self, call_count: int, elapsed_time: float) -> float:
        """Calculate current rate in calls per hour.

        Args:
            call_count: Number of calls made
            elapsed_time: Time elapsed in seconds

        Returns:
            Current rate in calls per hour
        """
        return (call_count / elapsed_time) * SECONDS_PER_HOUR

    def _calculate_drift(self, current_rate: float, target_rate: float) -> float:
        """Calculate drift as a fraction of the target rate.

        Args:
            current_rate: Current rate in calls per hour
            target_rate: Target rate in calls per hour

        Returns:
            Drift as a fraction (0.0 to inf)
        """
        if target_rate > 0:
            return abs(current_rate - target_rate) / target_rate
        return 0 if current_rate == 0 else float("inf")

    def _log_rate_check(
        self,
        limiter_id: str,
        current_rate: float,
        target_rate: float,
        drift: float,
        state: Dict[str, Any]
    ) -> None:
        """Log rate check information.

        Args:
            limiter_id: Identifier for the rate limiter
            current_rate: Current rate in calls per hour
            target_rate: Target rate in calls per hour
            drift: Calculated drift fraction
            state: Shared state dictionary
        """
        logger.info(
            f"Rate check for {limiter_id}: current={current_rate:.2f}/hr, "
            f"target={target_rate}/hr, drift={drift:.2%}. "
            f"Total calls: {state['call_count']}. Exceptions: {state['exceptions']}"
        )

    def _handle_drift_violation(
        self,
        limiter_id: str,
        current_rate: float,
        target_rate: float,
        drift: float,
        state: Dict[str, Any],
        limiter: TokenBucketPacer
    ) -> None:
        """Handle drift violation by logging and invoking callback.

        Args:
            limiter_id: Identifier for the rate limiter
            current_rate: Current rate in calls per hour
            target_rate: Target rate in calls per hour
            drift: Calculated drift fraction
            state: Shared state dictionary
            limiter: Reference to the TokenBucketPacer instance
        """
        message = (
            f"Rate drift for {limiter_id} exceeds maximum allowed: "
            f"current={current_rate:.2f}/hr, target={target_rate}/hr, "
            f"drift={drift:.2%} (max allowed: {self.max_drift:.2%})"
        )
        logger.error(message)

        if self.on_drift_callback:
            event = DriftEvent(
                limiter_id=limiter_id,
                limiter=limiter,
                state_snapshot=dict(state),
                current_rate=current_rate,
                target_rate=target_rate,
                drift=drift,
                max_drift=self.max_drift,
            )
            self.on_drift_callback(event)

    def periodic_check(
        self,
        state: Dict[str, Any],
        stats_state: Dict[str, Any],
        limiter_id: str,
        target_rate: float,
        limiter: TokenBucketPacer,
        metrics: PacerMetrics
    ) -> None:
        """Perform periodic check and invoke callback with current metrics.

        Retrieves TDigest distributions for call durations and wait times,
        calculates windowed rates, and provides comprehensive statistics
        for bottleneck analysis.

        Args:
            state: Shared state dictionary
            stats_state: Statistics state dictionary
            limiter_id: Identifier for the rate limiter
            target_rate: Target rate in calls per hour
            limiter: Reference to the TokenBucketPacer instance
            metrics: Metrics tracker instance for windowed rates
        """
        if not self.on_periodic_check_callback:
            return

        worker_count = int(os.getenv("PYTEST_XDIST_WORKER_COUNT", 1))

        # Delegate statistics extraction to PacerMetrics
        sample_count = metrics.get_sample_count(stats_state)
        duration_digest = metrics.get_duration_digest(stats_state, min_samples=10)
        wait_digest = metrics.get_wait_digest(stats_state, min_samples=10)
        windowed_rates = metrics.calculate_windowed_rates(stats_state)

        current_time = time.time()
        elapsed = current_time - state["start_time"]
        if elapsed > 0:
            current_rate = self._calculate_current_rate(state["call_count"], elapsed)
        else:
            current_rate = 0

        if elapsed >= self.seconds_before_first_check and target_rate > 0:
            drift = self._calculate_drift(current_rate, target_rate)
        else:
            drift = None

        event = PeriodicCheckEvent(
            limiter_id=limiter_id,
            limiter=limiter,
            state_snapshot=dict(state),
            worker_count=worker_count,
            duration_digest=duration_digest,
            wait_digest=wait_digest,
            windowed_rates=windowed_rates,
            sample_count=sample_count,
            target_rate=target_rate,
            current_rate=current_rate,
            drift=drift,
        )
        logger.debug(str(event))
        self.on_periodic_check_callback(event)

    def check_max_calls(
        self,
        call_count: int,
        max_calls: int,
        state_snapshot: Dict[str, Any],
        limiter_id: str,
        limiter: TokenBucketPacer
    ) -> None:
        """Check if max_calls limit has been reached and invoke callback if configured.

        Args:
            call_count: Current number of calls made
            max_calls: Maximum number of calls allowed
            state_snapshot: Snapshot of the current state
            limiter_id: Identifier for the rate limiter
            limiter: Reference to the TokenBucketPacer instance
        """
        if max_calls > 0 and call_count >= max_calls:
            logger.info(
                f"Rate limiter {limiter_id} reached max_calls limit of {max_calls}"
            )
            if self.on_max_calls_callback:
                event = MaxCallsEvent(
                    limiter_id=limiter_id,
                    limiter=limiter,
                    state_snapshot=state_snapshot,
                    max_calls=max_calls,
                )
                self.on_max_calls_callback(event)
