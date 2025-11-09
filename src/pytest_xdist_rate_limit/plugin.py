"""pytest-xdist-rate-limit plugin registration."""

import pytest


def pytest_configure(config: pytest.Config):
    """Register the concurrent_fixtures module to expose its fixtures."""
    from . import concurrent_fixtures

    if not config.pluginmanager.is_registered(concurrent_fixtures):
        config.pluginmanager.register(
            concurrent_fixtures, name="pytest_xdist_rate_limit_fixtures"
        )

