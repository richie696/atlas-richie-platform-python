"""Atlas Richie Sentinel Cluster — CLI 入口 (M6.3.5 配套).

中文
----
让 ``python -m atlas_richie.sentinel_cluster`` 真正可调 (跟 ``standalone.py``
docstring 声明的入口一致; 之前缺 ``__main__.py`` 时会抛
``No module named atlas_richie.sentinel_cluster.__main__``)。

**1.0 简化**: 只调 ``main()`` (来自 ``server.standalone``), 不加额外参数
解析 / 子命令。1.x 1.0 兼容, M6.3.x future 留扩展位 (e.g. ``--version`` /
``--check-config``)。

English
--------
Enables ``python -m atlas_richie.sentinel_cluster`` (matches ``standalone.py``
docstring; without ``__main__.py`` Python raises
``No module named atlas_richie.sentinel_cluster.__main__``).

1.0 simplification: just delegates to ``main()``. No extra arg parsing /
subcommands. 1.x 1.0 compatible; M6.3.x future may add ``--version`` /
``--check-config``.
"""

from __future__ import annotations

import sys

from .server.standalone import main

if __name__ == "__main__":
    sys.exit(main())
