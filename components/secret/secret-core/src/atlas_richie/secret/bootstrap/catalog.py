"""Secret 启动期 binding catalog。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.catalog.*`(7 个 class):
`RequiredWhen` / `SecretBinding` / `SecretBindingCatalog` /
`SecretBindingCatalogLoader` / `SecretBindingCatalogSet` /
`SecretExposure` / `SecretKind` / `SecretPropertyPattern` /
`SecretRefreshStrategy`。

- `SecretKind` — StrEnum,区分 secret 类型(API 凭证 / TLS 证书 / 配置
  令牌 / 通用)。
- `SecretExposure` — StrEnum,标记 binding 暴露方式(env / 文件 / 进程
  参数 / 服务总线)。
- `RequiredWhen` — StrEnum,标记 binding 何时为必填(startup / lazy /
  optional / production-only)。
- `SecretRefreshStrategy` — StrEnum,标记 secret 旋转后的刷新行为
  (none / env reload / file rewrite / service-bus notification)。
- `SecretPropertyPattern` — frozen dataclass,name 到 secret 路径的
  模板(可带 `${env}` 占位符;占位符展开留给 loader)。
- `SecretBinding` — frozen dataclass,一个 binding(name + reference +
  exposure + required_when + refresh + pattern)。
- `SecretBindingCatalog` — 一组 binding + 校验 / 合并 / 序列化的能力。
- `SecretBindingCatalogSet` — 多个 catalog 的有序集合(支持 profile:
  base / overlay)。
- `SecretBindingCatalogLoader` — 从 YAML / dict / env 加载 catalog。

`SecretBinding` 是 facade + bootstrap 之间的契约;后者用它驱动
`SecretBootstrapRequest` 构造。

English
--------
Secret binding catalog. Mirrors the Java secret bootstrap catalog
package. `SecretBindingCatalogSet` supports layering (base / overlay
profiles), and `SecretBindingCatalogLoader` is the in-memory / dict
loader (YAML loader is an extension point).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class SecretKind(StrEnum):
    """Classification of a secret binding."""

    GENERIC = "generic"
    API_CREDENTIAL = "api_credential"
    TLS_CERTIFICATE = "tls_certificate"
    CONFIG_TOKEN = "config_token"
    DATABASE_PASSWORD = "database_password"


class SecretExposure(StrEnum):
    """How a resolved secret is exposed to the application process."""

    ENV = "env"
    FILE = "file"
    ARGV = "argv"
    SERVICE_BUS = "service_bus"


class RequiredWhen(StrEnum):
    """When a binding must be present and resolvable."""

    STARTUP = "startup"
    LAZY = "lazy"
    OPTIONAL = "optional"
    PRODUCTION_ONLY = "production_only"


class SecretRefreshStrategy(StrEnum):
    """What happens after a secret rotates."""

    NONE = "none"
    ENV_RELOAD = "env_reload"
    FILE_REWRITE = "file_rewrite"
    SERVICE_BUS_NOTIFY = "service_bus_notify"


@dataclass(frozen=True, slots=True)
class SecretPropertyPattern:
    """Template for deriving the property name (env var, file path,
    argv index) from a binding name.

    Attributes:
        template: String with optional ``${name}`` placeholders.
            ``${name}`` is replaced by the binding's `name` (uppercase
            by default for env exposure).
        uppercase: Whether the resolved string is uppercased
            (matches the env-var convention).
    """

    template: str
    uppercase: bool = True

    def render(self, name: str) -> str:
        rendered = self.template.replace("${name}", name)
        return rendered.upper() if self.uppercase else rendered


@dataclass(frozen=True, slots=True)
class SecretBinding:
    """One binding between a logical name and a secret reference.

    Attributes:
        name: Logical name used by the application
            (e.g. ``"db.password"``).
        reference: Resolved `SecretReference` for the secret.
        kind: Type of secret.
        exposure: How the secret is exposed.
        required_when: When the secret must be present.
        refresh: What happens after rotation.
        pattern: Optional property-name pattern. If absent, `name`
            is used directly.
    """

    name: str
    reference: "SecretReference"
    kind: SecretKind = SecretKind.GENERIC
    exposure: SecretExposure = SecretExposure.ENV
    required_when: RequiredWhen = RequiredWhen.STARTUP
    refresh: SecretRefreshStrategy = SecretRefreshStrategy.NONE
    pattern: SecretPropertyPattern | None = None

    def property_name(self) -> str:
        if self.pattern is None:
            # Default rule: env exposure uppercases the binding name
            # (POSIX env-var convention); file/argv exposures keep the
            # raw path.
            if self.exposure is SecretExposure.ENV:
                return self.name.upper()
            return self.name
        return self.pattern.render(self.name)


@dataclass(frozen=True, slots=True)
class SecretBindingCatalog:
    """Immutable, validated set of `SecretBinding`s.

    Attributes:
        name: Catalog name (e.g. ``"default"``, ``"prod-overlay"``).
        bindings: Tuple of `SecretBinding` (sorted by name for
            determinism).
    """

    name: str
    bindings: tuple[SecretBinding, ...] = ()

    def __post_init__(self) -> None:
        names = [b.name for b in self.bindings]
        if len(names) != len(set(names)):
            raise ValueError(
                f"duplicate binding names in catalog {self.name!r}: {names}",
            )

    def with_binding(self, binding: SecretBinding) -> "SecretBindingCatalog":
        """Return a new catalog with `binding` appended. If a
        binding with the same name already exists, it is replaced.
        """
        existing = [b for b in self.bindings if b.name != binding.name]
        return SecretBindingCatalog(
            name=self.name,
            bindings=tuple(existing + [binding]),
        )

    def find(self, name: str) -> SecretBinding | None:
        for b in self.bindings:
            if b.name == name:
                return b
        return None

    def filter(
        self,
        *,
        kind: SecretKind | None = None,
        exposure: SecretExposure | None = None,
    ) -> tuple[SecretBinding, ...]:
        def keep(b: SecretBinding) -> bool:
            if kind is not None and b.kind is not kind:
                return False
            if exposure is not None and b.exposure is not exposure:
                return False
            return True

        return tuple(b for b in self.bindings if keep(b))


@dataclass(frozen=True, slots=True)
class SecretBindingCatalogSet:
    """An ordered, layered stack of `SecretBindingCatalog`s.

    Attributes:
        catalogs: Tuple of catalogs in precedence order (later wins).
    """

    catalogs: tuple[SecretBindingCatalog, ...] = ()

    def merged(self) -> SecretBindingCatalog:
        """Fold all catalogs into a single `SecretBindingCatalog`
        using last-wins semantics by binding name. Returned catalog
        name is ``"<set>"``; original catalog ordering is lost.
        """
        merged: dict[str, SecretBinding] = {}
        for catalog in self.catalogs:
            for binding in catalog.bindings:
                merged[binding.name] = binding
        return SecretBindingCatalog(
            name="<merged>",
            bindings=tuple(merged.values()),
        )

    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.catalogs)


class SecretBindingCatalogLoader:
    """Build a `SecretBindingCatalog` from a mapping of bindings.

    Expected shape:
    ```python
    {
      "name": "default",
      "bindings": [
        {
          "name": "db.password",
          "provider": "vault-prod",
          "path": "secret/data/db/password",
          "kind": "database_password",
          "exposure": "env",
          "required_when": "startup",
          "refresh": "env_reload",
        },
        ...
      ],
    }
    ```
    """

    def __init__(self, source: Mapping[str, object]) -> None:
        self._source = source

    def load(self) -> SecretBindingCatalog:
        name = str(self._source.get("name", "default"))
        raw_bindings = self._source.get("bindings", [])
        if not isinstance(raw_bindings, list):
            raise ValueError(
                f"catalog {name!r}: 'bindings' must be a list",
            )
        bindings = tuple(
            self._parse_binding(name, idx, entry)
            for idx, entry in enumerate(raw_bindings)
        )
        return SecretBindingCatalog(name=name, bindings=bindings)

    def _parse_binding(
        self,
        catalog_name: str,
        index: int,
        entry: object,
    ) -> SecretBinding:
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"catalog {catalog_name!r} binding #{index} must be a mapping",
            )
        name = entry.get("name")
        provider = entry.get("provider")
        path = entry.get("path")
        if not (isinstance(name, str) and isinstance(provider, str) and isinstance(path, str)):
            raise ValueError(
                f"catalog {catalog_name!r} binding #{index} requires "
                "name / provider / path strings",
            )
        from atlas_richie.secret.reference import SecretReference

        reference = SecretReference(provider=provider, path=path)
        kind = SecretKind(str(entry.get("kind", "generic")))
        exposure = SecretExposure(str(entry.get("exposure", "env")))
        required_when = RequiredWhen(str(entry.get("required_when", "startup")))
        refresh = SecretRefreshStrategy(str(entry.get("refresh", "none")))
        pattern_raw = entry.get("pattern")
        pattern: SecretPropertyPattern | None = None
        if pattern_raw is not None:
            if not isinstance(pattern_raw, Mapping):
                raise ValueError(
                    f"catalog {catalog_name!r} binding {name!r} pattern must be a mapping",
                )
            pattern = SecretPropertyPattern(
                template=str(pattern_raw.get("template", "${name}")),
                uppercase=bool(pattern_raw.get("uppercase", True)),
            )
        return SecretBinding(
            name=name,
            reference=reference,
            kind=kind,
            exposure=exposure,
            required_when=required_when,
            refresh=refresh,
            pattern=pattern,
        )


__all__ = [
    "SecretKind",
    "SecretExposure",
    "RequiredWhen",
    "SecretRefreshStrategy",
    "SecretPropertyPattern",
    "SecretBinding",
    "SecretBindingCatalog",
    "SecretBindingCatalogSet",
    "SecretBindingCatalogLoader",
]


_ = (field, Iterable)
