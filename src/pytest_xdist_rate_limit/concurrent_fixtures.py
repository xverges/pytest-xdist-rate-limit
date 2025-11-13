"""Concurrent fixture utilities for pytest-xdist workers.

This module provides utilities for creating fixtures that need to share state
across multiple pytest-xdist workers using file-based JSON storage with FileLock
for synchronization.
"""

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional, Set, Union

import pytest
from filelock import FileLock

logger = logging.getLogger(__name__)

# Constants
INIT_LOCK_TIMEOUT = 30  # seconds for initialization lock acquisition
SHARED_FILE_PREFIX = "pytest_shared_"  # prefix for shared fixture files


class SharedJson:
    """Thread-safe shared JSON data across pytest-xdist workers.

    This class provides atomic operations on a JSON file, ensuring data
    consistency when multiple workers access the same data concurrently.

    All data must be JSON-serializable (dict, list, str, int, float, bool, None).
    For timestamps, use time.time() instead of datetime objects.

    Attributes:
        data_file: Path to the JSON data file
        lock_file: Path to the lock file for synchronization
        timeout: Timeout in seconds for acquiring locks (-1 = wait forever)
    """

    def __init__(self, data_file: Path, lock_file: Path, timeout: float = -1):
        """Initialize the SharedJson instance.

        Args:
            data_file: Path where JSON data will be stored
            lock_file: Path for the lock file
            timeout: Timeout in seconds for lock acquisition (-1 = wait forever)

        Raises:
            filelock.Timeout: If lock cannot be acquired within timeout period
        """
        self.data_file = data_file
        self.lock_file = lock_file
        self.timeout = timeout
        self._lock = FileLock(str(lock_file), timeout=timeout)

    @property
    def name(self) -> str:
        """Get the name derived from the data file path.

        Returns:
            str: The stem (filename without extension) of the data file,
                 with the pytest_shared_ prefix removed if present
        """
        stem = self.data_file.stem
        if stem.startswith(SHARED_FILE_PREFIX):
            return stem[len(SHARED_FILE_PREFIX) :]
        return stem

    @contextmanager
    def locked_dict(self) -> Generator[Dict[str, Any], None, None]:
        """Context manager for atomic read-modify-write operations.

        Yields a dict that can be modified in-place. All changes are written
        back to the file atomically when the context exits.

        Yields:
            Dict[str, Any]: The current data from the JSON file (modifiable)

        Raises:
            filelock.Timeout: If lock cannot be acquired within timeout period

        Example:
            with shared.locked_dict() as data:
                data['count'] = data.get('count', 0) + 1
                data.setdefault('errors', []).append(error)

        Note:
            The dict is a regular Python dict, so all dict operations work
            (get, setdefault, update, etc.). However, only JSON-serializable
            values can be stored (no datetime, custom objects, etc.).
        """
        with self._lock:
            if self.data_file.exists():
                with open(self.data_file, "r") as f:
                    data = json.load(f)
            else:
                data = {}

            yield data

            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=2)

    def read(self) -> Dict[str, Any]:
        """Read the current data atomically (read-only snapshot).

        Returns:
            dict: A copy of the current data from the JSON file

        Raises:
            filelock.Timeout: If lock cannot be acquired within timeout period

        Example:
            data = shared.read()
            count = data.get('count', 0)
        """
        with self._lock:
            if self.data_file.exists():
                with open(self.data_file, "r") as f:
                    return json.load(f)
            return {}

    def update(self, updates: Dict[str, Any]) -> None:
        """Update specific keys atomically.

        Args:
            updates: Dictionary of key-value pairs to update

        Raises:
            filelock.Timeout: If lock cannot be acquired within timeout period

        Example:
            shared.update({'count': 5, 'status': 'active'})
        """
        with self.locked_dict() as data:
            data.update(updates)


