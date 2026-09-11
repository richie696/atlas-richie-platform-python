"""Sync every `pyproject.toml` against the central `versions.toml`.

The single source of truth is the repo-root `versions.toml`. This
script:

1. Reads `versions.toml` (the canonical map of package name → version).
2. Discovers every `pyproject.toml` under the repo (skipping
   `.venv`, `dist`, `node_modules`).
3. For each `pyproject.toml`:
   - Sets the `version = "X.Y.Z"` field for the package's own name.
   - Updates every `atlas-richie-*` dependency to
     `>=X.Y.Z,<X.(Y+1).0` (the standard Python "next-minor"
     compatible-release form).
4. Verifies that every `atlas-richie-*` package referenced in any
   `pyproject.toml` is declared in `versions.toml`. Missing entries
   fail loudly with a clear error.

This mirrors the Maven `<revision>` variable: a bump in
`versions.toml` is the only place to edit; this script propagates
it everywhere.

**Implementation note**: we use targeted text manipulation (regex
on the raw `pyproject.toml` text) rather than `tomllib`+`tomli_w`.
The latter would re-emit the whole file and lose the original
formatting + comments + drop tables whose names contain dashes
(`[tool.uv.build-backend]` is an example we've hit). The text-based
approach only touches the `version = "..."` line inside `[project]`
and the `dependencies = [...]` array — everything else is byte-
preserved.

Usage:
    python tools/sync_versions.py          # sync in place
    python tools/sync_versions.py --check  # verify only (exit 1 on drift)
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_FILE = REPO_ROOT / "versions.toml"

EXCLUDE_DIRS = {".venv", "dist", "node_modules", ".git", "__pycache__"}


def load_versions() -> dict[str, str]:
    """Read `versions.toml` and return the package name → version map."""
    data = tomllib.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
    versions = data.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise SystemExit(
            "versions.toml is missing a non-empty [versions] table"
        )
    for name, version in versions.items():
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            raise SystemExit(
                f"versions.toml: {name!r} has non-semver version {version!r}"
            )
    return dict(versions)


def discover_pyprojects() -> list[Path]:
    """Find every `pyproject.toml` under the repo."""
    out: list[Path] = []
    for path in REPO_ROOT.rglob("pyproject.toml"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def read_pyproject_name_and_version(path: Path) -> tuple[str, str | None]:
    """Read the `name` and `version` from a `pyproject.toml`."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    name = project.get("name")
    if not isinstance(name, str):
        raise SystemExit(f"{path}: missing [project] name")
    return name, project.get("version")


def _split_constraint(dep: str) -> tuple[str, str | None]:
    """Split a dep string like `atlas-richie-contracts>=0.1.0,<0.2.0`
    into the package name and a stripped constraint (or None for bare
    name)."""
    match = re.match(r"^([A-Za-z0-9._-]+)(.*)$", dep.strip())
    if not match:
        return dep.strip(), None
    return match.group(1), match.group(2).strip() or None


def _next_minor(version: str) -> str:
    """`0.1.0` -> `0.2.0`; `0.10.0` -> `0.11.0`; `1.2.3` -> `2.0.0`."""
    major, minor, _patch = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def _expected_constraint(dep_name: str, versions: dict[str, str]) -> str:
    """Build the expected `>=X.Y.Z,<X.(Y+1).0` constraint for a dep."""
    if dep_name not in versions:
        raise SystemExit(
            f"dependency {dep_name!r} is not declared in versions.toml; "
            f"add it before running sync"
        )
    current = versions[dep_name]
    upper = _next_minor(current)
    return f">={current},<{upper}"


