"""Unit tests for RP-Initiated Logout 1.0 request construction."""

from __future__ import annotations

import unittest
from urllib.parse import parse_qsl, urlsplit

from atlas_richie.oauth import (
    LogoutRequest,
    OAuthConfigurationError,
    RpInitiatedLogout,
)


def _qs(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


class RpInitiatedLogoutBuilderTest(unittest.TestCase):
    def test_minimal_request(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("id-token-xyz")
            .build()
        )
        self.assertEqual("https://issuer.example/logout", request.end_session_endpoint)
        self.assertEqual("id-token-xyz", request.id_token_hint)

    def test_full_request(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("id-token-xyz")
            .post_logout_redirect_uri("https://app.example/after")
            .state("csrf-token-abc")
            .ui_locales("zh-CN")
            .build()
        )
        self.assertEqual("https://app.example/after", request.post_logout_redirect_uri)
        self.assertEqual("csrf-token-abc", request.state)
        self.assertEqual("zh-CN", request.ui_locales)

    def test_builder_setters_return_new_instance(self) -> None:
        # Setters must not mutate the original builder (immutable chain).
        a = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("first")
        )
        b = a.post_logout_redirect_uri("https://app.example/after")
        # Both a and b derive from their respective parent, not from each other.
        a_request = a.build()
        b_request = b.build()
        self.assertEqual("first", a_request.id_token_hint)
        self.assertIsNone(a_request.post_logout_redirect_uri)
        self.assertEqual("first", b_request.id_token_hint)
        self.assertEqual("https://app.example/after", b_request.post_logout_redirect_uri)

    def test_builder_rejects_empty_endpoint(self) -> None:
        with self.assertRaises(OAuthConfigurationError):
            RpInitiatedLogout.builder("")
        with self.assertRaises(OAuthConfigurationError):
            RpInitiatedLogout.builder("   ")

    def test_build_rejects_missing_id_token_hint(self) -> None:
        with self.assertRaises(OAuthConfigurationError):
            RpInitiatedLogout.builder("https://issuer.example/logout").build()

    def test_build_rejects_blank_optional_fields(self) -> None:
        builder = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("x")
            .post_logout_redirect_uri("   ")
        )
        with self.assertRaises(OAuthConfigurationError):
            builder.build()


class LogoutRequestUrlTest(unittest.TestCase):
    def test_minimal_url(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("id-token-xyz")
            .build()
        )
        url = request.url()
        parts = urlsplit(url)
        self.assertEqual("https", parts.scheme)
        self.assertEqual("issuer.example", parts.netloc)
        self.assertEqual("/logout", parts.path)
        params = _qs(url)
        self.assertEqual("id-token-xyz", params["id_token_hint"])
        self.assertNotIn("post_logout_redirect_uri", params)
        self.assertNotIn("state", params)
        self.assertNotIn("ui_locales", params)

    def test_full_url(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("id-token-xyz")
            .post_logout_redirect_uri("https://app.example/after")
            .state("csrf-token-abc")
            .ui_locales("zh-CN")
            .build()
        )
        params = _qs(request.url())
        self.assertEqual("id-token-xyz", params["id_token_hint"])
        self.assertEqual("https://app.example/after", params["post_logout_redirect_uri"])
        self.assertEqual("csrf-token-abc", params["state"])
        self.assertEqual("zh-CN", params["ui_locales"])

    def test_url_preserves_existing_query(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout?session=abc")
            .id_token_hint("id-token-xyz")
            .build()
        )
        params = _qs(request.url())
        self.assertEqual("abc", params["session"])
        self.assertEqual("id-token-xyz", params["id_token_hint"])

    def test_url_percent_encodes_special_characters(self) -> None:
        request = (
            RpInitiatedLogout.builder("https://issuer.example/logout")
            .id_token_hint("id token/with=chars")
            .post_logout_redirect_uri("https://app.example/path?x=1&y=2")
            .state("a b/c")
            .build()
        )
        url = request.url()
        # OAuth parameters must be percent-encoded, and the & between
        # post_logout_redirect_uri's own query must not leak into the
        # top-level query string.
        self.assertIn("id_token_hint=id+token%2Fwith%3Dchars", url)
        self.assertIn("post_logout_redirect_uri=https%3A%2F%2Fapp.example%2Fpath%3Fx%3D1%26y%3D2", url)
        self.assertIn("state=a+b%2Fc", url)


class LogoutRequestValidationTest(unittest.TestCase):
    def test_blank_endpoint_rejected(self) -> None:
        with self.assertRaises(OAuthConfigurationError):
            LogoutRequest(
                end_session_endpoint="",
                id_token_hint="x",
            )

    def test_blank_id_token_hint_rejected(self) -> None:
        with self.assertRaises(OAuthConfigurationError):
            LogoutRequest(
                end_session_endpoint="https://issuer.example/logout",
                id_token_hint="",
            )
