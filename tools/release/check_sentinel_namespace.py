"""Sentinel 命名空间所有权检查工具。

PLANNING.md §M0.8.1: 主 wheel `atlas-richie-sentinel` 独占
`atlas_richie.sentinel` 命名空间。任何其它 wheel(扩展或第三方)都不能
在该命名空间下放置 .py 文件,否则会导致:

- wheel 安装顺序敏感(后装的 wheel 覆盖先装的)
- 静态分析冲突
- 用户在两个 wheel 间出现不可预测行为

实现策略:扫所有本地 built wheel(从 `versions.toml` + workspace
`pyproject.toml` 推断),解 `.dist-info/RECORD` 找 wheel 内的
`atlas_richie/sentinel/` 路径,统计每个 wheel 在该命名空间下
贡献的文件数。**仅主 wheel 允许非零**;其它 wheel 非零 → 退出码 1。

用法:

    python tools/release/check_sentinel_namespace.py

    # 显式指定 wheel 目录(默认 dist/)
    python tools/release/check_sentinel_namespace.py --dist-dir dist

    # 或指定一个 built wheel 列表
    python tools/release/check_sentinel_namespace.py --wheels \
        dist/atlas_richie_sentinel-0.2.0-py3-none-any.whl \
        dist/atlas_richie_sentinel_adapter_asgi-0.2.0-py3-none-any.whl

退出码:

    0 — 主 wheel 独占命名空间,其它 wheel 贡献 0 个文件
    1 — 发现命名空间冲突,报告里列出冲突源
    2 — 工具内部错误(wheel 解析失败 / 找不到任何 wheel)
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

OWNED_BY = "atlas-richie-sentinel"
"""唯一允许在 ``atlas_richie/sentinel/`` 写文件的主 wheel 名。"""

NAMESPACE_PREFIX = "atlas_richie/sentinel/"
"""被保护的命名空间前缀(以 ``/`` 结尾,避免误匹配)。"""


def _iter_dist_wheels(dist_dir: Path) -> Iterable[Path]:
    """Yield wheel files under ``dist_dir`` matching Sentinel-related names.

    Filters to wheels whose name starts with ``atlas_richie_sentinel`` so
    that the check is focused and fast. Non-Sentinel wheels in the same
    directory are skipped.
    """
    if not dist_dir.is_dir():
        return
    for whl in sorted(dist_dir.glob("atlas_richie_sentinel*.whl")):
        yield whl


def _files_in_namespace(whl: Path) -> list[str]:
    """Return all entries inside ``atlas_richie/sentinel/`` for a wheel.

    Reads ``.dist-info/RECORD`` (no extraction needed) and filters paths
    whose top-level matches the Sentinel namespace.
    """
    matched: list[str] = []
    with zipfile.ZipFile(whl) as zf:
        for name in zf.namelist():
            if name.startswith(NAMESPACE_PREFIX) and not name.endswith("/"):
                matched.append(name)
    return matched


def _wheel_name(whl: Path) -> str:
    """Best-effort wheel distribution name from filename.

    PEP 427 wheel filenames are
    ``{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl``.
    The first two ``-``-separated tokens (joined by ``-``) are the
    distribution name (which may itself contain ``-``). We use the
    ``.dist-info/METADATA`` Name field for the canonical name when
    available, falling back to the filename stem.
    """
    # Prefer canonical name from METADATA
    try:
        with zipfile.ZipFile(whl) as zf:
            for entry in zf.namelist():
                if entry.endswith(".dist-info/METADATA"):
                    with zf.open(entry) as f:
                        for line in f:
                            line = line.decode("utf-8", errors="replace").rstrip()
                            if line.startswith("Name:"):
                                return line.split(":", 1)[1].strip()
    except (KeyError, zipfile.BadZipFile):
        pass
    # Fallback: filename stem
    return whl.name.split("-", 1)[0]


def check(wheels: Iterable[Path]) -> tuple[int, list[str]]:
    """Run the namespace ownership check.

    Returns ``(exit_code, report_lines)``.
    """
    contributors: dict[str, list[str]] = defaultdict(list)
    for whl in wheels:
        files = _files_in_namespace(whl)
        if not files:
            continue
        contributors[_wheel_name(whl)].extend([f"{whl.name}: {p}" for p in files])

    report: list[str] = []
    if not contributors:
        report.append("OK: no wheel currently claims the atlas_richie.sentinel namespace")
        return 0, report

    if set(contributors.keys()) == {OWNED_BY}:
        n = sum(len(v) for v in contributors.values())
        report.append(
            f"OK: {OWNED_BY} exclusively owns the atlas_richie.sentinel namespace "
            f"({n} files)"
        )
        return 0, report

    report.append("FAIL: atlas_richie.sentinel namespace is contested:")
    for wheel, entries in sorted(contributors.items()):
        marker = " (OWNER)" if wheel == OWNED_BY else " (CONFLICT)"
        report.append(f"  - {wheel}{marker}: {len(entries)} files")
        for entry in entries[:10]:
            report.append(f"      {entry}")
        if len(entries) > 10:
            report.append(f"      ... and {len(entries) - 10} more")
    report.append("")
    report.append(
        f"Only {OWNED_BY} may write into atlas_richie/sentinel/. "
        f"Other wheels must move their code under a different sub-package."
    )
    return 1, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that atlas_richie.sentinel is owned exclusively by atlas-richie-sentinel."
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path("dist"),
        help="Directory to scan for built wheels (default: dist/)",
    )
    parser.add_argument(
        "--wheels",
        type=Path,
        nargs="*",
        default=None,
        help="Explicit list of wheel files to check (overrides --dist-dir)",
    )
    args = parser.parse_args(argv)

    if args.wheels:
        wheels: list[Path] = list(args.wheels)
    else:
        wheels = list(_iter_dist_wheels(args.dist_dir))

    if not wheels:
        print(
            f"ERROR: no wheels found (looked in {args.dist_dir}); "
            f"run `uv build` first or pass --wheels",
            file=sys.stderr,
        )
        return 2

    code, report = check(wheels)
    print("\n".join(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
