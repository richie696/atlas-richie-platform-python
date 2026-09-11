"""RFC 7636 PKCE S256 生成与校验。
----
实现 RFC 7636 "Proof Key for Code Exchange" 中规定的 `S256`
code_challenge_method。**仅**支持 S256，刻意拒绝已被废弃的 `plain`
方法 —— OAuth 2.1 / OAuth Security BCP 推荐淘汰 plain。

组件中提供两个角色：

- `PkcePair`（数据类）：把 verifier 和它唯一被接受的 challenge
  绑在一起，避免业务代码误用别的方法。
- `PkceS256`（工具类）：两个静态方法 `challenge()` 与 `verify()`，
  stateless；前者计算 challenge，后者做常数时间比对。两者都强制
  RFC 7636 §4.1 的 verifier 长度约束（43-128 ASCII 字符）。

English
--------
RFC 7636 PKCE S256 generation and validation.

Implements the `S256` `code_challenge_method` from RFC 7636
"Proof Key for Code Exchange". **Only** S256 is supported; the
deprecated `plain` method is intentionally rejected — OAuth 2.1 and
the OAuth Security BCP recommend retiring `plain`.

Two roles live in the component:

- `PkcePair` (dataclass): binds a verifier to the single challenge
  it accepts, so business code cannot accidentally pair it with a
  different method.
- `PkceS256` (utility): two stateless statics, `challenge()` and
  `verify()`. The first computes the challenge; the second does a
  constant-time comparison. Both enforce the RFC 7636 §4.1 verifier
  length constraint (43-128 ASCII characters).
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe

from .errors import OAuthConfigurationError


@dataclass(frozen=True, slots=True)
class PkcePair:
    """中文
    ----
    Verifier 与其唯一被接受的 (`S256`) challenge 的绑定。

    English
    --------
    A verifier and its only accepted (`S256`) challenge.
    """

    verifier: str
    challenge: str
    method: str = "S256"

    @classmethod
    def generate(cls) -> "PkcePair":
        verifier = token_urlsafe(32)
        return cls(verifier=verifier, challenge=PkceS256.challenge(verifier))


class PkceS256:
    """中文
    ----
    无状态 PKCE 工具类，拒绝已废弃的 `plain` 方法。

    English
    --------
    Stateless PKCE helper that refuses the obsolete plain method.
    """

    @staticmethod
    def challenge(verifier: str) -> str:
        """中文
        ----
        计算 RFC 7636 §4.2 的 S256 challenge。

        English
        --------
        Compute the RFC 7636 §4.2 S256 challenge.
        """
        if not verifier or not verifier.isascii() or not 43 <= len(verifier) <= 128:
            raise OAuthConfigurationError("PKCE verifier must be 43-128 ASCII characters")
        return urlsafe_b64encode(sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    @staticmethod
    def verify(*, verifier: str, expected_challenge: str, method: str = "S256") -> bool:
        """中文
        ----
        常数时间比对 verifier 与 expected_challenge。`method` 不是
        `S256` 时直接返回 `False`（刻意拒绝 plain）。

        English
        --------
        Constant-time comparison of `verifier` against
        `expected_challenge`. Returns `False` when `method` is not
        `S256` (`plain` is intentionally rejected).
        """
        if method != "S256" or not expected_challenge:
            return False
        return compare_digest(PkceS256.challenge(verifier), expected_challenge)
