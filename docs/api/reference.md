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

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.RateLimitTimeout
    options:
      show_root_heading: true
      show_source: false

### RateLimit

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.RateLimit
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

### TokenBucketRateLimiter

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.TokenBucketRateLimiter
    options:
      show_root_heading: true
      show_source: false
      members:
        - __init__
        - rate_limited_context
        - id
        - hourly_rate

#### RateLimitContext

::: pytest_xdist_rate_limit.token_bucket_rate_limiter.TokenBucketRateLimiter.RateLimitContext
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

## Fixture Factories

### make_shared_json

::: pytest_xdist_rate_limit.shared_json.make_shared_json
    options:
      show_root_heading: true
      show_source: false

### make_rate_limiter

::: pytest_xdist_rate_limit.rate_limiter_fixture.make_rate_limiter
    options:
      show_root_heading: true
      show_source: false