@pytest.fixture(scope="session")
def make_shared_json(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    worker_id: str,
) -> Generator[Callable[..., SharedJson], None, None]:
    """Factory for creating shared JSON fixtures across pytest-xdist workers.

    This is a session-scoped fixture that returns a factory function for creating
    SharedJson instances with proper worker coordination.

    Args:
        request: The pytest fixture request object
        tmp_path_factory: Pytest's temporary path factory
        worker_id: The xdist worker ID (e.g., 'gw0', 'gw1', or 'master')

    Returns:
        Callable[..., SharedJson]: Factory function that creates SharedJson instances

    Example:
        @pytest.fixture(scope="session")
        def api_rate_tracker(make_shared_json):
            def init_data():
                return {
                    'count': 0,
                    'limit': 100,
                    'errors': []
                }

            def report(shared):
                data = shared.read()
                print(f"Total API calls: {data['count']}")

            return make_shared_json(
                name="api_rate_tracker",
                on_first_worker=init_data,
                on_last_worker=report
            )

        def test_api_call(api_rate_tracker):
            with api_rate_tracker.locked_dict() as data:
                data['count'] = data.get('count', 0) + 1
    """
    shared_temp = tmp_path_factory.getbasetemp().parent
    last_worker_callbacks = []
    created_files: Set[Path] = set()

    def _initialize_first_worker_data(
        on_first_worker: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
        init_marker: Path,
        data_file: Path,
    ) -> None:
        is_first = not init_marker.exists()
        if is_first:
            init_marker.parent.mkdir(parents=True, exist_ok=True)
            init_marker.touch()

            if isinstance(on_first_worker, dict):
                initial_data = on_first_worker
            elif callable(on_first_worker):
                initial_data = on_first_worker()
                if not isinstance(initial_data, dict):
                    raise TypeError(
                        f"on_first_worker callback must return a dict, got {type(initial_data)}"
                    )

            data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(data_file, "w") as f:
                json.dump(initial_data, f, indent=2)

    def factory(
        name: str,
        on_first_worker: Optional[
            Union[Dict[str, Any], Callable[[], Dict[str, Any]]]
        ] = None,
        on_last_worker: Optional[Callable[[SharedJson], None]] = None,
        timeout: float = -1,
    ) -> SharedJson:
        """Create a SharedJson instance with worker coordination.

        Args:
            name: Unique name for this fixture (used in file paths)
            on_first_worker: Initial data (dict) or callback (callable) for first worker.
                           If dict: used as initial data
                           If callable: called to get initial data (should return dict)
            on_last_worker: Optional callback called once during factory teardown by the last worker.
                          Receives the SharedJson instance. This runs after all workers
                          have finished their tests.
            timeout: Timeout in seconds for lock acquisition (-1 = wait forever)

        Returns:
            SharedJson: Instance for atomic access to shared JSON data

        Raises:
            filelock.Timeout: If lock cannot be acquired within timeout period
        """
        base_path = shared_temp / f"{SHARED_FILE_PREFIX}{name}"
        data_file = base_path.with_suffix(".json")
        init_marker = base_path.with_name(f"{name}_init.marker")
        data_lock_file = base_path.with_name(f"{name}_data.lock")
        init_lock_file = base_path.with_name(f"{name}_init.lock")

        shared_json = SharedJson(data_file, data_lock_file, timeout=timeout)

        # Initialize data on first worker if needed
        if on_first_worker is not None:
            init_lock = FileLock(str(init_lock_file), timeout=INIT_LOCK_TIMEOUT)
            with init_lock:
                _initialize_first_worker_data(on_first_worker, init_marker, data_file)

        created_files.add(data_file)
        created_files.add(data_lock_file)
        created_files.add(init_lock_file)
        if init_marker.exists():
            created_files.add(init_marker)

        if on_last_worker is not None:
            last_worker_callbacks.append((shared_json, on_last_worker))

        return shared_json

    yield factory

    # Teardown: Determine if this is the last worker and perform cleanup
    # Create a SharedJson to track which workers have finished
    teardown_tracker_path = shared_temp / "pytest_factory_teardown"
    teardown_data_file = teardown_tracker_path.with_suffix(".json")
    teardown_lock_file = teardown_tracker_path.with_name("teardown.lock")

    teardown_tracker = SharedJson(teardown_data_file, teardown_lock_file, timeout=30)

    # Get the actual number of workers from pytest config
    # The workerinput plugin option contains worker count info
    total_workers = getattr(request.config, "workerinput", {}).get("workercount", 1)
    if total_workers is None:
        total_workers = 1

    # Track this worker's teardown
    with teardown_tracker.locked_dict() as data:
        if "finished_workers" not in data:
            data["finished_workers"] = []
            data["total_workers"] = total_workers

        # Add this worker if not already tracked
        if worker_id not in data["finished_workers"]:
            data["finished_workers"].append(worker_id)

        # Check if this is the last worker
        is_last = len(data["finished_workers"]) >= data["total_workers"]

    if is_last:
        for shared_json, callback in last_worker_callbacks:
            try:
                callback(shared_json)
            except Exception as e:
                logger.exception(f"Error in on_last_worker callback: {e}")

        for file_path in created_files:
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.debug(f"Cleaned up file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup file {file_path}: {e}")

        try:
            if teardown_data_file.exists():
                teardown_data_file.unlink()
            if teardown_lock_file.exists():
                teardown_lock_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup teardown tracker files: {e}")


