"""pytest-xdist-rate-limit: Shared state and call pacing for pytest-xdist workers."""

from .events import (
    DriftEvent,
    MaxCallsEvent,
    PacerEvent,
    PeriodicCheckEvent,
)
from .exceptions import RateLimitTimeout
from .rate import Rate, RateLimit  # RateLimit is deprecated, use Rate
from .rate_limiter_fixture import make_pacer, make_rate_limiter
from .shared_json import SharedJson, make_shared_json
from .token_bucket_rate_limiter import TokenBucketPacer

# Backward compatibility aliases
TokenBucketRateLimiter = TokenBucketPacer

__version__ = "1.0.0"
__all__ = [
    "make_shared_json",
    "make_pacer",
    "make_rate_limiter",  # Deprecated, use make_pacer
    "SharedJson",
    "Rate",
    "RateLimit",  # Deprecated, use Rate
    "RateLimitTimeout",
    "TokenBucketPacer",
    "TokenBucketRateLimiter",  # Deprecated, use TokenBucketPacer
    "PacerEvent",
    "DriftEvent",
    "MaxCallsEvent",
    "PeriodicCheckEvent",
]
