# pytest-xdist-rate-limit

[![PyPI version](https://img.shields.io/pypi/v/pytest-xdist-rate-limit.svg)](https://pypi.org/project/pytest-xdist-rate-limit)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-xdist-rate-limit.svg)](https://pypi.org/project/pytest-xdist-rate-limit)
[![Build Status](https://github.com/xverges/pytest-xdist-rate-limit/actions/workflows/main.yml/badge.svg)](https://github.com/xverges/pytest-xdist-rate-limit/actions/workflows/main.yml)

Set the rate at which pytest-xdist workers can run tests.

## Features

* **Call pacing**: Define how often tests hit the System Under Test.
  **Setup flexible load testing scenarios** when used in conjunction with
  [pytest-xdist-load-testing](https://github.com/xverges/pytest-xdist-load-testing).
* **Rate drift detection**: Set callbacks when the test system cannot adhere to the intended rate.
* **Shared state across workers**: Have session-scoped fixtures share state across pytest-xdist workers,
  transparently using file-based JSON storage
* **Setup/teardown on first/last worker**: First/last worker callbacks for setup and teardown,
  transparently using the pattern in [Making session-scoped fixtures execute only
  once](https://pytest-xdist.readthedocs.io/en/latest/how-to.html#making-session-scoped-fixtures-execute-only-once)

## Requirements

* Python 3.9+
* pytest >= 8.4.2
* pytest-xdist >= 3.8.0
* filelock >= 3.0.0

## Installation

```bash
pip install pytest-xdist-rate-limit
```

## Examples

See the [`examples/`](https://github.com/xverges/pytest-xdist-rate-limit/tree/main/examples)
folder for working examples.

### Call Pacing

Use `make_pacer` to generate load at a controlled rate across workers.

Example using `pytest_xdist_load_testing` to run  ~80% of `test_get` and
~20% `test_put` for 10K calls, or until we detect that we cannot keep with
the requested rate 10 calls per second.

```python
import pytest
from pytest_xdist_load_testing import stop_load_testing, weight
from pytest_xdist_rate_limit import Rate

@pytest.fixture(scope="session")
def pacer(request, make_pacer):
    """Pacer for generating load to SUT"""

    def on_periodic_check(event):
        """Called every N calls to monitor performance metrics.
        
        Provides detailed metrics including:
        - Current vs target rate and drift
        - Call duration percentiles (p50, p90, p99)
        - Wait time percentiles
        - Worker count and sample statistics
        """
        # Check drift manually
        if event.drift is not None and event.drift > 0.2:
            msg = (f"Rate drift detected: current={event.current_rate:.2f}/hr, "
                   f"target={event.target_rate}/hr, drift={event.drift:.2%}")
            stop_load_testing(msg)
        
        # Log performance metrics
        if event.duration_p50 is not None:
            print(f"Performance: p50={event.duration_p50*1000:.1f}ms, "
                  f"p90={event.duration_p90*1000:.1f}ms, "
                  f"p99={event.duration_p99*1000:.1f}ms")

    def on_max_calls(event):
        """Called when max_calls limit is reached."""
        msg = f"Reached {event.max_calls} calls in {event.elapsed_time:.1f}s"
        stop_load_testing(msg)

    return make_pacer(
        name="pacer",
        hourly_rate=Rate.per_second(10),  # 10 calls/second
        num_calls_between_checks=50,  # Check every 50 calls
        seconds_before_first_check=10.0,  # Wait 10s before first check
        on_periodic_check_callback=on_periodic_check,
        max_calls=10_000,
        on_max_calls_callback=on_max_calls
    )

@weight(80)
def test_get(pacer):
    with pacer():
        # Context entry waits to maintain target rate
        response = api.get("/data")

@weight(20)
def test_put(pacer):
    with pacer() as ctx:
        # Context entry waits to maintain target rate
        response = api.put(f"/data/{ctx.call_count}")
```

#### Timeout Support

You can specify a timeout to prevent tests from waiting too long:

```python
def test_with_timeout(pacer):
    try:
        with pacer(timeout=5.0) as ctx:
            # Will raise RateLimitTimeout if wait exceeds 5 seconds
            ...
    except RateLimitTimeout as e:
        ...
```

### Shared Session state

```python
import pytest

@pytest.fixture(scope="session")
def shared_resource(make_shared_json):
    """Shared resource with setup and teardown."""

    def setup():
        # Called by first worker only
        # Other workers have to wait for completion
        return {'initialized': True, 'counter': 0}

    def teardown(data):
        # Called by last worker only
        print(f"Final counter value: {data['counter']}")

    return make_shared_json(
        name="resource",
        on_first_worker=setup,
        on_last_worker=teardown
    )

def test_with_resource(shared_resource):
    with shared_resource.locked_dict() as data:
        data['counter'] += 1
```

## Documentation

📚 **[Full Documentation](https://xverges.github.io/pytest-xdist-rate-limit/)**

* [API Reference](https://xverges.github.io/pytest-xdist-rate-limit/api/reference/) - Complete API documentation

## License

Distributed under the terms of the [MIT](https://opensource.org/licenses/MIT) license, "pytest-xdist-rate-limit" is free and open source software

## Issues

If you encounter any problems, please [file an issue](https://github.com/xverges/pytest-xdist-rate-limit/issues) along with a detailed description.

---

This [pytest](https://github.com/pytest-dev/pytest) plugin was generated with [Cookiecutter](https://github.com/audreyr/cookiecutter) along with [@hackebrot](https://github.com/hackebrot)'s [cookiecutter-pytest-plugin](https://github.com/pytest-dev/cookiecutter-pytest-plugin) template.
