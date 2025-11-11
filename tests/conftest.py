import pytest
from _pytest.pytester import Pytester

pytest_plugins = ["pytester", "pytest_load_testing"]

PYTESTER_TIMEOUT = 10


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch):
    """Make all pytester tests use wider terminal for better output visibility."""
    monkeypatch.setenv("COLUMNS", "120")


@pytest.fixture
def run_with_timeout():
    """Fixture that provides a helper to run pytester with timeout

    Returns:
        A callable that runs pytester.runpytest_subprocess with timeout handling
    """

    def _run(pytester, *args, timeout=PYTESTER_TIMEOUT, **kwargs):
        """Run pytester with timeout and proper error handling.

        Args:
            pytester: The pytester fixture
            *args: Arguments to pass to runpytest_subprocess
            timeout: Timeout in seconds (default: PYTESTER_TIMEOUT)
            **kwargs: Keyword arguments to pass to runpytest_subprocess

        Returns:
            The result object from runpytest_subprocess

        Raises:
            pytest.fail: If the subprocess times out
        """
        try:
            return pytester.runpytest_subprocess(*args, timeout=timeout, **kwargs)
        except Pytester.TimeoutExpired as e:
            # Read stdout/stderr from pytester path
            stdout_path = pytester.path.joinpath("stdout")
            stderr_path = pytester.path.joinpath("stderr")

            stdout = stdout_path.read_text() if stdout_path.exists() else "<no stdout>"
            stderr = stderr_path.read_text() if stderr_path.exists() else "<no stderr>"

            # Truncate long output (first 100 + last 100 lines if > 200 lines)
            def truncate_output(text: str) -> str:
                lines = text.splitlines()
                if len(lines) > 200:
                    first_100 = "\n".join(lines[:100])
                    last_100 = "\n".join(lines[-100:])
                    return f"{first_100}\n\n... ({len(lines) - 200} lines omitted) ...\n\n{last_100}"
                return text

            stdout = truncate_output(stdout)
            stderr = truncate_output(stderr)

            pytest.fail(
                f"Test timed out after {timeout} seconds - load test did not complete\n"
                f"Error: {e}\n"
                f"STDOUT:\n{stdout}\n"
                f"STDERR:\n{stderr}"
            )

    return _run
