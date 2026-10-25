"""Tests for shared HTTP framing and JSON request parsing."""

from __future__ import annotations

import unittest

from starlette.requests import Request

from atlas_richie.sentinel_console.api.http_support import read_json_object


def _request(
    body: bytes,
    headers: list[tuple[bytes, bytes]] | None = None,
    *,
    disconnect_after_body: bool = False,
) -> Request:
    messages = [
        {"type": "http.request", "body": body, "more_body": disconnect_after_body}
    ]
    if disconnect_after_body:
        messages.append({"type": "http.disconnect"})

    async def receive() -> dict[str, object]:
        return messages.pop(0)

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/test",
            "raw_path": b"/api/v1/test",
            "query_string": b"",
            "headers": headers or [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive,
    )


class ReadJsonObjectTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_duplicate_keys_at_any_depth(self) -> None:
        for body in (
            b'{"role":"admin","role":"view"}',
            b'{"profile":{"role":"admin","role":"view"}}',
            b'{"profiles":[{"role":"admin","role":"view"}]}',
        ):
            with self.subTest(body=body):
                self.assertIsNone(await read_json_object(_request(body), 1024))

    async def test_accepts_nested_json_object_with_unique_keys(self) -> None:
        parsed = await read_json_object(
            _request(b'{"profile":{"role":"view"},"enabled":true}'),
            maximum_bytes=1024,
        )

        self.assertEqual(parsed, {"profile": {"role": "view"}, "enabled": True})

    async def test_rejects_duplicate_framing_headers(self) -> None:
        duplicate_content_type = _request(
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-type", b"application/json"),
            ],
        )
        duplicate_content_length = _request(
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-length", b"2"),
                (b"content-length", b"2"),
            ],
        )

        self.assertIsNone(await read_json_object(duplicate_content_type, 1024))
        self.assertIsNone(await read_json_object(duplicate_content_length, 1024))

    async def test_rejects_non_decimal_or_mismatched_content_length(self) -> None:
        for content_length in ("+2", " 2", "2 ", "2,2"):
            with self.subTest(content_length=content_length):
                request = _request(
                    b"{}",
                    [
                        (b"content-type", b"application/json"),
                        (b"content-length", content_length.encode("ascii")),
                    ],
                )
                self.assertIsNone(await read_json_object(request, 1024))

        mismatched = _request(
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-length", b"3"),
            ],
        )
        self.assertIsNone(await read_json_object(mismatched, 1024))

        disconnected = _request(
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-length", b"3"),
            ],
            disconnect_after_body=True,
        )
        self.assertIsNone(await read_json_object(disconnected, 1024))

        oversized_length = _request(
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-length", b"9" * 5000),
            ],
        )
        self.assertIsNone(await read_json_object(oversized_length, 1024))

    async def test_rejects_oversized_body_and_non_scalar_unicode(self) -> None:
        oversized = await read_json_object(_request(b'{"value":"too long"}'), 8)
        non_scalar = await read_json_object(_request(b'{"value":"\\ud800"}'), 1024)

        self.assertIsNone(oversized)
        self.assertIsNone(non_scalar)

    async def test_rejects_non_json_numeric_constants_and_excessive_nesting(
        self,
    ) -> None:
        for body in (
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":-Infinity}',
        ):
            with self.subTest(body=body):
                self.assertIsNone(await read_json_object(_request(body), 16_384))

        nested = b'{"value":' * 12_000 + b"null" + b"}" * 12_000
        parsed = await read_json_object(_request(nested), 1_048_576)
        if parsed is not None:
            self.fail("excessively nested JSON must be rejected")
