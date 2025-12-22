"""Tests for periodic check callback functionality."""
import time

from pytest_xdist_rate_limit import PeriodicCheckEvent, Rate, TokenBucketPacer


def test_periodic_check_callback_invoked(make_shared_json):
    """Test that periodic check callback is invoked at the correct interval."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_periodic"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=5,
        on_periodic_check_callback=capture_event,
    )

    # Make 4 calls - callback should not be invoked
    for _ in range(4):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 0

    # 5th call - callback should be invoked
    with limiter():
        time.sleep(0.01)

    assert len(events) == 1

    # Make 5 more calls - callback invoked again
    for _ in range(5):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 2


def test_periodic_check_event_structure(make_shared_json):
    """Test that PeriodicCheckEvent contains all expected fields."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_event_structure"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=10,
        on_periodic_check_callback=capture_event,
    )

    # Make enough calls to trigger callback
    for _ in range(10):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 1
    event = events[0]

    # Check all required fields exist
    assert isinstance(event, PeriodicCheckEvent)
    assert hasattr(event, 'worker_count')
    assert hasattr(event, 'duration_digest')
    assert hasattr(event, 'wait_digest')
    assert hasattr(event, 'windowed_rates')
    assert hasattr(event, 'sample_count')
    assert hasattr(event, 'target_rate')
    assert hasattr(event, 'current_rate')
    assert hasattr(event, 'drift')

    # Check convenience properties
    assert hasattr(event, 'duration_p50')
    assert hasattr(event, 'duration_p90')
    assert hasattr(event, 'duration_p99')
    assert hasattr(event, 'wait_p50')
    assert hasattr(event, 'wait_p90')
    assert hasattr(event, 'wait_p99')
    assert hasattr(event, 'wait_ratio')

    # Check base event fields
    assert hasattr(event, 'limiter_id')
    assert hasattr(event, 'limiter')
    assert hasattr(event, 'state_snapshot')
    assert hasattr(event, 'call_count')
    assert hasattr(event, 'exceptions')
    assert hasattr(event, 'start_time')


def test_periodic_check_with_insufficient_samples(make_shared_json):
    """Test that avg_call_duration is None when insufficient samples."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_insufficient_samples"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=5,
        on_periodic_check_callback=capture_event,
    )

    # Make only 5 calls (need 10 for statistics)
    for _ in range(5):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 1
    event = events[0]

    # Should have None for duration-based metrics (insufficient samples)
    assert event.duration_digest is None
    assert event.wait_digest is None
    assert event.sample_count < 10
    assert event.duration_p50 is None
    assert event.wait_p50 is None


def test_periodic_check_with_sufficient_samples(make_shared_json):
    """Test that metrics are calculated when sufficient samples exist."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_sufficient_samples"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=15,
        on_periodic_check_callback=capture_event,
    )

    # Make 15 calls with consistent duration
    for _ in range(15):
        with limiter():
            time.sleep(0.05)  # 50ms per call

    assert len(events) == 1
    event = events[0]

    # Should have valid duration-based metrics
    assert event.duration_digest is not None
    assert event.wait_digest is not None
    assert event.sample_count >= 10

    # Check that duration_p50 is reasonable (around 50ms)
    assert event.duration_p50 is not None
    assert 0.04 < event.duration_p50 < 0.06

    # Check percentiles are ordered correctly
    assert event.duration_p50 <= event.duration_p90 <= event.duration_p99

    # Check SUT throughput calculation (using p50 as representative)
    expected_throughput = (1 / event.duration_p50) * 3600
    # Throughput should be around 72,000 req/hr for 50ms calls
    assert 60000 < expected_throughput < 90000


def test_periodic_check_drift_calculation(make_shared_json):
    """Test that drift is calculated correctly."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_drift"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=10,
        seconds_before_first_check=0.1,  # Short delay for testing
        on_periodic_check_callback=capture_event,
    )

    # Make calls quickly to create drift
    for _ in range(10):
        with limiter():
            time.sleep(0.001)

    # Wait a bit to ensure we pass seconds_before_first_check
    time.sleep(0.2)

    # Make more calls to trigger another check
    for _ in range(10):
        with limiter():
            time.sleep(0.001)

    # Should have at least one event with drift calculated
    assert len(events) >= 1

    # At least one event should have drift calculated
    events_with_drift = [e for e in events if e.drift is not None]
    assert len(events_with_drift) > 0

    event = events_with_drift[0]
    assert isinstance(event.drift, float)
    assert event.drift >= 0  # Drift can be >1 (>100%) when rate far exceeds target


def test_periodic_check_target_rate(make_shared_json):
    """Test that target_rate matches configured rate."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    target = 7200  # 7200 calls/hour
    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_target_rate"),
        hourly_rate=Rate.per_hour(target),
        num_calls_between_checks=10,
        on_periodic_check_callback=capture_event,
    )

    for _ in range(10):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 1
    assert events[0].target_rate == target


def test_periodic_check_current_rate(make_shared_json):
    """Test that current_rate is calculated correctly."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_current_rate"),
        hourly_rate=Rate.per_hour(36000),  # High rate to avoid limiting
        num_calls_between_checks=10,
        on_periodic_check_callback=capture_event,
    )

    for _ in range(10):
        with limiter():
            time.sleep(0.01)

    assert len(events) == 1
    event = events[0]

    # Current rate should be in reasonable range (timing can vary)
    # We made 10 calls with 10ms sleep each, so should be around 3600 calls/hr
    # But timing is imprecise, so allow wide margin
    assert 1000 < event.current_rate < 500000  # Reasonable range


def test_periodic_check_no_callback_no_error(make_shared_json):
    """Test that no callback doesn't cause errors."""
    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_no_callback"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=5,
        on_periodic_check_callback=None,  # No callback
    )

    # Should not raise any errors
    for _ in range(10):
        with limiter():
            time.sleep(0.01)


def test_periodic_check_with_exceptions(make_shared_json):
    """Test that periodic check still works when exceptions occur."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_with_exceptions"),
        hourly_rate=Rate.per_hour(3600),
        num_calls_between_checks=10,
        on_periodic_check_callback=capture_event,
    )

    # Make some calls with exceptions
    for i in range(10):
        try:
            with limiter():
                if i % 3 == 0:
                    raise ValueError("Test exception")
                time.sleep(0.01)
        except ValueError:
            pass

    assert len(events) == 1
    event = events[0]

    # Should have tracked exceptions
    assert event.exceptions > 0
    assert event.call_count == 10


def test_periodic_check_duration_excludes_wait_time(make_shared_json):
    """Test that call duration excludes rate limiter wait time."""
    events = []

    def capture_event(event: PeriodicCheckEvent):
        events.append(event)

    # Low rate to force waiting
    limiter = TokenBucketPacer(
        shared_state=make_shared_json(name="test_duration_excludes_wait"),
        hourly_rate=Rate.per_second(2),  # 2 calls/second
        num_calls_between_checks=15,
        burst_capacity=1,
        on_periodic_check_callback=capture_event,
    )

    # Make calls that will cause waiting
    for _ in range(15):
        with limiter():
            time.sleep(0.05)  # Actual work: 50ms

    assert len(events) == 1
    event = events[0]

    # duration_p50 should be close to 50ms, not including wait time
    assert event.duration_p50 is not None
    # Should be around 50ms, definitely not 500ms+ (which would include wait)
    assert 0.04 < event.duration_p50 < 0.1

    # Wait times should be tracked separately and be significant
    assert event.wait_p50 is not None
    # With 2 calls/second rate and burst=1, we expect significant wait times
    assert event.wait_p50 > 0
