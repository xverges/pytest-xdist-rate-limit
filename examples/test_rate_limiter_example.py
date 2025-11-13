"""
Example: Rate limiting with automatic drift detection

Run with: pytest --tb=no -n 2 --load-test examples/test_rate_limiter_example.py

This demonstrates:
1. Using make_rate_limiter to make calls at a specific rate
2. Automatic rate drift detection across workers
3. Session exit when rate limits are violated
4. Shared state tracking for rate limiting
5. How entering the rate limiter context causes waiting when rate limit is reached

TEST_CODE:
```python
result = pytester.runpytest('--load-test', '-n', '2', '--tb', 'no')
result.stdout.fnmatch_lines([
    '*AssertionError: We expect ~10% of failures',
    '*Rate drift for fast_service exceeds maximum allowed*'
])
assert result.ret == pytest.ExitCode.INTERRUPTED

# Verify test_slow_api_demonstrates_waiting had no failures
assert 'test_slow_api_demonstrates_waiting FAILED' not in result.stdout.str()
```
"""

import random
import time

import pytest
from pytest_load_testing import stop_load_testing, weight

from pytest_xdist_rate_limit import RateLimit


class SystemUnderTest:
    @staticmethod
    def read():
        pass

    @staticmethod
    def write():
        pass

    @staticmethod
    def delete():
        pass


@pytest.fixture(scope="session")
def pacer(make_rate_limiter, request):
    """Rate limiter that exits session if rate drift exceeds 20%."""

    def on_drift(limiter_id, current_rate, target_rate, drift):
        """Exit session when drift exceeds threshold."""
        message = (
            f"Rate drift for {limiter_id} exceeds maximum allowed: "
            f"current={current_rate:.2f}/hr, target={target_rate}/hr, "
            f"drift={drift:.2%}"
        )
        stop_load_testing(request, message)

    return make_rate_limiter(
        name="fast_service",
        hourly_rate=RateLimit.per_second(1000),  # 10 calls per second
        burst_capacity=20,  # Allow bursts up to 20 calls
        max_drift=0.1,
        num_calls_between_checks=20,
        seconds_before_first_check=0.5,
        on_drift_callback=on_drift,
    )


@pytest.fixture(scope="session")
def throttle(make_rate_limiter):
    """Rate limiter with very low rate to demonstrate waiting behavior."""
    return make_rate_limiter(
        name="slow_service",
        hourly_rate=RateLimit.per_second(1),
        burst_capacity=1,
        max_drift=0.5,
        num_calls_between_checks=1000,
        seconds_before_first_check=1.0,
    )


@pytest.fixture
def should_pass():
    """Fixture that returns a function to check if a test should pass (90% success rate)."""

    def check(progress):
        return random.random() < 0.9 and progress.call_count != 1

    return check


@weight(80)
def test_api_read(pacer, should_pass):
    """60% - Simulates read API calls with rate limiting."""
    with pacer() as progress:
        SystemUnderTest.read()
        assert progress.call_count >= 1
        assert progress.id == "fast_service"
        is_passed = should_pass(progress)
    assert is_passed, "We expect ~10% of failures"


@weight(5)
def test_api_write(pacer, should_pass):
    """15% - Simulates write API calls with rate limiting."""
    with pacer() as progress:
        SystemUnderTest.write()
        assert progress.call_count >= 1
        assert progress.hourly_rate == 3600000
        passed = should_pass(progress)
    assert passed, "We expect ~10% of failures"


@weight(5)
def test_api_delete(pacer, should_pass):
    """5% - Simulates delete API calls with rate limiting."""
    with pacer() as progress:
        SystemUnderTest.delete()
        assert progress.call_count >= 1
        assert progress.exceptions == 0
        passed = should_pass(progress)
    assert passed, "We expect ~10% of failures"


@weight(10)
def test_slow_api_demonstrates_waiting(throttle):
    """Demonstrates how entering the rate limiter context causes waiting when tokens are exhausted."""
    with throttle() as progress:
        # Verify rate limiting: with 1 call/second rate, we shouldn't have more calls
        # than the elapsed time (in seconds) plus one (for burst capacity)
        elapsed_seconds = time.time() - progress.start_time
        max_expected_calls = elapsed_seconds + 1
        assert progress.call_count <= max_expected_calls, (
            f"Rate limit violated: {progress.call_count} calls in {elapsed_seconds:.2f}s "
            f"(max expected: {max_expected_calls:.0f})"
        )
