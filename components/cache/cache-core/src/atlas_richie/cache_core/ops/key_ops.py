"""Key 管理与元数据操作接口。

中文
----
Key 管理与元数据操作接口，定义了所有对 Redis Key 及其元数据的通用操作能力。
适用于 Key 生命周期管理、类型判断、批量操作等场景。

English
--------
Key management + metadata ops interface.

Mirrors `cn.richie696.component.cache.ops.KeyOps`. Key lifecycle,
type queries, batch operations, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Collection, Protocol, Set

from ..enums.key_type_enum import KeyTypeEnum


class KeyOps(Protocol):
    """中文
    ----
    Key 管理与元数据操作接口，定义了所有对 Redis Key 及其元数据的通用
    操作能力。适用于 Key 生命周期管理、类型判断、批量操作等场景。

    English
    --------
    Key management + metadata ops. Defines generic operations on Redis
    keys and their metadata. Suitable for key lifecycle management,
    type queries, and batch operations.
    """

    @abstractmethod
    def get_expire(self, key: str) -> int:
        """中文
        ----
        获取指定 KEY 过期时间。

        Args:
            key: 需要获取过期时间的 key

        Returns:
            过期时间（单位：毫秒）

        English
        --------
        Get the TTL of `key`.

        Args:
            key: Key to query.

        Returns:
            TTL in milliseconds.
        """
        ...

    @abstractmethod
    def get_all_keys(self, key: str) -> Set[str]:
        """中文
        ----
        获取指定节点下的所有 KEY。

        Args:
            key: 需要获取的某组 KEY 的父节点

        Returns:
            该父节点下的所有子节点 KEY

        English
        --------
        Get all keys under the given parent node.

        Args:
            key: Parent node of the desired key group.

        Returns:
            All child keys under that parent.
        """
        ...

    @abstractmethod
    def set_expired_time(self, key: str, timeout: int) -> None:
        """中文
        ----
        设置对应缓存过期时间。

        Args:
            key: 缓存键
            timeout: 超时时间

        English
        --------
        Set the expiry of the cached key.

        Args:
            key: Cache key.
            timeout: Timeout.
        """
        ...

    @abstractmethod
    def has_key(self, key: str) -> bool:
        """中文
        ----
        检查指定的 Key 是否存在。

        Args:
            key: 缓存键

        Returns:
            检查结果

        English
        --------
        Check whether the key exists.

        Args:
            key: Cache key.

        Returns:
            Existence result.
        """
        ...

    @abstractmethod
    def remove_cache(self, key: str) -> None:
        """中文
        ----
        根据 Key 删除指定元素（元素包含全部的 Redis 元素，比如：string,
        list, set, zset, hash, stream）。

        Args:
            key: 列表名称

        English
        --------
        Delete the element identified by `key` (covers all Redis element
        types: string, list, set, zset, hash, stream, …).

        Args:
            key: List name.
        """
        ...

    @abstractmethod
    def remove_cache_many(self, keys: Collection[str]) -> None:
        """中文
        ----
        根据 Key 列表删除指定元素（元素包含全部的 Redis 元素，比如：string,
        list, set, zset, hash, stream）。

        Args:
            keys: Key 列表

        English
        --------
        Delete elements for a list of keys (covers all Redis element
        types: string, list, set, zset, hash, stream, …).

        Args:
            keys: Key list.
        """
        ...

    @abstractmethod
    def copy(self, source_key: str, target_key: str, replace: bool) -> bool:
        """中文
        ----
        合并两个数据集。

        Args:
            source_key: 源数据集
            target_key: 目标数据集
            replace: 是否替换目标数据集

        Returns:
            合并结果

        English
        --------
        Merge two datasets.

        Args:
            source_key: Source dataset.
            target_key: Target dataset.
            replace: Whether to replace the target dataset.

        Returns:
            Merge result.
        """
        ...

    @abstractmethod
    def move(self, key: str, db_index: int) -> bool:
        """中文
        ----
        移动指定的 Key 到指定的数据库。

        Args:
            key: 需要移动的 KEY
            db_index: 目标数据库索引

        Returns:
            移动结果

        English
        --------
        Move the key to the specified database.

        Args:
            key: Key to move.
            db_index: Target database index.

        Returns:
            Move result.
        """
        ...

    @abstractmethod
    def rename_if_absent(self, old_key: str, new_key: str) -> bool:
        """中文
        ----
        仅当目标 KEY 不存在时才将指定 KEY 重命名为目标 KEY。

        Args:
            old_key: 旧 KEY
            new_key: 新 KEY

        Returns:
            是否重命名结果（`True`：重命名，`False`：未重命名）

        Raises:
            KeyError: 当访问的 old_key 不存在时抛出此异常

        English
        --------
        Rename `old_key` to `new_key` only if `new_key` does not exist.

        Args:
            old_key: Old key.
            new_key: New key.

        Returns:
            Rename outcome (`True`: renamed, `False`: not renamed).

        Raises:
            KeyError: If `old_key` does not exist.
        """
        ...

    @abstractmethod
    def rename(self, old_key: str, new_key: str) -> None:
        """中文
        ----
        重命名 KEY。

        Args:
            old_key: 旧 KEY
            new_key: 新 KEY

        Raises:
            KeyError: 当访问的 old_key 不存在时抛出此异常

        English
        --------
        Rename a key.

        Args:
            old_key: Old key.
            new_key: New key.

        Raises:
            KeyError: If `old_key` does not exist.
        """
        ...

    @abstractmethod
    def dump(self, key: str) -> bytes:
        """中文
        ----
        序列化 KEY。

        Args:
            key: 待序列化的 KEY

        Returns:
            序列化后的 KEY

        Raises:
            KeyError: 当访问的 key 不存在时抛出此异常

        English
        --------
        Serialise a key.

        Args:
            key: Key to serialise.

        Returns:
            Serialised key bytes.

        Raises:
            KeyError: If `key` does not exist.
        """
        ...

    @abstractmethod
    def persist(self, key: str) -> bool:
        """中文
        ----
        移除指定 key 的过期时间（执行后 KEY 将不再过期）。

        Args:
            key: 待移除过期时间的 KEY

        Returns:
            移除结果

        English
        --------
        Remove the expiry of `key` (after which the key will no longer
        expire).

        Args:
            key: Key whose expiry should be removed.

        Returns:
            Result of the removal.
        """
        ...

    @abstractmethod
    def expire_at(self, key: str, timestamp: float) -> bool:
        """中文
        ----
        指定时间点设置过期时间。

        Args:
            key: 待设置过期时间的 KEY
            timestamp: 过期的时间点（Unix epoch 毫秒）

        Returns:
            设置结果

        English
        --------
        Set the expiry at a specific timestamp.

        Args:
            key: Key whose expiry should be set.
            timestamp: Expiry timestamp (Unix epoch milliseconds).

        Returns:
            Set result.
        """
        ...

    @abstractmethod
    def count_existing_keys(self, keys: Collection[str]) -> int:
        """中文
        ----
        获取匹配的 KEY 数量。

        Args:
            keys: KEY 集合

        Returns:
            匹配的 KEY 的个数

        English
        --------
        Count the number of existing keys in the input collection.

        Args:
            keys: Key collection.

        Returns:
            Number of keys that exist.
        """
        ...

    @abstractmethod
    def get_key_type(self, key: str) -> KeyTypeEnum | None:
        """中文
        ----
        获取指定 Key 的类型。

        Args:
            key: 需要获取类型的 Key

        Returns:
            Key 的类型枚举（`KeyTypeEnum`），如果 Key 不存在或类型不
            支持则返回 `None`

        English
        --------
        Get the type of the specified key.

        Args:
            key: Key whose type should be queried.

        Returns:
            The `KeyTypeEnum`, or `None` if the key does not exist or
            its type is unsupported.
        """
        ...


__all__ = ["KeyOps"]
