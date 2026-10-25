"""Keep every published Console operation in runtime response tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_OPENAPI_PATH = _TESTS_DIR.parents[1] / "docs" / "protocol" / "console-api.openapi.json"


def test_every_openapi_operation_has_a_runtime_response_assertion() -> None:
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation_ids = {
        operation["operationId"]
        for path_item in document["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    asserted_operation_ids = {
        operation_id
        for path in _TESTS_DIR.glob("test_*.py")
        if path != Path(__file__)
        for operation_id in _asserted_operation_ids(path)
    }

    assert asserted_operation_ids <= operation_ids, (
        "Tests reference operation IDs absent from Console OpenAPI: "
        f"{sorted(asserted_operation_ids - operation_ids)}"
    )
    assert operation_ids <= asserted_operation_ids, (
        "Console OpenAPI operations need runtime response schema assertions: "
        f"{sorted(operation_ids - asserted_operation_ids)}"
    )


def _asserted_operation_ids(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        call.args[0].value
        for call in ast.walk(module)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "assert_openapi_response"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }
