import pytest

pytest_plugins = "pytester"


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    """Make all pytester tests use wider terminal for better output visibility."""
    monkeypatch.setenv("COLUMNS", "120")
