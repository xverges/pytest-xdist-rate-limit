"""Tests for RateLimitContext.seconds_waited field."""


def test_seconds_waited_no_wait(pytester, run_with_timeout):
    """Test that seconds_waited is 0 when no waiting occurs."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate
        )

        def test_no_wait(make_shared_json):
            shared = make_shared_json(name="no_wait_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(10),
                burst_capacity=5
            )

            # First call should not wait (burst capacity available)
            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0, f"Expected 0 wait, got {ctx.seconds_waited}"
                assert ctx.call_count == 1
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_seconds_waited_with_wait(pytester, run_with_timeout):
    """Test that seconds_waited reflects actual wait time."""
    pytester.makepyfile(
        """
        import time
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate
        )

        def test_with_wait(make_shared_json):
            shared = make_shared_json(name="wait_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1),
                burst_capacity=2
            )

            # First two calls use burst capacity (no wait)
            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0
                assert ctx.call_count == 1

            with limiter() as ctx:
                assert ctx.seconds_waited == 0.0
                assert ctx.call_count == 2

            # Third call should wait approximately 1 second
            with limiter() as ctx:
                assert ctx.seconds_waited > 0.9, f"Expected ~1s wait, got {ctx.seconds_waited}s"
                assert ctx.seconds_waited < 1.2, f"Wait time too long: {ctx.seconds_waited}s"
                assert ctx.call_count == 3
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)

