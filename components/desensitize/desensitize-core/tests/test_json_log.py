"""JSON 日志消息脱敏与 logging.Filter 接入。"""

from __future__ import annotations

import json
import logging

import pytest

from atlas_richie.desensitize_core import (
    DefaultMaskingService,
    DesensitizeProperties,
    JsonLogMaskingFilter,
    MaskScene,
    MaskType,
    mask_json_message,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def masking() -> DefaultMaskingService:
    return DefaultMaskingService(
        DesensitizeProperties(
            sensitive_keys={"password": MaskType.PASSWORD, "phone": MaskType.PHONE}
        )
    )


class TestMaskJsonMessage:
    def test_json_object_is_masked(self, masking) -> None:
        message = '{"user":"richie","password":"p@ss","phone":"13812345678"}'
        result = json.loads(mask_json_message(message, masking))
        assert result["user"] == "richie"
        assert result["password"] == "******"
        assert result["phone"] == "138****5678"

    def test_nested_json_is_masked(self, masking) -> None:
        message = '{"outer":{"password":"p@ss"},"list":[{"phone":"13812345678"}]}'
        result = json.loads(mask_json_message(message, masking))
        assert result["outer"]["password"] == "******"
        assert result["list"][0]["phone"] == "138****5678"

    def test_plain_text_passthrough(self, masking) -> None:
        assert mask_json_message("user logged in", masking) == "user logged in"

    def test_json_array_passthrough(self, masking) -> None:
        message = '[{"password":"p@ss"}]'
        assert mask_json_message(message, masking) == message, "仅处理 JSON 对象，数组透传"

    def test_malformed_json_passthrough(self, masking) -> None:
        assert mask_json_message("{bad json", masking) == "{bad json"

    def test_braces_but_not_json_passthrough(self, masking) -> None:
        assert mask_json_message("{not json at all}", masking) == "{not json at all}"

    def test_none_and_blank_passthrough(self, masking) -> None:
        assert mask_json_message(None, masking) is None
        assert mask_json_message("   ", masking) == "   "

    def test_whitespace_around_json_is_trimmed_for_detection(self, masking) -> None:
        result = json.loads(mask_json_message('  {"password":"p@ss"}  ', masking))
        assert result["password"] == "******"

    def test_unicode_preserved(self, masking) -> None:
        result = json.loads(mask_json_message('{"name":"张三","password":"p"}', masking))
        assert result["name"] == "张三"

    def test_masking_failure_passes_through(self) -> None:
        class _Broken:
            def mask_map(self, source, scene):
                raise RuntimeError("masking down")

        message = '{"password":"p@ss"}'
        assert mask_json_message(message, _Broken()) == message, "脱敏失败不得丢日志"

    def test_scene_is_forwarded(self) -> None:
        seen = []

        class _Recording:
            def mask_map(self, source, scene):
                seen.append(scene)
                return source

        mask_json_message('{"a":1}', _Recording(), MaskScene.AUDIT)
        assert seen == [MaskScene.AUDIT]


class TestLoggingFilter:
    def _record(self, msg, *args) -> logging.LogRecord:
        return logging.LogRecord("test", logging.INFO, __file__, 1, msg, args, None)

    def test_filter_masks_formatted_message(self, masking) -> None:
        record = self._record('{"password":"%s"}', "p@ss")
        assert JsonLogMaskingFilter(masking).filter(record) is True
        assert json.loads(record.getMessage())["password"] == "******"
        assert record.args == ()

    def test_filter_leaves_plain_text(self, masking) -> None:
        record = self._record("hello %s", "world")
        JsonLogMaskingFilter(masking).filter(record)
        assert record.getMessage() == "hello world"

    def test_filter_returns_true_always(self, masking) -> None:
        record = self._record("{bad", None)
        assert JsonLogMaskingFilter(masking).filter(record) is True

    def test_filter_integrates_with_logger(self, masking, caplog) -> None:
        logger = logging.getLogger("test.json.masking")
        logger.addFilter(JsonLogMaskingFilter(masking))
        logger.setLevel(logging.INFO)
        try:
            with caplog.at_level(logging.INFO, logger="test.json.masking"):
                logger.info('{"password":"p@ss","ok":1}')
            assert any("******" in r.getMessage() for r in caplog.records)
            assert all("p@ss" not in r.getMessage() for r in caplog.records)
        finally:
            logger.filters.clear()

    def test_broken_masking_does_not_break_logging(self, caplog) -> None:
        class _Broken:
            def mask_map(self, source, scene):
                raise RuntimeError("down")

        logger = logging.getLogger("test.json.broken")
        logger.addFilter(JsonLogMaskingFilter(_Broken()))
        logger.setLevel(logging.INFO)
        try:
            with caplog.at_level(logging.INFO, logger="test.json.broken"):
                logger.info('{"password":"p@ss"}')
            assert any("p@ss" in r.getMessage() for r in caplog.records), "脱敏故障时日志仍须输出"
        finally:
            logger.filters.clear()