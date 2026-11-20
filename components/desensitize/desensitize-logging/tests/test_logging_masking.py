"""Logging-side desensitization tests (MDC context, masking SPI, filters).

Ported from the Java `atlas-richie-desensitize-logging` test suite
(`SensitiveMdcTurboFilter` / `DefaultLoggingMaskingService`).
"""

from __future__ import annotations

import io
import logging

import pytest

from atlas_richie.desensitize_core import (
    DefaultMaskingService,
    DesensitizeProperties,
    MaskType,
    SceneOverride,
    SensitiveLogArg,
)
from atlas_richie.desensitize_logging import (
    DefaultLoggingMaskingService,
    LoggingMaskingService,
    MdcContext,
    MdcFormatter,
    SensitiveLogArgFilter,
    SensitiveMdcFilter,
    mdc_of,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_mdc():
    """Every test starts from an empty context."""
    MdcContext.clear()
    yield
    MdcContext.clear()


def _properties(**overrides) -> DesensitizeProperties:
    base = {"sensitive_keys": {"phone": MaskType.PHONE, "idCard": MaskType.ID_CARD}}
    base.update(overrides)
    return DesensitizeProperties(**base)


def _service(**overrides) -> DefaultLoggingMaskingService:
    return DefaultLoggingMaskingService(DefaultMaskingService(_properties(**overrides)))


def _record(msg: str = "hello", args: object = None, **extra) -> logging.LogRecord:
    # 标准库的 mapping 形态是「单 dict 包在 tuple 里」——LogRecord 构造时会把
    # 它拆成 dict（与 logger.info("msg %(k)s", {...}) 走同一条路）。
    if isinstance(args, dict):
        args = (args,)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestMdcContext:
    def test_put_and_get(self) -> None:
        MdcContext.put("traceId", "abc")
        assert MdcContext.get("traceId") == "abc"
        assert MdcContext.get("missing") is None

    def test_current_returns_a_copy(self) -> None:
        MdcContext.put("a", "1")
        snapshot = MdcContext.current()
        snapshot["a"] = "mutated"
        assert MdcContext.get("a") == "1"

    def test_remove_and_clear(self) -> None:
        MdcContext.put("a", "1")
        MdcContext.put("b", "2")
        MdcContext.remove("a")
        assert MdcContext.get("a") is None
        assert MdcContext.get("b") == "2"
        MdcContext.clear()
        assert MdcContext.current() == {}

    def test_remove_unknown_key_is_a_noop(self) -> None:
        MdcContext.put("a", "1")
        MdcContext.remove("zzz")
        assert MdcContext.current() == {"a": "1"}

    def test_scope_restores_on_exit(self) -> None:
        MdcContext.put("traceId", "abc")
        with MdcContext.scope(userId="u-1"):
            assert MdcContext.get("userId") == "u-1"
            assert MdcContext.get("traceId") == "abc"
        assert MdcContext.get("userId") is None
        assert MdcContext.get("traceId") == "abc"

    def test_scope_restores_on_exception(self) -> None:
        with pytest.raises(RuntimeError):
            with MdcContext.scope(userId="u-1"):
                raise RuntimeError("boom")
        assert MdcContext.get("userId") is None

    def test_writes_do_not_leak_into_a_sibling_context(self) -> None:
        """A write replaces the mapping — the ContextVar default is shared."""
        MdcContext.put("a", "1")
        MdcContext.current()["b"] = "2"          # mutating the snapshot is harmless
        assert MdcContext.current() == {"a": "1"}


class TestMaskingService:
    def test_masks_listed_keys(self) -> None:
        masked = _service().mask_mdc({"phone": "13812345678"})
        assert masked == {"phone": "138****5678"}

    def test_leaves_unlisted_keys_alone(self) -> None:
        masked = _service().mask_mdc({"orderId": "ORD-1"})
        assert masked == {"orderId": "ORD-1"}

    def test_none_in_none_out(self) -> None:
        assert _service().mask_mdc(None) is None

    def test_empty_in_empty_out(self) -> None:
        assert _service().mask_mdc({}) == {}

    def test_scene_override_is_honoured(self) -> None:
        service = _service(
            sensitive_keys={},
            log=SceneOverride(sensitive_keys={"idCard": MaskType.ID_CARD}),
        )
        masked = service.mask_mdc({"idCard": "110101199003071234"})
        assert masked == {"idCard": "110101********1234"}

    def test_failure_falls_back_to_the_original(self) -> None:
        class _Boom:
            def mask_map(self, source, scene=None):
                raise RuntimeError("core not ready")

            def mask(self, raw, mask_type, scene=None, context=None):
                raise RuntimeError("core not ready")

        service = DefaultLoggingMaskingService(_Boom())
        assert service.mask_mdc({"phone": "13812345678"}) == {"phone": "13812345678"}

    def test_to_masked_message_replaces_sensitive_args(self) -> None:
        record = _record("token=%s", (SensitiveLogArg.api_key("sk-9f8e7d"),))
        message = _service().to_masked_message(record)
        assert message is not None
        assert "sk-9f8e7d" not in message
        assert "sk-9****8e7d" in message

    def test_to_masked_message_without_args(self) -> None:
        assert _service().to_masked_message(_record("plain")) == "plain"

    def test_to_masked_message_with_none_record(self) -> None:
        assert _service().to_masked_message(None) is None

    def test_to_masked_message_with_broken_template(self) -> None:
        """模板本身坏了也不能抛 —— 日志链路不能被脱敏打断。"""
        record = _record("%d items", ("not-a-number",))
        message = _service().to_masked_message(record)
        assert isinstance(message, str)

    def test_to_masked_message_with_mapping_args(self) -> None:
        record = _record("token=%(token)s", {"token": SensitiveLogArg.password("p@ss")})
        message = _service().to_masked_message(record)
        assert message is not None
        assert "p@ss" not in message

    def test_spi_protocol_is_satisfied(self) -> None:
        assert isinstance(_service(), LoggingMaskingService)


class TestSensitiveMdcFilter:
    def test_masks_the_context(self) -> None:
        MdcContext.put("phone", "13812345678")
        record = _record("hello")
        assert SensitiveMdcFilter(_service()).filter(record) is True
        assert record.mdc == {"phone": "138****5678"}
        assert record.mdc_masked is True

    def test_empty_context_is_left_alone(self) -> None:
        record = _record("hello")
        SensitiveMdcFilter(_service()).filter(record)
        assert not hasattr(record, "mdc")

    def test_context_without_sensitive_keys_is_left_alone(self) -> None:
        MdcContext.put("orderId", "ORD-1")
        record = _record("hello")
        SensitiveMdcFilter(_service()).filter(record)
        assert not hasattr(record, "mdc")

    def test_explicit_record_mdc_wins(self) -> None:
        record = _record("hello", mdc={"phone": "13812345678"})
        SensitiveMdcFilter(_service()).filter(record)
        assert record.mdc == {"phone": "138****5678"}

    def test_context_is_not_modified_by_default(self) -> None:
        MdcContext.put("phone", "13812345678")
        SensitiveMdcFilter(_service()).filter(_record("hello"))
        assert MdcContext.get("phone") == "13812345678"

    def test_in_place_writes_the_masked_value_back(self) -> None:
        MdcContext.put("phone", "13812345678")
        SensitiveMdcFilter(_service(), in_place=True).filter(_record("hello"))
        assert MdcContext.get("phone") == "138****5678"

    def test_service_failure_does_not_break_the_chain(self) -> None:
        class _Boom:
            def mask_mdc(self, mdc):
                raise RuntimeError("boom")

            def to_masked_message(self, record):
                raise RuntimeError("boom")

        MdcContext.put("phone", "13812345678")
        record = _record("hello")
        assert SensitiveMdcFilter(_Boom()).filter(record) is True
        assert not hasattr(record, "mdc")


class TestSensitiveLogArgFilter:
    def test_replaces_sensitive_args_in_a_tuple(self) -> None:
        record = _record("token=%s", (SensitiveLogArg.api_key("sk-9f8e7d"),))
        SensitiveLogArgFilter().filter(record)
        assert record.args == ("sk-9****8e7d",)

    def test_replaces_sensitive_args_in_a_mapping(self) -> None:
        record = _record("token=%(token)s", {"token": SensitiveLogArg.password("p@ss")})
        SensitiveLogArgFilter().filter(record)
        # 密码掩码至少 6 位（不泄露长度）——对位 core 的 PasswordMaskingStrategy
        assert record.args == {"token": "******"}

    def test_leaves_plain_args_alone(self) -> None:
        record = _record("user=%s", ("u-1",))
        SensitiveLogArgFilter().filter(record)
        assert record.args == ("u-1",)

    def test_without_args_is_a_noop(self) -> None:
        record = _record("hello")
        SensitiveLogArgFilter().filter(record)
        assert record.args is None


class TestMdcFormatter:
    def test_renders_the_masked_snapshot(self) -> None:
        MdcContext.put("phone", "13812345678")
        record = _record("hello")
        SensitiveMdcFilter(_service()).filter(record)
        rendered = MdcFormatter("%(message)s").format(record)
        assert rendered == "hello [phone=138****5678]"

    def test_without_mdc_renders_only_the_message(self) -> None:
        assert MdcFormatter("%(message)s").format(_record("hello")) == "hello"

    def test_skips_none_values(self) -> None:
        record = _record("hello", mdc={"a": None, "b": "2"})
        rendered = MdcFormatter("%(message)s").format(record)
        assert rendered == "hello [b=2]"

    def test_custom_template_and_separator(self) -> None:
        record = _record("hello", mdc={"a": "1"})
        formatter = MdcFormatter("%(message)s", mdc_separator=" | ", mdc_template="{key}:{value}")
        assert formatter.format(record) == "hello | a:1"

    def test_mdc_of_prefers_the_snapshot(self) -> None:
        record = _record("hello", mdc={"a": "1"})
        assert mdc_of(record) == {"a": "1"}

    def test_mdc_of_falls_back_to_the_context(self) -> None:
        MdcContext.put("a", "1")
        assert mdc_of(_record("hello")) == {"a": "1"}


class TestEndToEnd:
    def _logger(self, service) -> tuple[logging.Logger, io.StringIO]:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(SensitiveMdcFilter(service))
        handler.addFilter(SensitiveLogArgFilter())
        handler.setFormatter(MdcFormatter("%(message)s"))
        logger = logging.getLogger("desensitize-logging-e2e")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        return logger, stream

    def test_output_carries_the_masked_value_only(self) -> None:
        logger, stream = self._logger(_service())
        MdcContext.put("phone", "13812345678")
        MdcContext.put("orderId", "ORD-1")
        logger.info("order created token=%s", SensitiveLogArg.api_key("sk-9f8e7d"))
        output = stream.getvalue()
        assert "13812345678" not in output
        assert "sk-9f8e7d" not in output
        assert "138****5678" in output
        assert "ORD-1" in output
        assert "sk-9****8e7d" in output

    def test_the_business_context_keeps_the_raw_value(self) -> None:
        logger, stream = self._logger(_service())
        MdcContext.put("phone", "13812345678")
        logger.info("order created")
        assert MdcContext.get("phone") == "13812345678"
        assert "13812345678" not in stream.getvalue()
