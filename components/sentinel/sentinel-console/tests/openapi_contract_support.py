"""Helpers for asserting live Console HTTP responses against the OpenAPI contract."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from httpx import Response
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "protocol"
_OPENAPI_PATH /= "console-api.openapi.json"
_OPENAPI_URI = _OPENAPI_PATH.as_uri()


@cache
def _openapi_contract() -> tuple[dict[str, Any], Registry[Any]]:
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    resource = Resource.from_contents(
        document,
        default_specification=DRAFT202012,
    )
    return document, Registry().with_resource(_OPENAPI_URI, resource)


def assert_openapi_response(operation_id: str, response: Response) -> None:
    """Validate an actual HTTP response body and declared headers for one operation."""
    document, registry = _openapi_contract()
    operation = _find_operation(document, operation_id)
    response_contract = operation["responses"].get(str(response.status_code))
    assert response_contract is not None, (
        f"{operation_id} returned undocumented HTTP {response.status_code}"
    )

    for name, header_contract in response_contract.get("headers", {}).items():
        value = response.headers.get(name)
        if header_contract.get("required"):
            assert value is not None, f"{operation_id} omitted required header {name}"
        if value is not None and "schema" in header_contract:
            _assert_schema(
                operation_id,
                f"response header {name}",
                header_contract["schema"],
                value,
                registry,
            )

    content = response_contract.get("content", {})
    if not content:
        assert not response.content, f"{operation_id} returned an undocumented body"
        return

    assert "application/json" in content, (
        f"{operation_id} does not declare application/json response content"
    )
    _assert_schema(
        operation_id,
        "response body",
        content["application/json"]["schema"],
        response.json(),
        registry,
    )


def _find_operation(document: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for path_item in document["paths"].values():
        for operation in path_item.values():
            if operation.get("operationId") == operation_id:
                return operation
    raise AssertionError(f"OpenAPI operation not found: {operation_id}")


def _assert_schema(
    operation_id: str,
    boundary: str,
    schema: dict[str, Any],
    instance: Any,
    registry: Registry[Any],
) -> None:
    schema_with_base = {"$id": _OPENAPI_URI, **schema}
    validator = Draft202012Validator(
        schema_with_base,
        format_checker=FormatChecker(),
        registry=registry,
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (tuple(map(str, error.absolute_path)), error.message),
    )
    assert not errors, (
        f"{operation_id} {boundary} violates Console OpenAPI schema:\n"
        + "\n".join(
            f"  {'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
            for error in errors
        )
    )
