"""pytest-xdist-rate-limit plugin registration."""

import pytest


def pytest_configure(config: pytest.Config):
    """Register the fixture modules to expose their fixtures."""
    from . import rate_limiter_fixture, shared_json

    if not config.pluginmanager.is_registered(shared_json):
        config.pluginmanager.register(
            shared_json, name="pytest_xdist_rate_limit_shared_json"
        )

    if not config.pluginmanager.is_registered(rate_limiter_fixture):
        config.pluginmanager.register(
            rate_limiter_fixture, name="pytest_xdist_rate_limit_rate_limiter"
        )

