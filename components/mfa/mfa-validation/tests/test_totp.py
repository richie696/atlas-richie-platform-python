"""TOTP contract tests.

Primary authority: RFC 6238 Appendix B test vectors (all three algorithms, six
timestamps, 8 digits). Secondary: expectations ported from the Java module's
`TotpValidationEngineTest`, including its no-credential-logging requirement.
"""

from __future__ import annotations

import base64
import logging

import pytest

from atlas_richie.mfa_validation import (
    InMemoryReplayGuard,
    ReplayPreventionProperties,
    TotpProperties,
    TotpValidationEngine,
    base32_decode,
    normalize_algorithm,
)

pytestmark = pytest.mark.unit

# RFC 6238 Appendix B seeds are ASCII strings, not Base32.
_SEEDS = {
    "SHA1": b"12345678901234567890",
    "SHA256": b"12345678901234567890123456789012",
    "SHA512": b"1234567890123456789012345678901234567890123456789012345678901234",
}

# (unix seconds, SHA1, SHA256, SHA512) — RFC 6238 Appendix B, 8 digits.
#
# The T values below are chosen so that floor(T / 30) equals the RFC's counter.
# Widely-circulated transcriptions of the table pair T=1111111111 with counter
# 0x23523EC, but 1111111111 // 30 == 0x23523ED; 0x23523EC covers T in
# [1111111080, 1111111109]. Using 1111111109 keeps the vector arithmetically
# consistent — and 1111111111 / 1111111112 would otherwise be the SAME counter
# and could not legitimately yield two different codes.
RFC_VECTORS = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111112, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]

JAVA_SECRET = "JBSWY3DPEHPK3PXP"


def _b32(seed: bytes) -> str:
    return base64.b32encode(seed).decode("ascii")


class TestRfc6238Vectors:
    @pytest.mark.parametrize(("seconds", "sha1", "sha256", "sha512"), RFC_VECTORS)
    def test_generate_matches_rfc(self, seconds: int, sha1: str, sha256: str, sha512: str) -> None:
        engine = TotpValidationEngine()
        for algorithm, expected in (("SHA1", sha1), ("SHA256", sha256), ("SHA512", sha512)):
            step = seconds // 30
            assert engine.generate_code(_b32(_SEEDS[algorithm]), step, 8, algorithm) == expected

    @pytest.mark.parametrize(("seconds", "sha1", "sha256", "sha512"), RFC_VECTORS)
    def test_verify_matches_rfc(self, seconds: int, sha1: str, sha256: str, sha512: str) -> None:
        engine = TotpValidationEngine()
        for algorithm, expected in (("SHA1", sha1), ("SHA256", sha256), ("SHA512", sha512)):
            assert engine.verify_code(
                _b32(_SEEDS[algorithm]), expected, window=0, algorithm=algorithm,
                period=30, digits=8, now=seconds,
            ) is True


class TestJavaExpectations:
    def test_accepts_current_totp(self) -> None:
        engine = TotpValidationEngine()
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 30, 6, "SHA1")
        assert engine.verify_code(JAVA_SECRET, code, 1, "SHA1", 30, 6, now=now) is True

    def test_rejects_blank_secret(self) -> None:
        engine = TotpValidationEngine()
        assert engine.verify_code("", "123456", 1, now=1_700_000_000) is False
        assert engine.verify_code(None, "123456", 1, now=1_700_000_000) is False

    def test_rejects_wrong_code(self) -> None:
        engine = TotpValidationEngine()
        assert engine.verify_code(JAVA_SECRET, "000000", 0, now=1_700_000_000) is False

    @pytest.mark.parametrize("algorithm", ["SHA256", "SHA512"])
    def test_supports_alternate_algorithms(self, algorithm: str) -> None:
        engine = TotpValidationEngine(TotpProperties(algorithm=algorithm))
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 30, 6, algorithm)
        assert engine.verify_code(JAVA_SECRET, code, 1, algorithm, 30, 6, now=now) is True

    def test_unknown_algorithm_falls_back_to_configured_default(self) -> None:
        engine = TotpValidationEngine(TotpProperties(algorithm="SHA1"))
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 30, 6, "SHA1")
        assert engine.verify_code(JAVA_SECRET, code, 1, "UNKNOWN", 30, 6, now=now) is True

    def test_empty_config_falls_back_to_sha1(self) -> None:
        engine = TotpValidationEngine(TotpProperties(algorithm=""))
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 30, 6, "SHA1")
        assert engine.verify_code(JAVA_SECRET, code, 1, now=now) is True

    def test_invalid_config_falls_back_to_sha1(self) -> None:
        engine = TotpValidationEngine(TotpProperties(algorithm="MD5"))
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 30, 6, "SHA1")
        assert engine.verify_code(JAVA_SECRET, code, 1, now=now) is True

    def test_invalid_base32_fails_closed(self) -> None:
        engine = TotpValidationEngine()
        assert engine.verify_code("!!!not-base32!!!", "123456", 1, now=1_700_000_000) is False

    def test_never_logs_secret_or_submitted_code(self, caplog) -> None:
        engine = TotpValidationEngine()
        with caplog.at_level(logging.DEBUG):
            engine.verify_code("!!!not-base32!!!", "987654", 1, now=1_700_000_000)
            engine.verify_code(JAVA_SECRET, "000000", 0, now=1_700_000_000)
        joined = " ".join(record.getMessage() for record in caplog.records)
        assert JAVA_SECRET not in joined
        assert "987654" not in joined
        assert "000000" not in joined
        assert "!!!not-base32!!!" not in joined


