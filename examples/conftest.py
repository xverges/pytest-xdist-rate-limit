"""Conftest for examples to ensure fixtures work with xdist."""

from pytest_xdist_rate_limit.concurrent_fixtures import (
    make_rate_limiter,
    make_shared_json,
)

# Re-export the fixtures so they're available in examples
__all__ = ["make_shared_json", "make_rate_limiter"]
