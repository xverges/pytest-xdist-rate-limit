# API Reference

This documentation is automatically generated from the source code docstrings, ensuring it always matches the actual implementation.

## Core Classes

### SharedJson

::: pytest_xdist_rate_limit.shared_json.SharedJson
    options:
      show_root_heading: true
      show_source: false
      members:
        - __init__
        - locked_dict
        - read
        - update
        - name

### RateLimitTimeout

::: pytest_xdist_rate_limit.exceptions.RateLimitTimeout
    options:
      show_root_heading: true
      show_source: false

### Rate

::: pytest_xdist_rate_limit.rate.Rate
    options:
      show_root_heading: true
      show_source: false
      members:
        - __init__
        - per_second
        - per_minute
        - per_hour
        - per_day
        - calls_per_hour

### TokenBucketPacer

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.TokenBucketPacer
    options:
      show_root_heading: true
      show_source: false
      members:
        - __init__
        - rate_limited_context
        - __call__
        - id
        - hourly_rate

#### RateLimitContext

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.TokenBucketPacer.RateLimitContext
    options:
      show_root_heading: true
      show_source: false
      members:
        - id
        - hourly_rate
        - call_count
        - exceptions
        - start_time
        - seconds_waited

## Event Classes

### PacerEvent

::: pytest_xdist_rate_limit.events.PacerEvent
    options:
      show_root_heading: true
      show_source: false
      members:
        - limiter_id
        - limiter
        - state_snapshot
        - call_count
        - exceptions
        - start_time
        - elapsed_time

### DriftEvent

::: pytest_xdist_rate_limit.events.DriftEvent
    options:
      show_root_heading: true
      show_source: false
      members:
        - current_rate
        - target_rate
        - drift
        - max_drift

### MaxCallsEvent

::: pytest_xdist_rate_limit.events.MaxCallsEvent
    options:
      show_root_heading: true
      show_source: false
      members:
        - max_calls

### PeriodicCheckEvent

::: pytest_xdist_rate_limit.events.PeriodicCheckEvent
    options:
      show_root_heading: true
      show_source: false
      members:
        - worker_count
        - duration_digest
        - wait_digest
        - windowed_rates
        - sample_count
        - target_rate
        - current_rate
        - drift
        - duration_p50
        - duration_p90
        - duration_p99
        - wait_p50
        - wait_p90
        - wait_p99
        - wait_ratio

## Fixture Factories

### make_shared_json

::: pytest_xdist_rate_limit.shared_json.make_shared_json
    options:
      show_root_heading: true
      show_source: false

### make_pacer

::: pytest_xdist_rate_limit.rate_limiter_fixture.make_pacer
    options:
      show_root_heading: true
      show_source: false

### make_rate_limiter (Deprecated)

::: pytest_xdist_rate_limit.rate_limiter_fixture.make_rate_limiter
    options:
      show_root_heading: true
      show_source: false

## Deprecated Aliases

The following names are deprecated and maintained for backward compatibility:

- `RateLimit` - Use [`Rate`](rate.py:12) instead
- `TokenBucketRateLimiter` - Use [`TokenBucketPacer`](token_bucket_rate_limiter.py:34) instead
- `make_rate_limiter` - Use [`make_pacer`](rate_limiter_fixture.py:13) instead
