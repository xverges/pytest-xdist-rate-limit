"""Conftest for examples to ensure fixtures work with xdist."""

from pytest_xdist_rate_limit.concurrent_fixtures import (
    rate_limiter_fixture_factory,
    shared_json_fixture_factory,
)

# Re-export the fixtures so they're available in examples
__all__ = ["shared_json_fixture_factory", "rate_limiter_fixture_factory"]
