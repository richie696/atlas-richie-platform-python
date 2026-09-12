"""AWS secret backend properties — pydantic-settings env injection.

中文
----
对位 Java `cn.richie696.component.secret.provider.aws.AwsSecretProperties`。

字段分类:

- **连接**:`region`(必填),`endpoint_kms` / `endpoint_sm`(覆盖,
  主要是 localstack 测试用),`timeout_seconds`
- **认证**:`auth_type` 枚举 `DEFAULT_CHAIN` / `PROFILE` +
  `profile_name`(boto3 SDK 走 default chain 处理 env / IAM /
  profile,Python 端只暴露这两个选项)
- **KMS**:`kms_signing_algorithm`(默认 `RSASSA_PSS_SHA_256`),
  `kms_key_bindings`(logical → 物理 CMK ARN,跟 Vault R-233.3
  一样用于环境分层)
- **Secrets Manager**:`secrets_manager_path_prefix`(逻辑路径
  到 SM secret name 的前缀)
- **secret 映射**:`secrets: dict[str, SecretMapping]`(逻辑名
  → `secret_id` + 可选 `field`,对位 Java `SecretMapping`)

`to_boto3_client_kwargs()` 构造 boto3 client kwargs dict(共享
region / endpoint / creds)。

English
--------
AWS backend properties. Pydantic-settings env injection with
prefix `ATLAS_RICHIE_SECRET_AWS_`. Mirrors Java
`AwsSecretProperties`: region / auth / KMS signing algorithm /
KMS key bindings / Secrets Manager prefix / endpoint overrides /
secret mapping table. boto3's default credential chain is
preserved; only the type discriminator (default vs profile) is
exposed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass


class AwsAuthType(StrEnum):
    """AWS authentication strategy (mirrors Java `AuthenticationType`)."""

    DEFAULT_CHAIN = "default_chain"
    PROFILE = "profile"


class AwsSecretProperties(BaseSettings):
    """Env-injected configuration for the AWS secret backend."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_RICHIE_SECRET_AWS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Region
    region: str = Field(...)
    timeout_seconds: float = Field(default=30.0, gt=0)

    # Auth
    auth_type: AwsAuthType = Field(default=AwsAuthType.DEFAULT_CHAIN)
    profile_name: str | None = Field(default=None)

    # Endpoints (override for localstack / private link)
    endpoint_kms: str | None = Field(default=None)
    endpoint_sm: str | None = Field(default=None)

    # KMS
    kms_signing_algorithm: str = Field(default="RSASSA_PSS_SHA_256")
    # Logical → physical CMK ARN mapping. Mirrors Java
    # `Kms.keyBindings` and the vault wheel's R-233.3
    # `transit_key_bindings`.
    kms_key_bindings: dict[str, str] = Field(default_factory=dict)

    # Secrets Manager
    secrets_manager_path_prefix: str = Field(default="")

    @field_validator("region")
    @classmethod
    def _validate_region(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("region is required")
        return value.strip()

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> "AwsSecretProperties":
        if self.auth_type is AwsAuthType.PROFILE and not self.profile_name:
            raise ValueError(
                "auth_type=profile requires ATLAS_RICHIE_SECRET_AWS_PROFILE_NAME",
            )
        return self

    def to_boto3_client_kwargs(self) -> dict[str, object]:
        """Build the kwargs dict for `boto3.client("kms", **kwargs)`
        and `boto3.client("secretsmanager", **kwargs)`.
        """
        kwargs: dict[str, object] = {
            "region_name": self.region,
            "config": {
                "connect_timeout": self.timeout_seconds,
                "read_timeout": self.timeout_seconds,
                "retries": {"max_attempts": 3, "mode": "standard"},
            },
        }
        if self.profile_name:
            kwargs["profile_name"] = self.profile_name
        return kwargs

    def to_kms_client_kwargs(self) -> dict[str, object]:
        kwargs = self.to_boto3_client_kwargs()
        if self.endpoint_kms:
            kwargs["endpoint_url"] = self.endpoint_kms
        return kwargs

    def to_sm_client_kwargs(self) -> dict[str, object]:
        kwargs = self.to_boto3_client_kwargs()
        if self.endpoint_sm:
            kwargs["endpoint_url"] = self.endpoint_sm
        return kwargs


__all__ = ["AwsAuthType", "AwsSecretProperties"]
