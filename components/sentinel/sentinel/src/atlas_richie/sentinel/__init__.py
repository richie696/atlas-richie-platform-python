"""Atlas Richie Sentinel — flow control, circuit breaking, system protection.

This is the public Facade for the main wheel. The version string is read
from distribution metadata (PEP 562 lazy attribute) so there is no
hard-coded ``__version__`` to drift out of sync with ``pyproject.toml``.

For detailed documentation, see ``components/sentinel/docs/DESIGN.md``
and ``components/sentinel/docs/PLANNING.md`` in the source repository.

中文
----
Atlas Richie Sentinel 公共 Facade。版本号走 PEP 562 懒加载从 distribution
metadata 读取,避免在 ``__init__.py`` 中硬编码,确保 wheel 内版本号与
发布元数据始终一致。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version


def __getattr__(name: str) -> str:
    """PEP 562 lazy attribute access.

    Returns the package version from distribution metadata when available,
    falling back to ``"0.0.0+local"`` for editable / non-installed copies so
    that ``import atlas_richie.sentinel`` always succeeds.
    """
    if name == "__version__":
        try:
            return _pkg_version("atlas-richie-sentinel")
        except PackageNotFoundError:
            return "0.0.0+local"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["__version__"]