class TestWindowAndParameters:
    def test_window_accepts_adjacent_steps(self) -> None:
        engine = TotpValidationEngine()
        now = 1_700_000_000
        step = now // 30
        for delta in (-1, 0, 1):
            code = engine.generate_code(JAVA_SECRET, step + delta, 6, "SHA1")
            assert engine.verify_code(JAVA_SECRET, code, 1, "SHA1", 30, 6, now=now) is True

    def test_zero_window_rejects_adjacent_steps(self) -> None:
        engine = TotpValidationEngine()
        now = 1_700_000_000
        step = now // 30
        for delta in (-1, 1):
            code = engine.generate_code(JAVA_SECRET, step + delta, 6, "SHA1")
            assert engine.verify_code(JAVA_SECRET, code, 0, "SHA1", 30, 6, now=now) is False

    def test_period_and_digits_override_config(self) -> None:
        engine = TotpValidationEngine(TotpProperties(time_window=30, code_length=6))
        now = 1_700_000_000
        code = engine.generate_code(JAVA_SECRET, now // 60, 8, "SHA1")
        assert engine.verify_code(JAVA_SECRET, code, 0, "SHA1", 60, 8, now=now) is True
        assert engine.verify_code(JAVA_SECRET, code, 0, "SHA1", 30, 6, now=now) is False

    def test_non_positive_period_fails_closed(self) -> None:
        engine = TotpValidationEngine()
        assert engine.verify_code(JAVA_SECRET, "123456", 1, period=0, now=1_700_000_000) is False


class TestNormalizeAlgorithm:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("SHA1", "SHA1"), ("sha256", "SHA256"), ("HmacSHA512", "SHA512"),
            ("HmacSHA1", "SHA1"), ("UNKNOWN", "SHA1"), (None, "SHA1"), ("", "SHA1"),
        ],
    )
    def test_normalization(self, value: str | None, expected: str) -> None:
        assert normalize_algorithm(value) == expected

    def test_configured_default_is_used(self) -> None:
        assert normalize_algorithm(None, "HmacSHA256") == "SHA256"
        assert normalize_algorithm("BOGUS", "SHA512") == "SHA512"
        assert normalize_algorithm("BOGUS", "ALSO-BAD") == "SHA1"


class TestBase32Leniency:
    def test_lowercase_accepted(self) -> None:
        assert base32_decode(JAVA_SECRET.lower()) == base32_decode(JAVA_SECRET)

    def test_missing_padding_accepted(self) -> None:
        assert base32_decode("JBSWY3DPEHPK3PXP") == base32_decode("JBSWY3DPEHPK3PXP====")

    def test_whitespace_ignored(self) -> None:
        assert base32_decode(" JBSW Y3DP EHPK 3PXP ") == base32_decode(JAVA_SECRET)

    def test_empty_returns_empty(self) -> None:
        assert base32_decode("") == b""


class TestReplayGuard:
    def test_mark_then_detect(self) -> None:
        guard = InMemoryReplayGuard()
        assert guard.is_code_used("u1", None, 100) is False
        guard.mark_code_as_used("u1", None, 100)
        assert guard.is_code_used("u1", None, 100) is True

    def test_steps_and_subjects_are_independent(self) -> None:
        guard = InMemoryReplayGuard()
        guard.mark_code_as_used("u1", None, 100)
        assert guard.is_code_used("u1", None, 101) is False
        assert guard.is_code_used("u2", None, 100) is False

    def test_tenant_isolation(self) -> None:
        guard = InMemoryReplayGuard()
        guard.mark_code_as_used("u1", 7, 100)
        assert guard.is_code_used("u1", 7, 100) is True
        assert guard.is_code_used("u1", 8, 100) is False
        assert guard.is_code_used("u1", None, 100) is False

    def test_ttl_expiry(self) -> None:
        clock = [0.0]
        guard = InMemoryReplayGuard(
            ReplayPreventionProperties(time_window=30, replay_prevention_ttl_multiplier=3),
            clock=lambda: clock[0],
        )
        guard.mark_code_as_used("u1", None, 100)
        clock[0] = 89.0
        assert guard.is_code_used("u1", None, 100) is True
        clock[0] = 90.0
        assert guard.is_code_used("u1", None, 100) is False

    def test_ttl_matches_java_rule(self) -> None:
        props = ReplayPreventionProperties(time_window=30, replay_prevention_ttl_multiplier=4)
        assert props.ttl_seconds == 120
