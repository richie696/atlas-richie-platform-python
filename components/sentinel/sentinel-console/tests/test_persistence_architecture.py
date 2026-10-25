"""Guard the application-to-database dependency boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_APPLICATION_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "atlas_richie"
    / "sentinel_console"
    / "application"
)
_DATABASE_MODULE_ROOTS = frozenset(
    {
        "sqlalchemy",
        "sqlmodel",
        "sqlite3",
        "psycopg",
        "asyncmy",
        "aiomysql",
        "pymysql",
        "MySQLdb",
    }
)


def _forbidden_database_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                root = module.split(".", maxsplit=1)[0]
                if root in _DATABASE_MODULE_ROOTS or module.startswith(
                    "atlas_richie.sentinel_console.infrastructure"
                ):
                    violations.add(module)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            root = module.split(".", maxsplit=1)[0]
            imports_console_infrastructure = (
                module.startswith("atlas_richie.sentinel_console.infrastructure")
                or (node.level > 0 and root == "infrastructure")
            )
            if root in _DATABASE_MODULE_ROOTS or imports_console_infrastructure:
                violations.add(module)
    return violations


@pytest.mark.parametrize(
    "source_path",
    sorted(_APPLICATION_ROOT.glob("*.py")),
    ids=lambda path: path.name,
)
def test_application_modules_do_not_import_database_implementations(
    source_path: Path,
) -> None:
    database_dependencies = _forbidden_database_imports(
        source_path.read_text(encoding="utf-8")
    )

    assert not database_dependencies, (
        f"{source_path.name} imports database implementation modules: "
        f"{sorted(database_dependencies)}"
    )
