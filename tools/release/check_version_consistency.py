"""Wheel / sdist / pyproject.toml 三产物版本一致性门禁。

PLANNING.md §M0.4 Exit Criteria: 主 wheel `atlas-richie-sentinel` 发布前
必须验证 wheel `*.dist-info/METADATA` + sdist `PKG-INFO` + 源
`pyproject.toml [project] version` + `name` 四者全部一致。

理由:

- `uv publish` 自身不校验包内 version 与构建元数据的一致性,只上传。
- 仓库根 `dist/` 已堆积 cache / secret / sentinel 旧 wheel 产物,直接
  扫描会误判 + 误发布。
- 专用干净目录 + `--clear` 重建保证"恰好 1 wheel + 1 sdist"。

PEP 625: 本仓所有 sdist / wheel 文件名按 `atlas_richie_sentinel-*`
规范化(连字符转下划线),但 METADATA / PKG-INFO 内部的 `Name:` 字段
保留原始 `atlas-richie-sentinel` 字符串。

用法:

    # 推荐:专用目录 + 严格门禁
    rm -rf /tmp/atlas-richie-sentinel-release
    uv build --package atlas-richie-sentinel \\
             --out-dir /tmp/atlas-richie-sentinel-release \\
             --clear \\
             --no-create-gitignore
    python tools/release/check_version_consistency.py /tmp/atlas-richie-sentinel-release
    uv publish /tmp/atlas-richie-sentinel-release/*.whl \\
               /tmp/atlas-richie-sentinel-release/*.tar.gz

退出码:

    0 — 四处完全一致(包名 + 版本)
    1 — 冲突(数量错 / 文件名包名错 / 三者版本不等 / 三者 Name 不等)
    2 — 工具内部错误
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Optional

EXPECTED_NAME = "atlas-richie-sentinel"
"""项目原始包名(wheel 内部 Name 字段 / pyproject.toml [project] name)。"""

NAME_SLUG = "atlas_richie_sentinel"
"""PEP 625 规范化文件名 slug(用于校验 wheel / sdist 文件名前缀)。"""

DEFAULT_PYPROJECT = Path("components/sentinel/sentinel/pyproject.toml")
"""默认读取的 pyproject.toml 路径(可用 --pyproject 覆盖)。"""

_VERSION_RE = re.compile(r"^Version:\s*(\S+)\s*$", re.MULTILINE)
_NAME_RE = re.compile(r"^Name:\s*(\S+)\s*$", re.MULTILINE)


def _read_pyproject(pyproject: Path) -> tuple[Optional[str], Optional[str]]:
    """Parse ``[project] name`` and ``[project] version`` from pyproject.toml.

    Minimal regex parser; the file is hand-written so we don't need a TOML
    dependency. Fails closed (returns ``None``) on parse error.
    """
    text = pyproject.read_text(encoding="utf-8")
    # Capture the first [project] block
    m = re.search(r"\[project\](.*?)(?:^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None, None
    block = m.group(1)
    name_match = re.search(r"^name\s*=\s*['\"]([^'\"]+)['\"]", block, re.MULTILINE)
    version_match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]", block, re.MULTILINE)
    return (name_match.group(1) if name_match else None,
            version_match.group(1) if version_match else None)


def _read_wheel_metadata(whl: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (Name, Version) from a wheel's ``*.dist-info/METADATA``."""
    with zipfile.ZipFile(whl) as zf:
        for entry in zf.namelist():
            if entry.endswith(".dist-info/METADATA"):
                with zf.open(entry) as f:
                    text = f.read().decode("utf-8", errors="replace")
                name = _NAME_RE.search(text)
                version = _VERSION_RE.search(text)
                return (name.group(1) if name else None,
                        version.group(1) if version else None)
    return None, None


