"""Keep synchronous rule-binding registration aligned with its wire contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

from atlas_richie.sentinel_console.api.rule_binding_registration_parsing import (
    _REQUEST_KEY as _BINDING_REQUEST_KEY_PATTERN,
)

_OPENAPI_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "protocol"
    / "console-api.openapi.json"
)


def test_rule_binding_registration_idempotency_contract_is_explicit() -> None:
    """The synchronous create endpoint binds one header key to its body key."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = document["paths"]["/api/v1/rulesets"]["post"]

    assert operation["operationId"] == "createRuleBinding"
    assert operation["x-unknown-outcome"] is True

    idempotency_headers = [
        parameter
        for parameter in operation["parameters"]
        if parameter.get("in") == "header"
        and parameter.get("name") == "idempotency-key"
    ]
    assert len(idempotency_headers) == 1
    idempotency_header = idempotency_headers[0]
    assert idempotency_header["required"] is True

    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["additionalProperties"] is False
    assert "requestKey" in body_schema["required"]
    request_key_schema = body_schema["properties"]["requestKey"]

    header_schema = {
        key: value
        for key, value in idempotency_header["schema"].items()
        if key != "$schema"
    }
    assert request_key_schema == header_schema
    assert request_key_schema["minLength"] == 1
    assert request_key_schema["maxLength"] == 128
    wire_patterns = tuple(
        constraint["pattern"]
        for constraint in request_key_schema["allOf"]
        if "pattern" in constraint
    )
    for value, expected in (
        ("a", True),
        ("_-.:", True),
        ("a" * 128, True),
        ("a" * 129, False),
        ("bad/key", False),
    ):
        wire_accepts = (
                request_key_schema["minLength"]
                <= len(value)
                <= request_key_schema["maxLength"]
                and all(re.search(pattern, value) for pattern in wire_patterns)
        )
        python_accepts = _BINDING_REQUEST_KEY_PATTERN.fullmatch(value) is not None
        assert wire_accepts is expected, value[:16]
        assert python_accepts is wire_accepts, value[:16]


def test_binding_creation_and_mutation_have_distinct_recovery_contracts() -> None:
    """Creation permits identical replay; async mutations require operation lookup."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    creation = document["paths"]["/api/v1/rulesets"]["post"]
    mutation = document["paths"]["/api/v1/rulesets/{bindingId}/commands"]["post"]
    lookup = document["paths"][
        "/api/v1/rulesets/{bindingId}/operations/{requestKey}"
    ]["get"]

    assert creation["x-unknown-outcome"] is True
    creation_rules = creation["x-semantic-rules"]
    assert any("idempotent for the same actor" in rule for rule in creation_rules)
    assert any(
        "identical retry returns the original binding" in rule
        for rule in creation_rules
    )
    assert mutation["x-unknown-outcome"] is True
    mutation_rules = mutation["x-semantic-rules"]
    assert any("never replayed" in rule for rule in mutation_rules)
    assert lookup["operationId"] == "readRuleOperation"

