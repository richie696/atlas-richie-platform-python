"""Guard the P0/P1 no-framework-core dependency promise."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_ROOTS = frozenset(
    {
        "fastapi",
        "django",
        "flask",
        "starlette",
        "pydantic",
        "sqlalchemy",
        "httpx",
        "redis",
        "opentelemetry",
        "jwt",
    }
)


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    source_roots = [
        root / "foundation" / "contracts" / "src",
        root / "components" / "mcp" / "src",
        root / "components" / "oauth" / "src",
    ]
    violations: list[str] = []
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            forbidden = imported_roots(path).intersection(FORBIDDEN_ROOTS)
            violations.extend(f"{path}: {name}" for name in sorted(forbidden))
    if violations:
        print("forbidden core imports:", *violations, sep="\n")
        return 1
    print("core dependency import policy: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
