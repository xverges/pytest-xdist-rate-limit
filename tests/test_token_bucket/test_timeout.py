"""Tests for TokenBucketPacer timeout functionality."""

def test_timeout_not_exceeded(pytester, run_with_timeout):
    """Test that timeout is not raised when wait time is within limit."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate,
            RateLimitTimeout
        )

        def test_no_timeout(make_shared_json):
            shared = make_shared_json(name="no_timeout_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(2),  # 2 calls per second
                burst_capacity=1
            )

            # First call should not wait (burst available)
            with limiter(timeout=2.0) as ctx:
                assert ctx.call_count == 1
                assert ctx.seconds_waited == 0.0

            # Second call should wait ~0.5s, which is within 2s timeout
            with limiter(timeout=2.0) as ctx:
                assert ctx.call_count == 2
                assert ctx.seconds_waited > 0.4
                assert ctx.seconds_waited < 0.7
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_exceeded(pytester, run_with_timeout):
    """Test that RateLimitTimeout is raised when wait time exceeds timeout."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate,
            RateLimitTimeout
        )

        def test_timeout_exceeded(make_shared_json):
            shared = make_shared_json(name="timeout_exceeded_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1),  # 1 call per second
                burst_capacity=1
            )

            # First call should not wait (burst available)
            with limiter() as ctx:
                assert ctx.call_count == 1

            # Second call would need to wait ~1s, which exceeds 0.3s timeout
            with pytest.raises(RateLimitTimeout) as exc_info:
                with limiter(timeout=0.3):
                    pass

            # Verify exception details
            error = exc_info.value
            assert error.limiter_id == "timeout_exceeded_test"
            assert error.timeout == 0.3
            assert error.required_wait > 0.9
            assert error.required_wait < 1.2
            assert "timeout of 0.3s exceeded" in str(error)
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_none_allows_unlimited_wait(pytester, run_with_timeout):
    """Test that timeout=None allows unlimited waiting."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate
        )

        def test_no_timeout_limit(make_shared_json):
            shared = make_shared_json(name="unlimited_wait_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1),
                burst_capacity=1
            )

            # First call uses burst
            with limiter() as ctx:
                assert ctx.call_count == 1

            # Second call should wait ~1s without raising timeout error (no timeout specified)
            with limiter() as ctx:
                assert ctx.call_count == 2
                assert ctx.seconds_waited > 0.9
        """
    )
    result = run_with_timeout(pytester, "-n", "2", "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_validation(pytester, run_with_timeout):
    """Test that invalid timeout values are rejected."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate
        )

        def test_negative_timeout(make_shared_json):
            shared = make_shared_json(name="negative_timeout_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1)
            )

            with pytest.raises(ValueError, match="timeout must be positive"):
                with limiter(timeout=-1.0):
                    pass

        def test_zero_timeout(make_shared_json):
            shared = make_shared_json(name="zero_timeout_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1)
            )

            with pytest.raises(ValueError, match="timeout must be positive"):
                with limiter(timeout=0.0):
                    pass
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 2, str(result.stdout)


def test_timeout_with_burst_capacity(pytester, run_with_timeout):
    """Test timeout behavior with different burst capacities."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate,
            RateLimitTimeout
        )

        def test_burst_then_timeout(make_shared_json):
            shared = make_shared_json(name="burst_timeout_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1),
                burst_capacity=3  # Allow 3 immediate calls
            )

            # First 3 calls should use burst (no wait)
            for i in range(3):
                with limiter(timeout=0.5) as ctx:
                    assert ctx.call_count == i + 1
                    assert ctx.seconds_waited == 0.0

            # Fourth call would need to wait ~1s, exceeding 0.5s timeout
            with pytest.raises(RateLimitTimeout) as exc_info:
                with limiter(timeout=0.5):
                    pass

            error = exc_info.value
            assert error.timeout == 0.5
            assert error.required_wait > 0.9
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)


def test_timeout_with_concurrent_workers(pytester, run_with_timeout):
    """Test timeout behavior with multiple xdist workers."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate,
            RateLimitTimeout
        )

        @pytest.fixture(scope="session")
        def rate_limiter(make_shared_json):
            shared = make_shared_json(name="concurrent_timeout_test")
            return TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(2),
                burst_capacity=2
            )

        def test_worker_1(rate_limiter):
            # May or may not timeout depending on execution order
            try:
                with rate_limiter(timeout=1.0) as ctx:
                    assert ctx.call_count >= 1
            except RateLimitTimeout:
                pass  # Expected if other workers consumed tokens

        def test_worker_2(rate_limiter):
            try:
                with rate_limiter(timeout=1.0) as ctx:
                    assert ctx.call_count >= 1
            except RateLimitTimeout:
                pass

        def test_worker_3(rate_limiter):
            try:
                with rate_limiter(timeout=1.0) as ctx:
                    assert ctx.call_count >= 1
            except RateLimitTimeout:
                pass
        """
    )
    result = run_with_timeout(pytester, "-n", "3", "-v")
    outcomes = result.parseoutcomes()
    # All tests should pass (either successfully or by catching timeout)
    assert "passed" in outcomes and outcomes["passed"] == 3, str(result.stdout)


def test_timeout_error_attributes(pytester, run_with_timeout):
    """Test that RateLimitTimeout has correct attributes."""
    pytester.makepyfile(
        """
        import pytest
        from pytest_xdist_rate_limit import (
            TokenBucketPacer,
            Rate,
            RateLimitTimeout
        )

        def test_error_attributes(make_shared_json):
            shared = make_shared_json(name="error_attrs_test")
            limiter = TokenBucketPacer(
                shared_state=shared,
                hourly_rate=Rate.per_second(1),
                burst_capacity=1
            )

            # Consume burst
            with limiter():
                pass

            # Trigger timeout
            try:
                with limiter(timeout=0.2):
                    pass
                assert False, "Should have raised RateLimitTimeout"
            except RateLimitTimeout as e:
                # Verify all attributes are present and correct
                assert hasattr(e, 'limiter_id')
                assert hasattr(e, 'timeout')
                assert hasattr(e, 'required_wait')

                assert e.limiter_id == "error_attrs_test"
                assert e.timeout == 0.2
                assert e.required_wait > 0.9
                assert e.required_wait < 1.2

                # Verify error message format
                error_msg = str(e)
                assert "error_attrs_test" in error_msg
                assert "0.2s" in error_msg
                assert "exceeded" in error_msg
        """
    )
    result = run_with_timeout(pytester, "-v")
    outcomes = result.parseoutcomes()
    assert "passed" in outcomes and outcomes["passed"] == 1, str(result.stdout)

