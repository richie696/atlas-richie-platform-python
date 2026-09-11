"""脚本原子操作 API 管理器接口。

中文
----
脚本原子操作 API 管理器接口，封装了脚本的执行能力。
适用于复杂原子操作、分布式事务、批量处理等场景。

- `script`：执行脚本，支持传递 key 和参数，返回指定类型结果

推荐用于高并发下的原子性保障、复杂业务逻辑下沉缓存中间件等场景
（Redis -> Lua、其它：待更新）。

English
--------
Script atomic ops interface.

Mirrors `cn.richie696.component.cache.ops.ScriptOps`. Encapsulates
script execution for complex atomic operations, distributed
transactions, and batch processing.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import List, Protocol, TypeVar

T = TypeVar("T")


class ScriptOps(Protocol):
    """中文
    ----
    脚本原子操作 API 管理器接口，封装了脚本的执行能力。适用于复杂原子
    操作、分布式事务、批量处理等场景。

    - `script`：执行脚本，支持传递 key 和参数，返回指定类型结果

    推荐用于高并发下的原子性保障、复杂业务逻辑下沉缓存中间件等场景
    （Redis -> Lua、其它：待更新）。

    English
    --------
    Script atomic ops manager. Encapsulates script execution for
    complex atomic operations, distributed transactions, and batch
    processing.

    - `script`: execute a script, accepting keys and args, returning a
      result of the requested type.

    Recommended for atomicity under high concurrency and for sinking
    complex business logic into the cache middleware (Redis → Lua;
    others TBD).
    """

    @abstractmethod
    def eval(self, script: str, keys: List[str], args: List[str], result_type: type[T]) -> T:
        """中文
        ----
        执行 Lua 脚本。

        Args:
            script: Lua 脚本内容
            keys: 参与脚本的 Redis 键列表
            args: 脚本参数列表
            result_type: 返回结果类型

        Returns:
            脚本执行结果

        English
        --------
        Execute a Lua script.

        Args:
            script: Lua script body.
            keys: Redis keys involved in the script.
            args: Script arguments.
            result_type: Result type.

        Returns:
            Script execution result.
        """
        ...

    @abstractmethod
    def eval_single_key(
        self, script: str, key: str, args: List[str], result_type: type[T]
    ) -> T:
        """中文
        ----
        执行 Lua 脚本（单 key 变体）。

        Args:
            script: Lua 脚本内容
            key: 参与脚本的 Redis 键
            args: 脚本参数列表
            result_type: 返回结果类型

        Returns:
            脚本执行结果

        English
        --------
        Execute a Lua script (single-key variant).

        Args:
            script: Lua script body.
            key: Redis key involved in the script.
            args: Script arguments.
            result_type: Result type.

        Returns:
            Script execution result.
        """
        ...


__all__ = ["ScriptOps"]
