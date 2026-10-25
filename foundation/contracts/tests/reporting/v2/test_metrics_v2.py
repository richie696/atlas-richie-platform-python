"""Value-object, calculation, and codec tests for the frozen Metrics V2 contract."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from atlas_richie.contracts.reporting import v1
from atlas_richie.contracts.reporting.v2.metrics_v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    MAX_SAFE_INTEGER,
    CounterName,
    CounterRateState,
    CounterReading,
    GaugeName,
    GaugeQuality,
    GaugeReading,
    HistogramDelta,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
    calculate_counter_rate,
    calculate_histogram_delta,
)
from atlas_richie.contracts.reporting.v2.metrics_v2_codec import (
    METRICS_V2_MAX_RECORDS,
    METRICS_V2_MAX_SIZE_BYTES,
    MetricsV2ProtocolError,
    decode_metrics_snapshot,
    encode_metrics_snapshot,
)

_TEST_STARTUP_EPOCH = UUID("00000000-0000-4000-8000-000000000001")


def _snapshot(**changes: object) -> MetricsSnapshot:
    values: dict[str, object] = {
        "reporter_id": "reporter-1",
        "startup_epoch": _TEST_STARTUP_EPOCH,
        "sequence": 1,
        "captured_at": datetime(2026, 10, 11, tzinfo=UTC),
        "counters": (),
        "histograms": (),
        "gauges": (),
    }
    values.update(changes)
    if "capture_elapsed_ns" not in changes:
        values["capture_elapsed_ns"] = int(values["sequence"]) * 1_000_000_000
    return MetricsSnapshot(**values)  # type: ignore[arg-type]


def test_snapshot_accepts_typed_counters_and_explicit_unavailable_gauge() -> None:
    snapshot = _snapshot(
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, 12),),
        gauges=(
            GaugeReading(
                GaugeName.PROCESS_CPU_RATIO,
                None,
                GaugeQuality.UNAVAILABLE,
            ),
        ),
    )

    assert snapshot.counters[0].value == 12
    assert snapshot.gauges[0].value is None


def test_snapshot_accepts_maximum_capture_elapsed_decimal() -> None:
    snapshot = _snapshot(capture_elapsed_ns=(10**38) - 1)

    assert snapshot.capture_elapsed_ns == (10**38) - 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reporter_id", "  "),
        ("startup_epoch", 0),
        ("startup_epoch", True),
        ("sequence", 0),
        ("sequence", False),
        ("capture_elapsed_ns", -1),
        ("capture_elapsed_ns", True),
        ("capture_elapsed_ns", 1.0),
        ("capture_elapsed_ns", 10**38),
        ("captured_at", datetime(2026, 10, 11)),
        ("captured_at", datetime(2026, 10, 11, tzinfo=timezone(timedelta(hours=8)))),
    ],
)
def test_snapshot_rejects_invalid_identity_ordering_and_time(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        _snapshot(**{field: value})


@pytest.mark.parametrize("value", [-1, True, 1.0, MAX_SAFE_INTEGER + 1])
def test_counter_requires_nonnegative_integer_and_rejects_bool(value: object) -> None:
    with pytest.raises(ValueError):
        CounterReading(
            CounterName.HTTP_REQUESTS_COMPLETED,
            value,  # type: ignore[arg-type]
        )


def test_counter_accepts_the_safe_integer_boundary() -> None:
    counter = CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, MAX_SAFE_INTEGER)

    assert counter.value == MAX_SAFE_INTEGER


def test_snapshot_rejects_duplicate_counter_and_gauge_identities() -> None:
    counter = CounterReading(CounterName.SENTINEL_ENTRIES_BLOCKED, 1, "r")
    gauge = GaugeReading(GaugeName.PROCESS_RSS_BYTES, 10, GaugeQuality.AVAILABLE)

    with pytest.raises(ValueError, match="repeat a counter"):
        _snapshot(counters=(counter, counter))
    with pytest.raises(ValueError, match="repeat a gauge"):
        _snapshot(gauges=(gauge, gauge))


def test_counter_rate_uses_matching_identity_and_monotonic_interval() -> None:
    name = CounterName.SENTINEL_ENTRIES_ADMITTED
    previous = _snapshot(
        sequence=4,
        captured_at=datetime(2026, 10, 11, tzinfo=UTC),
        counters=(CounterReading(name, 10, "POST /orders"),),
    )
    current = _snapshot(
        sequence=5,
        captured_at=datetime(2026, 10, 11, 0, 0, 2, tzinfo=UTC),
        capture_elapsed_ns=6_000_000_000,
        counters=(CounterReading(name, 16, "POST /orders"),),
    )

    result = calculate_counter_rate(previous, current, name, "POST /orders")

    assert result.state is CounterRateState.AVAILABLE
    assert result.delta == 6
    assert result.elapsed_seconds == 2.0
    assert result.rate_per_second == 3.0
    assert calculate_counter_rate(previous, current, name).state is (
        CounterRateState.BASELINE_REQUIRED
    )


@pytest.mark.parametrize(
    ("current_changes", "expected"),
    [
        (
            {"startup_epoch": UUID("00000000-0000-4000-8000-000000000002")},
            CounterRateState.BASELINE_REQUIRED,
        ),
        ({"sequence": 1}, CounterRateState.SAMPLE_ORDER_INVALID),
        (
            {"capture_elapsed_ns": 2_000_000_000},
            CounterRateState.SAMPLE_ORDER_INVALID,
        ),
        (
            {"counters": (CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, 1),)},
            CounterRateState.BASELINE_REQUIRED,
        ),
        (
            {
                "counters": (
                    CounterReading(CounterName.SENTINEL_ENTRIES_BLOCKED, 1, "r"),
                )
            },
            CounterRateState.BASELINE_REQUIRED,
        ),
    ],
)
def test_counter_rate_refuses_epoch_sequence_time_and_missing_counter_mismatches(
    current_changes: dict[str, object], expected: CounterRateState
) -> None:
    name = CounterName.SENTINEL_ENTRIES_ADMITTED
    previous = _snapshot(
        sequence=2,
        captured_at=datetime(2026, 10, 11, tzinfo=UTC),
        counters=(CounterReading(name, 10),),
    )
    current = _snapshot(
        **{
            "sequence": 3,
            "captured_at": datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC),
            "counters": (CounterReading(name, 12),),
            **current_changes,
        }
    )

    assert calculate_counter_rate(previous, current, name).state is expected


def test_counter_rate_uses_monotonic_interval_when_wall_clock_moves_backwards() -> None:
    name = CounterName.HTTP_REQUESTS_COMPLETED
    previous = _snapshot(
        sequence=4,
        captured_at=datetime(2026, 10, 11, 0, 0, 2, tzinfo=UTC),
        capture_elapsed_ns=4_000_000_000,
        counters=(CounterReading(name, 10),),
    )
    current = _snapshot(
        sequence=5,
        captured_at=datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC),
        capture_elapsed_ns=6_000_000_000,
        counters=(CounterReading(name, 16),),
    )

    result = calculate_counter_rate(previous, current, name)

    assert result.state is CounterRateState.AVAILABLE
    assert result.elapsed_seconds == 2.0
    assert result.rate_per_second == 3.0


def test_counter_rate_breaks_baseline_after_counter_reset() -> None:
    name = CounterName.HTTP_REQUESTS_COMPLETED
    previous = _snapshot(
        sequence=1,
        captured_at=datetime(2026, 10, 11, tzinfo=UTC),
        counters=(CounterReading(name, 20),),
    )
    current = _snapshot(
        sequence=2,
        captured_at=datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC),
        counters=(CounterReading(name, 2),),
    )

    result = calculate_counter_rate(previous, current, name)

    assert result.state is CounterRateState.COUNTER_RESET
    assert result.rate_per_second is None


def test_histogram_validates_overflow_bucket_and_empty_statistics() -> None:
    histogram = HistogramReading(
        name=HistogramName.HTTP_REQUEST_DURATION,
        boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        bucket_counts=(0, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0),
        sample_count=4,
        total_ns=180_000_000,
        min_ns=5_000_000,
        max_ns=100_000_000,
    )
    assert histogram.bucket_counts[-1] == 0

    with pytest.raises(ValueError, match="overflow bucket"):
        HistogramReading(
            name=HistogramName.HTTP_REQUEST_DURATION,
            boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
            bucket_counts=(1,) + (0,) * 11,
            sample_count=3,
            total_ns=50,
            min_ns=5,
            max_ns=30,
        )
    with pytest.raises(ValueError, match="empty histogram"):
        HistogramReading(
            name=HistogramName.HTTP_REQUEST_DURATION,
            boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
            bucket_counts=(0,) * 13,
            sample_count=0,
            total_ns=1,
            min_ns=None,
            max_ns=None,
        )
    with pytest.raises(ValueError, match="immutable tuples"):
        HistogramReading(
            name=HistogramName.HTTP_REQUEST_DURATION,
            boundaries_ns=list(HTTP_REQUEST_DURATION_BOUNDARIES_NS),  # type: ignore[arg-type]
            bucket_counts=(1,) + (0,) * 12,
            sample_count=1,
            total_ns=5,
            min_ns=5,
            max_ns=5,
        )


def test_histogram_total_ns_round_trips_above_json_safe_integer() -> None:
    total_ns = MAX_SAFE_INTEGER * 3
    snapshot = _snapshot(
        histograms=(
            HistogramReading(
                HistogramName.HTTP_REQUEST_DURATION,
                HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                (0,) * 12 + (3,),
                3,
                total_ns,
                0,
                MAX_SAFE_INTEGER,
            ),
        ),
    )

    payload = encode_metrics_snapshot(snapshot)

    assert f'"total_ns":"{total_ns}"'.encode() in payload
    assert b'"capture_elapsed_ns":"1000000000"' in payload
    assert decode_metrics_snapshot(payload) == snapshot


def _http_histogram(
    *,
    buckets: tuple[int, ...],
    sample_count: int,
    total_ns: int,
    resource: str | None = None,
) -> HistogramReading:
    return HistogramReading(
        name=HistogramName.HTTP_REQUEST_DURATION,
        boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        bucket_counts=buckets,
        sample_count=sample_count,
        total_ns=total_ns,
        min_ns=0 if sample_count else None,
        max_ns=100 if sample_count else None,
        resource=resource,
    )


def test_histogram_delta_subtracts_cumulative_buckets_and_keeps_zero_rt_valid() -> None:
    name = HistogramName.HTTP_REQUEST_DURATION
    previous = _snapshot(
        sequence=7,
        captured_at=datetime(2026, 10, 11, 0, 0, 2, tzinfo=UTC),
        histograms=(
            _http_histogram(buckets=(2, 1) + (0,) * 11, sample_count=3, total_ns=8),
        ),
    )
    current = _snapshot(
        sequence=8,
        captured_at=datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC),
        capture_elapsed_ns=9_000_000_000,
        histograms=(
            _http_histogram(buckets=(4, 2) + (0,) * 11, sample_count=6, total_ns=16),
        ),
    )

    result = calculate_histogram_delta(previous, current, name)

    assert result.state is CounterRateState.AVAILABLE
    assert result.elapsed_seconds == 2.0
    assert result.histogram is not None
    assert result.histogram.bucket_counts == (2, 1) + (0,) * 11
    assert result.histogram.sample_count == 3
    assert result.histogram.total_ns == 8
    assert result.histogram.p95_upper_bound_ns == HTTP_REQUEST_DURATION_BOUNDARIES_NS[1]
    zero_latency = HistogramDelta(
        name=name,
        boundaries_ns=HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        bucket_counts=(1,) + (0,) * 12,
        sample_count=1,
        total_ns=0,
    )
    assert zero_latency.p95_upper_bound_ns == HTTP_REQUEST_DURATION_BOUNDARIES_NS[0]


def test_histogram_p95_is_unavailable_when_nearest_rank_falls_in_overflow() -> None:
    histogram = HistogramDelta(
        HistogramName.HTTP_REQUEST_DURATION,
        HTTP_REQUEST_DURATION_BOUNDARIES_NS,
        (90, 4) + (0,) * 10 + (6,),
        100,
        1_000,
    )

    assert histogram.p95_upper_bound_ns is None


def test_histogram_delta_refuses_missing_reset_epoch_order_and_bucket_changes() -> None:
    name = HistogramName.HTTP_REQUEST_DURATION
    previous_time = datetime(2026, 10, 11, tzinfo=UTC)
    previous_histogram = _http_histogram(
        buckets=(3, 4) + (0,) * 11, sample_count=7, total_ns=300
    )
    previous = _snapshot(
        sequence=4, captured_at=previous_time, histograms=(previous_histogram,)
    )

    def current_snapshot(
        *,
        epoch: UUID = _TEST_STARTUP_EPOCH,
        sequence: int = 5,
        captured_at: datetime = datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC),
        capture_elapsed_ns: int | None = None,
        histogram: HistogramReading | None = None,
    ) -> MetricsSnapshot:
        values: dict[str, object] = {
            "startup_epoch": epoch,
            "sequence": sequence,
            "captured_at": captured_at,
            "histograms": () if histogram is None else (histogram,),
        }
        if capture_elapsed_ns is not None:
            values["capture_elapsed_ns"] = capture_elapsed_ns
        return _snapshot(**values)

    assert (
        calculate_histogram_delta(
            previous,
            current_snapshot(
                epoch=UUID("00000000-0000-4000-8000-000000000002"),
                histogram=previous_histogram,
            ),
            name,
        ).state
        is CounterRateState.BASELINE_REQUIRED
    )
    assert (
        calculate_histogram_delta(
            previous, current_snapshot(sequence=4, histogram=previous_histogram), name
        ).state
        is CounterRateState.SAMPLE_ORDER_INVALID
    )
    assert (
        calculate_histogram_delta(previous, current_snapshot(), name).state
        is CounterRateState.BASELINE_REQUIRED
    )
    reset_histogram = _http_histogram(
        buckets=(2, 4) + (0,) * 11, sample_count=6, total_ns=250
    )
    assert (
        calculate_histogram_delta(
            previous, current_snapshot(histogram=reset_histogram), name
        ).state
        is CounterRateState.COUNTER_RESET
    )
    with pytest.raises(ValueError, match="boundaries must match Metrics V2"):
        HistogramReading(
            name=name,
            boundaries_ns=(10, 200),
            bucket_counts=(3, 5, 1),
            sample_count=9,
            total_ns=350,
            min_ns=1,
            max_ns=200,
        )
    assert (
        calculate_histogram_delta(
            previous,
            current_snapshot(
                captured_at=previous_time,
                capture_elapsed_ns=4_000_000_000,
                histogram=previous_histogram,
            ),
            name,
        ).state
        is CounterRateState.SAMPLE_ORDER_INVALID
    )


@pytest.mark.parametrize(
    ("value", "quality"),
    [
        (0, GaugeQuality.UNAVAILABLE),
        (None, GaugeQuality.AVAILABLE),
        (float("nan"), GaugeQuality.AVAILABLE),
        (float("inf"), GaugeQuality.AVAILABLE),
        (-0.1, GaugeQuality.AVAILABLE),
        (True, GaugeQuality.AVAILABLE),
    ],
)
def test_gauge_requires_explicit_and_finite_measurement(
    value: object, quality: GaugeQuality
) -> None:
    with pytest.raises(ValueError):
        GaugeReading(  # type: ignore[arg-type]
            GaugeName.PROCESS_MEMORY_RATIO, value, quality
        )


@pytest.mark.parametrize(
    "value",
    [MAX_SAFE_INTEGER + 1, float(MAX_SAFE_INTEGER + 1)],
)
def test_gauge_rejects_values_outside_json_safe_number_range(value: float) -> None:
    with pytest.raises(ValueError, match="safe number range"):
        GaugeReading(
            GaugeName.PROCESS_RSS_BYTES,
            value,
            GaugeQuality.AVAILABLE,
        )


def test_gauge_accepts_json_safe_number_boundary() -> None:
    gauge = GaugeReading(
        GaugeName.PROCESS_RSS_BYTES,
        MAX_SAFE_INTEGER,
        GaugeQuality.AVAILABLE,
    )

    assert gauge.value == MAX_SAFE_INTEGER


def test_records_are_frozen_and_sequences_are_immutable() -> None:
    reading = CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, 1)
    with pytest.raises((AttributeError, TypeError)):
        reading.value = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="immutable tuples"):
        _snapshot(counters=[reading])
    with pytest.raises(ValueError, match="finite and non-negative"):
        GaugeReading(
            GaugeName.PROCESS_RSS_BYTES,
            float("inf"),
            GaugeQuality.AVAILABLE,
        )
    assert not hasattr(v1, "MetricsSnapshot")


def test_json_codec_round_trips_all_record_families() -> None:
    snapshot = _snapshot(
        reporter_id="reporter-α",
        counters=(
            CounterReading(CounterName.SENTINEL_ENTRIES_ADMITTED, 42, "POST /orders"),
        ),
        histograms=(
            HistogramReading(
                HistogramName.HTTP_REQUEST_DURATION,
                HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                (0, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0),
                4,
                180,
                5,
                100,
            ),
        ),
        gauges=(
            GaugeReading(
                GaugeName.PROCESS_CPU_RATIO,
                0.5,
                GaugeQuality.AVAILABLE,
            ),
            GaugeReading(
                GaugeName.PROCESS_MEMORY_RATIO,
                None,
                GaugeQuality.UNAVAILABLE,
            ),
        ),
    )

    encoded = encode_metrics_snapshot(snapshot)

    assert decode_metrics_snapshot(encoded) == snapshot


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (b'{"protocol_version":"x","protocol_version":"y"}', "duplicate_json_key"),
        (b"{", "invalid_json"),
        (
            (
                b'{"protocol_version":"atlas-richie.metrics/v2-draft",'
                b'"reporter_id":"r","startup_epoch":"00000000-0000-4000-8000-000000000001","sequence":1,'
                b'"captured_at":"2026-10-11T00:00:00.000000Z",'
                b'"capture_elapsed_ns":"0","counters":[],"histograms":[],"gauges":[]}'
            ),
            "unsupported_protocol",
        ),
        (
            b'{"protocol_version":"atlas-richie.metrics/v2","extra":1}',
            "invalid_snapshot_fields",
        ),
        (
            (
                b'{"protocol_version":"atlas-richie.metrics/v2",'
                b'"reporter_id":"r","startup_epoch":true,"sequence":1,'
                b'"captured_at":"2026-10-11T00:00:00.000000Z",'
                b'"capture_elapsed_ns":"0","counters":[],"histograms":[],"gauges":[]}'
            ),
            "invalid_startup_epoch",
        ),
        (
            (
                b'{"protocol_version":"atlas-richie.metrics/v2",'
                b'"reporter_id":"r","startup_epoch":"00000000-0000-4000-8000-000000000001","sequence":1,'
                b'"captured_at":"2026-10-11T00:00:00Z",'
                b'"capture_elapsed_ns":"0","counters":[],"histograms":[],"gauges":[]}'
            ),
            "invalid_captured_at",
        ),
        (
            (
                b'{"protocol_version":"atlas-richie.metrics/v2",'
                b'"reporter_id":"r","startup_epoch":"00000000-0000-4000-8000-000000000001","sequence":1,'
                b'"captured_at":"2026-10-11T00:00:00.000000Z",'
                b'"capture_elapsed_ns":"0","counters":[],"histograms":[],'
                b'"gauges":[{"name":"process_cpu_ratio","value":NaN,'
                b'"quality":"available"}]}'
            ),
            "invalid_json_number",
        ),
    ],
)
def test_codec_rejects_malformed_json_and_unknown_fields(
    payload: bytes, error_code: str
) -> None:
    with pytest.raises(MetricsV2ProtocolError, match=error_code):
        decode_metrics_snapshot(payload)


def test_codec_rejects_wrong_root_type_and_oversized_input() -> None:
    with pytest.raises(MetricsV2ProtocolError, match="invalid_snapshot_object"):
        decode_metrics_snapshot(b"[]")
    with pytest.raises(MetricsV2ProtocolError, match="payload_too_large"):
        decode_metrics_snapshot(b" " * (METRICS_V2_MAX_SIZE_BYTES + 1))


def test_codec_bounds_record_count_and_encoded_payload_size() -> None:
    counters = tuple(
        CounterReading(
            CounterName.HTTP_REQUESTS_COMPLETED,
            index,
            f"resource-{index}",
        )
        for index in range(METRICS_V2_MAX_RECORDS + 1)
    )
    with pytest.raises(MetricsV2ProtocolError, match="too_many_records"):
        encode_metrics_snapshot(_snapshot(counters=counters))

    large_counters = tuple(
        CounterReading(
            CounterName.HTTP_REQUESTS_COMPLETED,
            index,
            f"{index:03d}" + "r" * 197,
        )
        for index in range(METRICS_V2_MAX_RECORDS)
    )
    with pytest.raises(MetricsV2ProtocolError, match="payload_too_large"):
        encode_metrics_snapshot(_snapshot(counters=large_counters))

    valid_payload = json.loads(encode_metrics_snapshot(_snapshot()))
    assert valid_payload["protocol_version"] == "atlas-richie.metrics/v2"


def test_counter_rate_gap_over_ten_seconds_reestablishes_baseline() -> None:
    name = CounterName.HTTP_REQUESTS_COMPLETED
    previous = _snapshot(counters=(CounterReading(name, 5),))
    current = _snapshot(
        sequence=2,
        capture_elapsed_ns=12_000_000_000,
        counters=(CounterReading(name, 15),),
    )

    result = calculate_counter_rate(previous, current, name)

    assert result.state is CounterRateState.BASELINE_REQUIRED
    assert result.rate_per_second is None


def test_protocol_error_exposes_registered_stable_code() -> None:
    with pytest.raises(MetricsV2ProtocolError) as error:
        decode_metrics_snapshot(b"not-json")

    assert error.value.code.value == "invalid_json"
