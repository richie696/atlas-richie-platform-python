"""MFA 注册侧：密钥生成与 otpauth URI，并与验码侧闭环。"""

from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest

from atlas_richie.mfa_validation import (
    SECRET_KEY_LENGTH,
    TotpValidationEngine,
    base32_decode,
    generate_qr_code_url,
    generate_secret_key,
)

pytestmark = pytest.mark.unit


class TestSecretGeneration:
    def test_default_length_is_160_bits(self) -> None:
        secret = generate_secret_key()
        assert len(base32_decode(secret)) == SECRET_KEY_LENGTH == 20

    def test_no_base32_padding(self) -> None:
        for _ in range(20):
            assert "=" not in generate_secret_key()

    def test_uppercase_base32_alphabet(self) -> None:
        assert re.fullmatch(r"[A-Z2-7]+", generate_secret_key())

    def test_keys_are_unique(self) -> None:
        assert len({generate_secret_key() for _ in range(50)}) == 50

    def test_custom_length(self) -> None:
        assert len(base32_decode(generate_secret_key(32))) == 32

    @pytest.mark.parametrize("length", [0, -1])
    def test_invalid_length_rejected(self, length: int) -> None:
        with pytest.raises(ValueError):
            generate_secret_key(length)

    def test_generated_secret_is_usable_by_the_engine(self) -> None:
        secret = generate_secret_key()
        code = TotpValidationEngine().generate_code(secret, 1_700_000_000 // 30)
        assert len(code) == 6 and code.isdigit()


class TestQrCodeUrl:
    def _url(self, **overrides) -> str:
        base = dict(
            tenant_id=7, user_id="u-1", username="richie", secret="JBSWY3DPEHPK3PXP",
            issuer="Atlas", algorithm="SHA1", digits=6, period=30,
        )
        base.update(overrides)
        return generate_qr_code_url(**base)

    def test_scheme_and_label_with_tenant(self) -> None:
        url = self._url()
        assert url.startswith("otpauth://totp/")
        parsed = urlparse(url)
        assert unquote_plus(parsed.path.lstrip("/")) == "Atlas:7:u-1"

    def test_label_without_tenant(self) -> None:
        parsed = urlparse(self._url(tenant_id=None))
        assert unquote_plus(parsed.path.lstrip("/")) == "Atlas:u-1"

    def test_issuer_parameter_includes_username(self) -> None:
        query = parse_qs(urlparse(self._url()).query)
        assert query["issuer"] == ["Atlas richie"]

    def test_query_parameters(self) -> None:
        query = parse_qs(urlparse(self._url()).query)
        assert query["secret"] == ["JBSWY3DPEHPK3PXP"]
        assert query["algorithm"] == ["SHA1"]
        assert query["digits"] == ["6"]
        assert query["period"] == ["30"]

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("HmacSHA256", "SHA256"),
            ("hmacsha512", "SHA1"),  # Java replaceFirst("^Hmac") 大小写敏感
            ("SHA256", "SHA256"),
            ("MD5", "SHA1"),
            ("", "SHA1"),
            (None, "SHA1"),
        ],
    )
    def test_algorithm_normalization_matches_validation_side(
        self, given, expected
    ) -> None:
        query = parse_qs(urlparse(self._url(algorithm=given)).query)
        assert query["algorithm"] == [expected]

    def test_configured_default_is_used_when_argument_invalid(self) -> None:
        query = parse_qs(
            urlparse(
                self._url(algorithm="BOGUS", configured_default_algorithm="HmacSHA512")
            ).query
        )
        assert query["algorithm"] == ["SHA512"]

    def test_label_is_percent_encoded(self) -> None:
        url = self._url(issuer="Atlas Corp", user_id="u/1")
        path = urlparse(url).path
        assert "%3A" in path, "label 中的 ':' 必须被编码"
        assert "%2F" in path, "label 中的 '/' 必须被编码"
        assert ":" not in path

    def test_java_urlencoder_semantics_for_star_and_tilde(self) -> None:
        url = self._url(username="a*b~c")
        query = parse_qs(urlparse(url).query)
        assert query["issuer"] == ["Atlas a*b~c"]
        assert "a*b%7Ec" in url, "Java URLEncoder 保留 '*' 并编码 '~'"

    def test_space_encodes_as_plus_like_java(self) -> None:
        assert "Atlas+richie" in self._url()

    @pytest.mark.parametrize(
        "overrides",
        [
            {"user_id": ""},
            {"secret": ""},
            {"issuer": ""},
            {"digits": 0},
            {"period": 0},
        ],
    )
    def test_invalid_arguments_rejected(self, overrides) -> None:
        with pytest.raises(ValueError):
            self._url(**overrides)


class TestEnrollmentToValidationRoundTrip:
    def test_secret_from_uri_verifies_a_generated_code(self) -> None:
        """注册产出的 URI 必须能被验码侧直接消费——开户与验码闭环。"""
        secret = generate_secret_key()
        url = generate_qr_code_url(
            tenant_id=7, user_id="u-1", username="richie", secret=secret,
            issuer="Atlas", algorithm="HmacSHA256", digits=8, period=60,
        )
        query = parse_qs(urlparse(url).query)
        recovered = query["secret"][0]
        assert recovered == secret
        engine = TotpValidationEngine()
        now = 1_700_000_000
        period = int(query["period"][0])
        digits = int(query["digits"][0])
        algorithm = query["algorithm"][0]
        code = engine.generate_code(recovered, now // period, digits=digits, algorithm=algorithm)
        assert len(code) == digits
        assert engine.verify_code(
            recovered, code, algorithm=algorithm, period=period, digits=digits, now=now,
        ) is True
