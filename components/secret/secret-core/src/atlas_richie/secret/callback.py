"""Secret 回调契约。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretCallback`。

`SecretCallback` 是一个 Protocol,允许调用方在 secret 读 / 写 / 旋转
等操作中插入自定义副作用:

- **审计**(audit):记录 secret 访问到 SIEM / 审计日志(不记录明文)
- **指标**(metrics):增加 Prometheus / OpenTelemetry counter
- **追踪**(tracing):注入 trace span
- **缓存失效**(cache invalidation):旋转时清掉 `atlas-richie-cache` 里的
  派生值

实现要点:

- 多个 callback 通过 `SecretCallback` 列表传给 `SecretResolver`,
  顺序执行;任一 callback 抛异常都会被 facade 记录但不会中断主流程
  (`best-effort`,与 cache 那边 audit sink 行为一致)。
- 回调拿到的参数已脱敏:`reference` 是完整对象,`value` 视 `pass_value`
  标志位决定是否传明文;默认 `pass_value=False`,只给 `metadata`。
- 不允许 callback 修改 `value` / `reference`(语义冻结);需要转换请
  使用 `SecretCipher` decorator 链,而不是 callback。

English
--------
Secret callback contract. Mirrors the Java
`cn.richie696.component.secret.api.SecretCallback`. `SecretCallback`
is a Protocol; the resolver accepts a list of callbacks, runs them
in order, and treats each as best-effort (failures are logged but
do not abort the secret read/write/rotate).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret.value import SecretValue


@runtime_checkable
class SecretCallback(Protocol):
    """Best-effort side-effect hook fired on secret operations.

    Implementations must be idempotent and non-throwing: a callback
    that raises an exception is logged and skipped so that one
    broken observability hook does not break the secret pipeline.
    """

    def on_read(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        """Called after a successful read.

        `value` is the full `SecretValue` including plaintext bytes.
        Implementations MUST NOT log `value.plaintext` to any sink.
        """
        ...

    def on_write(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        """Called after a successful write (create / update)."""
        ...

    def on_rotate(
        self,
        reference: SecretReference,
        previous: SecretValue | None,
        current: SecretValue,
    ) -> None:
        """Called after a successful rotation. `previous` is the value
        that was active just before the rotation; ``None`` if the
        backend had no record of a prior version.
        """
        ...

    def on_resolve_failure(
        self,
        reference: SecretReference,
        error: BaseException,
    ) -> None:
        """Called when a resolve attempt raises. `error` is the
        underlying exception (typically `SecretException`).
        """
        ...

    def on_metadata(
        self,
        reference: SecretReference,
        metadata: SecretMetadata,
    ) -> None:
        """Called when metadata-only operations (e.g. list, describe)
        produce a `SecretMetadata` record.
        """
        ...


__all__ = ["SecretCallback"]
