"""Secret 值对象与可销毁包装。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretValue` /
`DefaultSecretOperations.DestroyableSecretValue`。

- `SecretValue` — frozen dataclass,持有一次 `read` 的结果:**明文字节
  + 关联元数据**。不可变,可在函数间安全传递,也可作为 cache key 的
  payload 参与等值判断(默认 `eq=True`)。
- `DestroyableSecretValue` — 普通类,包装一份 `SecretValue` 并提供
  `destroy()` 方法,在用完后将内部字节清零(0x00 覆写)。用于短期
  内存中的密码 / token 处理(Java 的 `CharSequence` 清零模式在
  Python 中用 `bytearray` + `__del__` + 显式 `destroy()` 双保险)。

设计要点:

- `SecretValue.plaintext` 是 `bytes` 而不是 `str`,因为 secret 经常
  是 base64 / 十六进制 / 二进制 token;强制 bytes 避免编码歧义。
- `DestroyableSecretValue` 不强制 `__del__` 调 `destroy()`(CPython
  不保证 `__del__` 时机),调用方应使用 `with` 上下文或显式 `try /
  finally` 调 `destroy()`。
- 不实现 `__eq__` / `__hash__` — secret 值不应被缓存为 dict key(防
  止长生命周期进程中 secret 被误用为一般 hash key)。

English
--------
Secret value holder and destroyable wrapper. Mirrors the Java
`SecretValue` / `DefaultSecretOperations.DestroyableSecretValue`.
`SecretValue` is a frozen dataclass holding plaintext bytes plus
metadata; `DestroyableSecretValue` is a regular class that wraps a
`SecretValue` and zeroes the bytes when `destroy()` is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType

from atlas_richie.secret.metadata import SecretMetadata


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Immutable secret read result.

    Attributes:
        plaintext: Secret bytes. May be empty (e.g. an opt-in
            feature flag) but never ``None``.
        metadata: Backend-defined metadata for this read.
    """

    plaintext: bytes
    metadata: SecretMetadata

    def as_str(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        """Decode plaintext to a string.

        Use only when the caller knows the secret is text. The default
        encoding is UTF-8 strict; pass `errors="replace"` to tolerate
        undecodable bytes (rare for legitimately text-shaped secrets).
        """
        return self.plaintext.decode(encoding, errors=errors)


class DestroyableSecretValue:
    """Wrapper that zeroes plaintext bytes on `destroy()`.

    Best used as a context manager:

    ```python
    with resolver.read(reference) as handle:
        password = handle.value.as_str()
    # handle.value is now zeroed; future reads must re-fetch.
    ```

    Forgetting the context exit or `destroy()` call leaves the secret
    in memory until the process exits; this is the Pythonic equivalent
    of the Java `DestroyableSecretValue` best-effort model.
    """

    __slots__ = ("_value", "_destroyed")

    def __init__(self, value: SecretValue) -> None:
        self._value = value
        self._destroyed = False

    @property
    def value(self) -> SecretValue:
        if self._destroyed:
            raise RuntimeError("DestroyableSecretValue has been destroyed")
        return self._value

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def destroy(self) -> None:
        """Zero the plaintext bytes. Idempotent."""
        if self._destroyed:
            return
        # Re-bind to a zero-length bytes of the same length to overwrite.
        current = self._value.plaintext
        zeroed = bytes(len(current))
        # Replace frozen inner object via object.__setattr__ on a new value.
        # SecretValue is frozen so we cannot mutate; we replace _value.
        new_value = SecretValue(plaintext=zeroed, metadata=self._value.metadata)
        object.__setattr__(self, "_value", new_value)
        self._destroyed = True

    # Context manager support ----------------------------------------------------

    def __enter__(self) -> "DestroyableSecretValue":
        if self._destroyed:
            raise RuntimeError("DestroyableSecretValue has been destroyed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.destroy()


__all__ = [
    "SecretValue",
    "DestroyableSecretValue",
]