def _read_sdist_metadata(sdist: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (Name, Version) from an sdist's ``PKG-INFO``."""
    with tarfile.open(sdist, "r:gz") as tf:
        for member in tf.getmembers():
            if member.isfile() and member.name.endswith("/PKG-INFO"):
                f = tf.extractfile(member)
                if f is None:
                    continue
                text = f.read().decode("utf-8", errors="replace")
                name = _NAME_RE.search(text)
                version = _VERSION_RE.search(text)
                return (name.group(1) if name else None,
                        version.group(1) if version else None)
    return None, None


def check(release_dir: Path, pyproject: Path) -> tuple[int, list[str]]:
    """Run the consistency check; return ``(exit_code, report_lines)``."""
    report: list[str] = []

    if not release_dir.is_dir():
        report.append(f"FAIL: release directory does not exist: {release_dir}")
        return 1, report

    wheels = sorted(release_dir.glob("*.whl"))
    sdists = sorted(release_dir.glob("*.tar.gz"))
    others = [p for p in release_dir.iterdir()
              if p.is_file() and not (p.name.endswith(".whl") or p.name.endswith(".tar.gz"))]

    # 1) Exactly one wheel + one sdist
    if others:
        report.append(
            f"FAIL: release dir contains {len(others)} non-wheel/non-sdist file(s):"
        )
        for p in others:
            report.append(f"  - {p.name}")
        return 1, report
    if len(wheels) != 1:
        report.append(
            f"FAIL: expected exactly 1 wheel, found {len(wheels)}: "
            f"{[p.name for p in wheels]}"
        )
        return 1, report
    if len(sdists) != 1:
        report.append(
            f"FAIL: expected exactly 1 sdist, found {len(sdists)}: "
            f"{[p.name for p in sdists]}"
        )
        return 1, report

    whl, sdist = wheels[0], sdists[0]
    report.append(f"wheel:  {whl.name}")
    report.append(f"sdist:  {sdist.name}")

    # 2) Filename slug check (PEP 625)
    if not whl.name.startswith(f"{NAME_SLUG}-"):
        report.append(
            f"FAIL: wheel filename does not start with '{NAME_SLUG}-': {whl.name}"
        )
        return 1, report
    if not sdist.name.startswith(f"{NAME_SLUG}-"):
        report.append(
            f"FAIL: sdist filename does not start with '{NAME_SLUG}-': {sdist.name}"
        )
        return 1, report

    # 3) Read all three sources
    pp_name, pp_version = _read_pyproject(pyproject)
    if pp_name is None or pp_version is None:
        report.append(f"FAIL: could not parse [project] from {pyproject}")
        return 1, report
    whl_name, whl_version = _read_wheel_metadata(whl)
    sd_name, sd_version = _read_sdist_metadata(sdist)
    if whl_name is None or whl_version is None:
        report.append(f"FAIL: could not read wheel METADATA from {whl.name}")
        return 1, report
    if sd_name is None or sd_version is None:
        report.append(f"FAIL: could not read sdist PKG-INFO from {sdist.name}")
        return 1, report

    report.append(f"pyproject:  name={pp_name!r}  version={pp_version!r}")
    report.append(f"wheel:      name={whl_name!r}  version={whl_version!r}")
    report.append(f"sdist:      name={sd_name!r}  version={sd_version!r}")

    # 4) Cross-check Name + Version
    names = {pp_name, whl_name, sd_name}
    versions = {pp_version, whl_version, sd_version}
    if names != {EXPECTED_NAME}:
        report.append(
            f"FAIL: Name mismatch — expected all three == {EXPECTED_NAME!r}, "
            f"got {sorted(names)}"
        )
        return 1, report
    if len(versions) != 1:
        report.append(
            f"FAIL: Version mismatch — pyproject={pp_version!r} "
            f"wheel={whl_version!r} sdist={sd_version!r}"
        )
        return 1, report

    report.append("")
    report.append(
        f"OK: name={pp_name!r} version={pp_version!r} consistent across "
        f"pyproject.toml, wheel METADATA, sdist PKG-INFO"
    )
    return 0, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse_for_check()
    args = parser.parse_args(argv)

    if not args.release_dir.is_dir():
        print(f"ERROR: release dir does not exist: {args.release_dir}", file=sys.stderr)
        return 2
    if not args.pyproject.is_file():
        print(f"ERROR: pyproject not found: {args.pyproject}", file=sys.stderr)
        return 2

    code, report = check(args.release_dir, args.pyproject)
    print("\n".join(report))
    return code


def argparse_for_check():
    import argparse
    parser = argparse.ArgumentParser(
        description="Check wheel / sdist / pyproject.toml version consistency "
                    "for atlas-richie-sentinel."
    )
    parser.add_argument(
        "release_dir",
        type=Path,
        help="Directory containing exactly 1 wheel + 1 sdist "
             "(use --clear --no-create-gitignore when building).",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT,
        help=f"Path to pyproject.toml (default: {DEFAULT_PYPROJECT})",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