@pytest.fixture(scope="session")
def make_rate_limiter(make_shared_json):
    """Factory for creating rate limiter fixtures across pytest-xdist workers.

    This fixture provides a way to create TokenBucketRateLimiter instances
    that share state across workers using SharedJson.

    Example:
        @pytest.fixture(scope="session")
        def pacer(make_rate_limiter):
            from pytest_xdist_rate_limit import RateLimit

            return make_rate_limiter(
                name="pacer",
                hourly_rate=RateLimit.per_second(10)
            )

        def test_api_call(pacer):
            with pacer() as ctx:
                # Entering the context will wait if required to respect the rate
                pass
    """
    from pytest_xdist_rate_limit import (
        RateLimit,
        TokenBucketRateLimiter,
    )

    def factory(
        name: str,
        hourly_rate: Union[RateLimit, Callable[[], RateLimit]],
        max_drift: float = 0.1,
        on_drift_callback: Optional[Callable[[str, float, float, float], None]] = None,
        num_calls_between_checks: int = 10,
        seconds_before_first_check: float = 60.0,
        burst_capacity: Optional[int] = None,
        max_calls: int = -1,
        max_call_callback: Optional[Callable[[str, int], None]] = None,
    ) -> TokenBucketRateLimiter:
        """Create a TokenBucketRateLimiter instance with shared state.

        Args:
            name: Unique name for this rate limiter
            hourly_rate: Rate limit (RateLimit object or callable returning one)
            max_drift: Maximum allowed drift from expected rate (0-1)
            on_drift_callback: Callback when drift exceeds max_drift
            num_calls_between_checks: Number of calls between rate checks
            seconds_before_first_check: Minimum time before rate checking begins
            burst_capacity: Maximum tokens in bucket (defaults to 10% of hourly rate)
            max_calls: Maximum number of calls allowed (-1 for unlimited)
            max_call_callback: Callback when max_calls is reached

        Returns:
            TokenBucketRateLimiter: Rate limiter instance
        """
        shared_state = make_shared_json(name=name)

        return TokenBucketRateLimiter(
            shared_state=shared_state,
            hourly_rate=hourly_rate,
            max_drift=max_drift,
            on_drift_callback=on_drift_callback,
            num_calls_between_checks=num_calls_between_checks,
            seconds_before_first_check=seconds_before_first_check,
            burst_capacity=burst_capacity,
            max_calls=max_calls,
            max_call_callback=max_call_callback,
        )

    return factory
