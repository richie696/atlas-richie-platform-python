"""Unit tests for idempotency-key strategies."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel.primitives import (
    CallableIdempotencyKey,
    NeverIdempotencyKey,
    StatelessIdempotencyKey,
)


class _Operation:
    async def __call__(self) -> int:
        return 1


class StatelessIdempotencyKeyTest(unittest.TestCase):
    def test_returns_a_stable_hashable_tag(self) -> None:
        op = _Operation()
        key = StatelessIdempotencyKey()
        self.assertEqual("stateless", key.derive(op))
        self.assertEqual(key.derive(op), key.derive(op))


class NeverIdempotencyKeyTest(unittest.TestCase):
    def test_always_returns_none(self) -> None:
        key = NeverIdempotencyKey()
        op = _Operation()
        self.assertIsNone(key.derive(op))
        self.assertIsNone(key.derive(op))


class CallableIdempotencyKeyTest(unittest.TestCase):
    def test_uses_supplied_function(self) -> None:
        op = _Operation()

        def derive(o: object) -> str:
            return f"tag-for-{type(o).__name__}"

        key = CallableIdempotencyKey(derive)
        self.assertEqual("tag-for-_Operation", key.derive(op))

    def test_supports_none_for_non_idempotent(self) -> None:
        def derive(_: object) -> None:
            return None

        key = CallableIdempotencyKey(derive)
        self.assertIsNone(key.derive(_Operation()))

    def test_rejects_non_callable(self) -> None:
        with self.assertRaises(TypeError):
            CallableIdempotencyKey("not-a-callable")  # type: ignore[arg-type]
