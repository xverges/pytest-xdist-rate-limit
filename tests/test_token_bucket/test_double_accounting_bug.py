"""
Simple regression test for double accounting bug.

This test uses sequential calls (not concurrent) to clearly demonstrate
the bug where token debt is paid twice.
"""


def test_sequential_calls_total_time(pytester, run_with_timeout):
    """
    Test that sequential calls take the expected total time.
    
    With 1 call/sec rate and burst=1:
    - Call 1: 0s (uses burst)
    - Call 2: ~1s (waits for 1 token)
    - Call 3: ~1s (waits for 1 token)
    Total: ~2s
    
    With the bug (double accounting), the total time would be longer
    because debt is counted twice.
    """
    pytester.makepyfile(
        """
        import time
        from pytest_xdist_rate_limit import (
            TokenBucketRateLimiter,
            RateLimit
        )

        def test_sequential_timing(make_shared_json):
            shared = make_shared_json(name="sequential_test")
            limiter = TokenBucketRateLimiter(
                shared_state=shared,
                hourly_rate=RateLimit.per_second(1),  # 1 call per second
                burst_capacity=1,
                max_drift=1.0,
                num_calls_between_checks=1000,
                seconds_before_first_check=1000.0,
            )

            start_time = time.time()
            
            # Make 3 sequential calls
            with limiter() as ctx:
                wait1 = ctx.seconds_waited
                
            with limiter() as ctx:
                wait2 = ctx.seconds_waited
                
            with limiter() as ctx:
                wait3 = ctx.seconds_waited
            
            total_elapsed = time.time() - start_time
            
            # Expected: ~2 seconds total (call 1 is immediate, calls 2-3 wait 1s each)
            # With bug: would be longer due to double accounting
            assert total_elapsed >= 1.9, f"Total time {total_elapsed:.2f}s is too short"
            assert total_elapsed <= 2.3, f"Total time {total_elapsed:.2f}s is too long (indicates bug)"
            
            # Verify individual wait times
            assert wait1 < 0.1, f"First call should not wait, got {wait1:.2f}s"
            assert 0.9 <= wait2 <= 1.1, f"Second call should wait ~1s, got {wait2:.2f}s"
            assert 0.9 <= wait3 <= 1.1, f"Third call should wait ~1s, got {wait3:.2f}s"
        """
    )
    
    result = run_with_timeout(pytester, "-v", timeout=10)
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, (
        f"Test should pass with fixed code. Outcomes: {outcomes}\\n{result.stdout}"
    )
