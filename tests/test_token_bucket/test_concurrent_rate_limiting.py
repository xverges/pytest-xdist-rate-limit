"""
Tests for concurrent rate limiting behavior.

These tests verify that the token bucket rate limiter properly enforces
rate limits when multiple threads/processes are competing for tokens.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from pytest_xdist_rate_limit import (
    RateLimit,
    SharedJson,
    TokenBucketRateLimiter,
)


def test_concurrent_workers_respect_rate_limit(tmp_path):
    """
    Test that multiple concurrent workers properly respect the rate limit.

    This test verifies the fix for the bug where multiple threads could
    calculate wait times based on the same token state, leading to rate
    limit violations.

    With the old buggy code, this test would fail because multiple threads
    would see the same token state and all proceed after the same wait time.

    With the fix, tokens are consumed immediately (even going negative),
    ensuring proper serialization.
    """
    # Create a rate limiter with 1 call per second and burst capacity of 1
    data_file = tmp_path / "concurrent_test.json"
    lock_file = tmp_path / "concurrent_test.lock"
    shared_state = SharedJson(
        data_file=data_file,
        lock_file=lock_file,
    )

    limiter = TokenBucketRateLimiter(
        shared_state=shared_state,
        hourly_rate=RateLimit.per_second(1),  # 1 call per second
        burst_capacity=1,  # No burst allowance
        max_drift=0.5,
        num_calls_between_checks=1000,
        seconds_before_first_check=100.0,
    )

    # Track execution times
    execution_times = []

    def make_call():
        """Make a rate-limited call and record the time."""
        with limiter.rate_limited_context():
            execution_times.append(time.time())

    # Run 5 calls concurrently with 2 workers
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(make_call) for _ in range(5)]
        for future in futures:
            future.result()

    elapsed = time.time() - start_time

    # With 1 call/second rate limit, 5 calls should take at least 4 seconds
    # (first call is immediate, then 4 more calls at 1/second)
    assert elapsed >= 4.0, (
        f"Expected at least 4 seconds for 5 calls at 1/sec rate, but took only {elapsed:.2f}s"
    )

    # Verify calls were properly spaced
    # Sort execution times
    execution_times.sort()

    # Check spacing between consecutive calls
    for i in range(1, len(execution_times)):
        gap = execution_times[i] - execution_times[i - 1]
        # Each gap should be at least 0.9 seconds (allowing small timing variance)
        assert gap >= 0.9, (
            f"Gap between call {i - 1} and {i} was only {gap:.2f}s, expected at least 0.9s"
        )


def test_concurrent_workers_with_burst_capacity(tmp_path):
    """
    Test that burst capacity allows initial rapid calls, then enforces rate limit.
    """
    data_file = tmp_path / "burst_test.json"
    lock_file = tmp_path / "burst_test.lock"
    shared_state = SharedJson(
        data_file=data_file,
        lock_file=lock_file,
    )

    limiter = TokenBucketRateLimiter(
        shared_state=shared_state,
        hourly_rate=RateLimit.per_second(1),  # 1 call per second
        burst_capacity=3,  # Allow 3 rapid calls
        max_drift=0.5,
        num_calls_between_checks=1000,
        seconds_before_first_check=100.0,
    )

    execution_times = []

    def make_call():
        with limiter.rate_limited_context():
            execution_times.append(time.time())

    # Run 5 calls concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(make_call) for _ in range(5)]
        for future in futures:
            future.result()

    execution_times.sort()

    # First 3 calls should be rapid (using burst capacity)
    first_three_duration = execution_times[2] - execution_times[0]
    assert first_three_duration < 0.5, (
        f"First 3 calls should be rapid, but took {first_three_duration:.2f}s"
    )

    # Calls 4 and 5 should be rate-limited
    # They should take at least 1 second each after the burst
    gap_3_to_4 = execution_times[3] - execution_times[2]
    gap_4_to_5 = execution_times[4] - execution_times[3]

    assert gap_3_to_4 >= 0.9, (
        f"Gap from call 3 to 4 was only {gap_3_to_4:.2f}s, expected ~1s"
    )
    assert gap_4_to_5 >= 0.9, (
        f"Gap from call 4 to 5 was only {gap_4_to_5:.2f}s, expected ~1s"
    )


def test_negative_tokens_prevent_race_condition(tmp_path):
    """
    Test that the fix properly prevents the race condition by allowing negative tokens.

    This test specifically targets the bug where multiple threads could see
    the same positive token count and all calculate the same wait time.
    """
    data_file = tmp_path / "negative_tokens_test.json"
    lock_file = tmp_path / "negative_tokens_test.lock"
    shared_state = SharedJson(
        data_file=data_file,
        lock_file=lock_file,
    )

    limiter = TokenBucketRateLimiter(
        shared_state=shared_state,
        hourly_rate=RateLimit.per_second(2),  # 2 calls per second
        burst_capacity=1,  # Only 1 token available initially
        max_drift=0.5,
        num_calls_between_checks=1000,
        seconds_before_first_check=100.0,
    )

    call_count = [0]

    def make_call():
        with limiter.rate_limited_context():
            call_count[0] += 1

    # Launch 4 calls simultaneously
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(make_call) for _ in range(4)]
        for future in futures:
            future.result()

    elapsed = time.time() - start_time

    # With 2 calls/second and 4 calls:
    # - Call 1: immediate (uses burst token)
    # - Call 2: waits 0.5s (token debt of -1)
    # - Call 3: waits 1.0s (token debt of -2)
    # - Call 4: waits 1.5s (token debt of -3)
    # Total time should be at least 1.5 seconds
    assert elapsed >= 1.4, (
        f"Expected at least 1.4 seconds for 4 calls at 2/sec rate with burst=1, but took only {elapsed:.2f}s"
    )

    assert call_count[0] == 4, f"Expected 4 calls, got {call_count[0]}"