def _set_self_version(text: str, new_version: str) -> tuple[str, list[str]]:
    """Update the package's own `version = "X.Y.Z"` line.

    The line lives inside `[project]`. We use a regex that matches
    the FIRST `version = "..."` line (the build-backend table has no
    version field, so this is unambiguous in our codebase).
    """
    changes: list[str] = []
    new_line = f'version = "{new_version}"'
    pattern = re.compile(
        r'^(?P<indent>[ \t]*)version\s*=\s*"[^"]*"\s*$',
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m is None:
        return text, changes
    old_line = m.group(0)
    new_full = f'{m.group("indent")}{new_line}'
    if old_line != new_full:
        changes.append(
            f"self version: {old_line.strip()!r} -> {new_full.strip()!r}"
        )
        text = text[: m.start()] + new_full + text[m.end():]
    return text, changes


def _rewrite_deps_block(text: str, versions: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite the `dependencies = [...]` block: every
    `atlas-richie-*` entry gets the canonical `>=X.Y.Z,<X.(Y+1).0`
    constraint. Single-line and multi-line forms are both supported.
    Every other dep (third-party, non-`atlas-richie-*` workspace
    members) is left untouched.
    """
    changes: list[str] = []
    # Match the `dependencies = [` opening, then capture everything
    # up to the matching `]`. The non-greedy `[^\[\]]*?` stops at the
    # first `]` because TOML dep arrays don't contain nested `[` or `]`.
    pattern = re.compile(
        r'^(?P<indent>[ \t]*)dependencies\s*=\s*\[(?P<inner>[^\[\]]*?)\]',
        re.MULTILINE,
    )
    dep_pat = re.compile(
        r'"(?P<full>(?P<name>[A-Za-z0-9._-]+)(?P<constraint>[^"]*))"'
    )

    def rewrite(match: re.Match[str]) -> str:
        inner = match.group("inner")
        # Detect format: multi-line if there's a newline before any
        # quoted string.
        is_multiline = "\n" in inner
        if is_multiline:
            # Split on commas, preserving structure.
            new_inner = dep_pat.sub(
                lambda m: _replace_dep(m, versions), inner
            )
        else:
            new_inner = dep_pat.sub(
                lambda m: _replace_dep(m, versions), inner
            )
        if new_inner != inner:
            # Re-emit in the same form (single-line vs multi-line).
            if is_multiline:
                # Pull out all the (now-updated) dep strings, one
                # per line, indented with 2 spaces.
                items = re.findall(r'"[^"]*"', new_inner)
                rendered = "[\n  " + ",\n  ".join(items) + ",\n]"
            else:
                items = re.findall(r'"[^"]*"', new_inner)
                rendered = "[" + ", ".join(items) + "]"
            return f'{match.group("indent")}dependencies = {rendered}'
        return match.group(0)

    def _replace_dep(m: re.Match[str], versions: dict[str, str]) -> str:
        name = m.group("name")
        if not name.startswith("atlas-richie-") or name not in versions:
            return m.group(0)
        new_constraint = _expected_constraint(name, versions)
        new_dep = f"{name}{new_constraint}"
        if new_dep != m.group("full"):
            changes.append(
                f"dep {name}: {m.group('full')!r} -> {new_dep!r}"
            )
        return f'"{new_dep}"'

    return pattern.sub(rewrite, text), changes


def update_pyproject(
    path: Path,
    self_name: str,
    self_version: str,
    versions: dict[str, str],
) -> list[str]:
    """Update a single `pyproject.toml` in place. Returns a list of
    human-readable change summaries (empty if no changes)."""
    original = path.read_text(encoding="utf-8")
    text, version_changes = _set_self_version(original, self_version)
    text, dep_changes = _rewrite_deps_block(text, versions)

    if text != original:
        path.write_text(text, encoding="utf-8")
    return version_changes + dep_changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify consistency without writing (exit 1 on drift)",
    )
    args = parser.parse_args()

    versions = load_versions()
    print(f"versions.toml: {len(versions)} packages declared")

    pyprojects = discover_pyprojects()
    print(f"discovered {len(pyprojects)} pyproject.toml files")

    declared = set(versions)
    referenced: set[str] = set()
    drift_count = 0

    for path in pyprojects:
        try:
            self_name, current_version = read_pyproject_name_and_version(path)
        except SystemExit as exc:
            # The root `pyproject.toml` is a workspace aggregator with
            # no `[project] name` — that's fine, skip it.
            if "missing [project] name" in str(exc):
                continue
            raise
        referenced.add(self_name)

        if self_name not in versions:
            print(
                f"  ERROR  {path.relative_to(REPO_ROOT)}: "
                f"package {self_name!r} not declared in versions.toml"
            )
            drift_count += 1
            continue

        target_version = versions[self_name]

        if args.check:
            if current_version != target_version:
                print(
                    f"  DRIFT   {path.relative_to(REPO_ROOT)}: "
                    f"{self_name} {current_version} -> {target_version}"
                )
                drift_count += 1
        else:
            changes = update_pyproject(
                path, self_name, target_version, versions
            )
            if changes:
                print(
                    f"  updated {path.relative_to(REPO_ROOT)} ({self_name}):"
                )
                for change in changes:
                    print(f"    - {change}")

    undeclared = referenced - declared
    if undeclared:
        print(f"  ERROR  undeclared packages: {sorted(undeclared)}")
        drift_count += 1

    if args.check:
        if drift_count:
            print(f"\nFAIL: {drift_count} drift(s) detected")
            return 1
        print("\nOK: all pyproject.toml files are in sync with versions.toml")
        return 0

    print(
        f"\nDone. {len(pyprojects)} pyproject.toml files synced to versions.toml."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
