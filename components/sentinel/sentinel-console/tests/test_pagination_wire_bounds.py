"""Exercise pagination query bounds at each Python HTTP parser boundary."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from atlas_richie.sentinel_console.api.accounts import _parse_query as parse_accounts
from atlas_richie.sentinel_console.api.fleet_overview import _parse_query as parse_fleet
from atlas_richie.sentinel_console.api.incident_query_parsing import (
    parse_incident_timeline_query,
)
from atlas_richie.sentinel_console.api.instance_catalog import (
    _parse_query as parse_instances,
)
from atlas_richie.sentinel_console.api.instance_observation import (
    _parse_query as parse_instance_observation,
)
from atlas_richie.sentinel_console.api.metrics import _parse_query as parse_metrics
from atlas_richie.sentinel_console.api.query_parsing import parse_query_values
from atlas_richie.sentinel_console.api.rule_binding_parsing import (
    parse_rule_binding_query,
)
from atlas_richie.sentinel_console.api.rule_publication_receipts import (
    _page_arguments as parse_receipt_page,
)
from atlas_richie.sentinel_console.api.system_audit import _parse_query as parse_audit

_FROM = "2026-10-08T00:00:00.000Z"
_TO = "2026-10-08T00:01:00.000Z"
_PAGED_QUERIES: tuple[tuple[str, Callable[[Request], object], dict[str, str]], ...] = (
    (
        "fleet",
        parse_fleet,
        {
            "environmentId": "prod",
            "scope": "fleet",
            "from": _FROM,
            "to": _TO,
            "page": "1000000",
            "pageSize": "100",
            "search": "",
            "stepMs": "60000",
        },
    ),
    (
        "instances",
        parse_instances,
        {
            "environmentId": "prod",
            "scope": "fleet",
            "from": _FROM,
            "to": _TO,
            "page": "1000000",
            "pageSize": "100",
            "search": "",
            "attentionOnly": "false",
        },
    ),
    (
        "accounts",
        parse_accounts,
        {"page": "1000000", "pageSize": "100", "search": ""},
    ),
    (
        "system audit",
        parse_audit,
        {"start": _FROM, "end": _TO, "page": "1000000", "pageSize": "100"},
    ),
    (
        "rule bindings",
        parse_rule_binding_query,
        {"environmentId": "prod", "page": "1000000", "pageSize": "100"},
    ),
    (
        "publication receipts",
        parse_receipt_page,
        {"page": "1000000", "pageSize": "100"},
    ),
)


def _request_with_query(query: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": query,
            "path_params": {"instance_id": "instance-1"},
            "headers": [],
            "client": ("test", 1234),
            "server": ("test", 80),
        }
    )


def _request(parameters: dict[str, str]) -> Request:
    return _request_with_query(urlencode(parameters).encode("ascii"))


@pytest.mark.parametrize(
    ("query", "expected"),
    (
        (b"page=2&search=", {"page": "2", "search": ""}),
        (b"page=2&%70age=3&search=", None),
        (b"page=2&search=&unexpected=yes", None),
        (b"page=2", None),
    ),
)
def test_strict_query_values_reject_decoded_duplicates_unknown_and_missing_keys(
    query: bytes, expected: dict[str, str] | None
) -> None:
    request = _request_with_query(query)
    if expected is None:
        with pytest.raises(ValueError):
            parse_query_values(
                request,
                frozenset({"page", "search"}),
                frozenset({"status"}),
            )
        return

    assert (
        parse_query_values(
            request,
            frozenset({"page", "search"}),
            frozenset({"status"}),
        )
        == expected
    )


def _is_rejected(result: object) -> bool:
    return result is None


@pytest.mark.parametrize(("name", "parser", "parameters"), _PAGED_QUERIES)
def test_paged_query_parsers_accept_wire_maximums(
    name: str,
    parser: Callable[[Request], object],
    parameters: dict[str, str],
) -> None:
    result = parser(_request(parameters))

    assert not _is_rejected(result), name
    if isinstance(result, tuple):
        assert result == (1_000_000, 100), name
    else:
        assert getattr(result, "page", None) == 1_000_000, name
        assert getattr(result, "page_size", None) == 100, name


@pytest.mark.parametrize(("name", "parser", "parameters"), _PAGED_QUERIES)
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("page", "0"),
        ("page", "1000001"),
        ("pageSize", "0"),
        ("pageSize", "101"),
    ),
)
def test_paged_query_parsers_reject_values_above_wire_maximum(
    name: str,
    parser: Callable[[Request], object],
    parameters: dict[str, str],
    field: str,
    value: str,
) -> None:
    changed = {**parameters, field: value}

    try:
        result = parser(_request(changed))
    except (TypeError, ValueError):
        return

    assert _is_rejected(result), (name, field, result)


@pytest.mark.parametrize(
    ("name", "parser", "parameters", "field"),
    (
        (name, parser, parameters, field)
        for name, parser, parameters in _PAGED_QUERIES
        for field in ("page", "pageSize")
        if field in parameters
    ),
)
def test_paged_query_parsers_reject_noncanonical_integer_values(
    name: str,
    parser: Callable[[Request], object],
    parameters: dict[str, str],
    field: str,
) -> None:
    changed = {**parameters, field: "01"}

    try:
        result = parser(_request(changed))
    except (TypeError, ValueError):
        return

    assert _is_rejected(result), (name, field, result)


def test_incident_parser_accepts_maximum_page_size() -> None:
    query = parse_incident_timeline_query(
        _request(
            {
                "environmentId": "prod",
                "scope": "fleet",
                "from": _FROM,
                "to": _TO,
                "pageSize": "100",
            }
        )
    )

    assert query.page_size == 100


@pytest.mark.parametrize("page_size", ("0", "101"))
def test_incident_parser_rejects_page_size_outside_wire_bounds(page_size: str) -> None:
    with pytest.raises(ValueError):
        parse_incident_timeline_query(
            _request(
                {
                    "environmentId": "prod",
                    "scope": "fleet",
                    "from": _FROM,
                    "to": _TO,
                    "pageSize": page_size,
                }
            )
        )


def test_incident_parser_rejects_noncanonical_page_size() -> None:
    with pytest.raises(ValueError):
        parse_incident_timeline_query(
            _request(
                {
                    "environmentId": "prod",
                    "scope": "fleet",
                    "from": _FROM,
                    "to": _TO,
                    "pageSize": "01",
                }
            )
        )


@pytest.mark.parametrize(
    ("parser", "parameters"),
    (
        (
            parse_metrics,
            {
                "environmentId": "prod",
                "scope": "fleet",
                "from": _FROM,
                "to": _TO,
                "metrics": "http_qps",
                "stepMs": "060000",
            },
        ),
        (
            parse_instance_observation,
            {
                "environmentId": "prod",
                "appId": "checkout",
                "scope": "process",
                "from": _FROM,
                "to": _TO,
                "processEpoch": "epoch-1",
                "stepMs": "060000",
            },
        ),
    ),
)
def test_observation_query_parsers_reject_noncanonical_step_ms(
    parser: Callable[[Request], object], parameters: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        parser(_request(parameters))
