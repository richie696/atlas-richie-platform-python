"""MFA 注册侧的纯标准库能力：密钥生成与 otpauth provisioning URI。

对位 Java `mfa-management` 的 `SecretKeyManager.generateSecretKey` 与
`QrCodeManager.generateQrCodeUrl`。两者都不需要数据库或 Spring，因此抽到
mfa-validation 里交付，使本包从「只能验码」变为「能开户 + 能验码」。

注册链路的其余部分（绑定/激活、可信设备、备份码、密钥加密）依赖持久层与
KMS，不在本模块范围内。
"""

from __future__ import annotations

import base64
import secrets
from urllib.parse import quote_plus

from .engine import normalize_algorithm

SECRET_KEY_LENGTH = 20  # 160 位，RFC 4226 建议的 HMAC-SHA1 密钥长度


def generate_secret_key(length: int = SECRET_KEY_LENGTH) -> str:
    """CSPRNG 密钥 → 无填充 Base32（otpauth URI 规范要求去掉 `=`）。"""
    if length <= 0:
        raise ValueError("secret key length must be positive")
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _form_encode(value: str) -> str:
    """Match Java's URLEncoder: space → '+', '*' literal, '~' percent-encoded.

    Python's quote_plus differs on exactly those two characters, so align them
    rather than emit a URI that a Java-generated one would not byte-match.
    """
    return quote_plus(value, safe="*").replace("~", "%7E")


def generate_qr_code_url(
    tenant_id: int | None,
    user_id: str,
    username: str,
    secret: str,
    issuer: str,
    algorithm: str | None = None,
    digits: int = 6,
    period: int = 30,
    *,
    configured_default_algorithm: str | None = None,
) -> str:
    """构造 otpauth://totp provisioning URI（供二维码渲染）。

    label 为 `issuer:tenantId:userId`（无租户时 `issuer:userId`）；issuer 参数
    为 `"{issuer} {username}"`，与 Java 一致。算法名归一化复用验码侧的
    `normalize_algorithm`，保证注册与校验用同一套解析规则。
    """
    if not user_id:
        raise ValueError("user_id must not be blank")
    if not secret:
        raise ValueError("secret must not be blank")
    if not issuer:
        raise ValueError("issuer must not be blank")
    if digits <= 0 or period <= 0:
        raise ValueError("digits and period must be positive")

    label = (
        f"{issuer}:{tenant_id}:{user_id}"
        if tenant_id is not None
        else f"{issuer}:{user_id}"
    )
    issuer_with_username = f"{issuer} {username}"
    resolved = normalize_algorithm(algorithm, configured_default_algorithm)
    return (
        f"otpauth://totp/{_form_encode(label)}"
        f"?secret={_form_encode(secret)}"
        f"&issuer={_form_encode(issuer_with_username)}"
        f"&algorithm={resolved}"
        f"&digits={digits}"
        f"&period={period}"
    )


__all__ = ["SECRET_KEY_LENGTH", "generate_secret_key", "generate_qr_code_url"]