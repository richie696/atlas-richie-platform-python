"""Tests for the Console's strict UTC-millisecond timestamp wire format."""

from datetime import datetime, timedelta, timezone

import pytest

from atlas_richie.sentinel_console.api.query_parsing import parse_utc_timestamp
from atlas_richie.sentinel_console.api.system_observation_access import utc_timestamp


def test_utc_timestamp_normalizes_aware_instants_to_utc_milliseconds() -> None:
    value = datetime(
        2026,
        10,
        10,
        15,
        30,
        45,
        456789,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert utc_timestamp(value) == "2026-10-10T10:00:45.456Z"


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (datetime(1970, 1, 1, tzinfo=timezone.utc), "1970-01-01T00:00:00.000Z"),
        (
            datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc),
            "9999-12-31T23:59:59.999Z",
        ),
    ),
)
def test_utc_timestamp_accepts_wire_year_boundaries(
    value: datetime, expected: str
) -> None:
    assert utc_timestamp(value) == expected


def test_utc_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_timestamp(datetime(2026, 10, 10, 10, 0, 0))


def test_utc_timestamp_rejects_utc_year_outside_wire_range() -> None:
    value = datetime(1970, 1, 1, tzinfo=timezone(timedelta(hours=1)))

    with pytest.raises(ValueError, match="1970 through 9999"):
        utc_timestamp(value)


def test_utc_timestamp_rejects_utc_conversion_overflow() -> None:
    value = datetime(
        9999,
        12,
        31,
        23,
        59,
        tzinfo=timezone(-timedelta(hours=1)),
    )

    with pytest.raises(ValueError, match="1970 through 9999"):
        utc_timestamp(value)


def test_parse_utc_timestamp_accepts_wire_timestamp_as_utc() -> None:
    value = parse_utc_timestamp("2026-10-10T10:00:45.456Z")

    assert value == datetime(2026, 10, 10, 10, 0, 45, 456000, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    (
        ("1970-01-01T00:00:00.000Z", datetime(1970, 1, 1, tzinfo=timezone.utc)),
        (
            "9999-12-31T23:59:59.999Z",
            datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc),
        ),
        (
            "2000-02-29T10:00:45.456Z",
            datetime(2000, 2, 29, 10, 0, 45, 456000, tzinfo=timezone.utc),
        ),
    ),
)
def test_parse_utc_timestamp_accepts_wire_boundaries_and_gregorian_leap_year(
    wire_value: str, expected: datetime
) -> None:
    assert parse_utc_timestamp(wire_value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "2026-10-10T10:00:45Z",
        "2026-10-10T10:00:45.456+00:00",
        "2026-10-10T10:00:45.456789Z",
        "1969-12-31T23:59:59.999Z",
        "0001-01-01T00:00:00.000Z",
        "2026-02-30T10:00:45.456Z",
        "2100-02-29T10:00:45.456Z",
    ),
)
def test_parse_utc_timestamp_rejects_values_outside_wire_contract(value: str) -> None:
    with pytest.raises(ValueError):
        parse_utc_timestamp(value)
