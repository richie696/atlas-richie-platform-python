"""Pydantic v2 响应脱敏：字段级标记、按名规则、嵌套与列表、场景门控。"""

from __future__ import annotations

from typing import Annotated, List, Optional

import pytest
from pydantic import BaseModel

from atlas_richie.desensitize_core import (
    DefaultMaskingService,
    DesensitizeProperties,
    MaskScene,
    MaskType,
)
from atlas_richie.desensitize_pydantic import (
    PydanticMaskingSerializer,
    Transient,
    sensitive,
)

pytestmark = pytest.mark.unit


class Address(BaseModel):
    city: str
    detail: Annotated[str, sensitive(MaskType.ADDRESS)]


class User(BaseModel):
    name: str
    phone: Annotated[str, sensitive(MaskType.PHONE)]
    address: Address
    cards: List[Address]
    optional_addr: Optional[Address] = None
    secret_note: Annotated[str, Transient()] = ""


@pytest.fixture
def serializer() -> PydanticMaskingSerializer:
    return PydanticMaskingSerializer()


@pytest.fixture
def user() -> User:
    return User(
        name="张三",
        phone="13812345678",
        address=Address(city="杭州", detail="文一路 1 号"),
        cards=[Address(city="北京", detail="长安街 2 号")],
        optional_addr=Address(city="上海", detail="南京路 3 号"),
        secret_note="内部备注",
    )


class TestFieldMarkers:
    def test_phone_is_masked(self, serializer, user) -> None:
        safe = serializer.to_safe_dict(user)
        assert safe["phone"] == "138****5678"
        assert "13812345678" not in serializer.to_safe_json(user)

    def test_marker_does_not_mutate_the_model(self, serializer, user) -> None:
        serializer.to_safe_dict(user)
        assert user.phone == "13812345678"

    def test_non_marked_fields_pass_through(self, serializer, user) -> None:
        assert serializer.to_safe_dict(user)["name"] == "张三"

    def test_transient_field_is_excluded(self, serializer, user) -> None:
        assert "secret_note" not in serializer.to_safe_dict(user)
        assert "secret_note" not in serializer.to_safe_json(user)


class TestNesting:
    def test_nested_model_markers_apply(self, serializer, user) -> None:
        # ADDRESS 掩蔽保留可读前缀（Java 同语义），只遮门牌段
        assert serializer.to_safe_dict(user)["address"]["detail"] == "文一路 1 *"
        assert "1 号" not in serializer.to_safe_json(user)

    def test_optional_nested_model(self, serializer, user) -> None:
        assert serializer.to_safe_dict(user)["optional_addr"]["detail"] == "南京路 3 *"

    def test_list_of_models(self, serializer, user) -> None:
        cards = serializer.to_safe_dict(user)["cards"]
        assert cards[0]["detail"] == "长安街 2 *"
        assert cards[0]["city"] == "北京"

    def test_bare_list_annotation(self, serializer) -> None:
        class Holder(BaseModel):
            items: list[Address] = []

        safe = serializer.to_safe_dict(Holder(items=[Address(city="c", detail="d 号")]))
        assert safe["items"][0]["detail"] == "***"  # 短输入整段遮蔽
        assert safe["items"][0]["city"] == "c"

    def test_nested_transient_is_dropped(self, serializer) -> None:
        class Inner(BaseModel):
            keep: str
            drop: Annotated[str, Transient()] = ""

        class Outer(BaseModel):
            inner: Inner

        safe = serializer.to_safe_dict(Outer(inner=Inner(keep="k", drop="d")))
        assert safe["inner"] == {"keep": "k"}

    def test_plain_nested_dicts_pass_marker_walk_through(self, serializer) -> None:
        class Holder(BaseModel):
            blob: dict

        safe = serializer.to_safe_dict(Holder(blob={"x": "y"}))
        assert safe["blob"] == {"x": "y"}


class TestNameBasedRules:
    def _service_with_keys(self, keys: dict) -> DefaultMaskingService:
        return DefaultMaskingService(DesensitizeProperties(sensitive_keys=keys))

    def test_name_rule_masks_unmarked_field(self) -> None:
        class Login(BaseModel):
            password: str
            note: str

        serializer = PydanticMaskingSerializer(
            self._service_with_keys({"password": MaskType.PASSWORD})
        )
        safe = serializer.to_safe_dict(Login(password="p@ss", note="ok"))
        assert safe["password"] == "******"
        assert safe["note"] == "ok"

    def test_no_name_rules_by_default(self, serializer) -> None:
        """sensitive_keys 默认为空（同 Java）：password 明文是配置决定，不是缺陷。"""

        class Login(BaseModel):
            password: str

        assert serializer.to_safe_dict(Login(password="p@ss"))["password"] == "p@ss"

    def test_marker_overrides_name_rule(self) -> None:
        class Login(BaseModel):
            password: Annotated[str, sensitive(MaskType.PHONE)]

        serializer = PydanticMaskingSerializer(
            self._service_with_keys({"password": MaskType.PASSWORD})
        )
        assert serializer.to_safe_dict(Login(password="13812345678"))["password"] == "138****5678"

    def test_name_rules_reach_nested_plain_dicts(self) -> None:
        class Holder(BaseModel):
            blob: dict

        serializer = PydanticMaskingSerializer(
            self._service_with_keys({"password": MaskType.PASSWORD})
        )
        safe = serializer.to_safe_dict(Holder(blob={"password": "p", "ok": 1}))
        assert safe["blob"]["password"] == "******"


class TestSceneGating:
    def test_marker_limited_to_log_does_not_apply_to_api_response(self) -> None:
        class OnlyLog(BaseModel):
            phone: Annotated[str, sensitive(MaskType.PHONE, (MaskScene.LOG,))]

        serializer = PydanticMaskingSerializer()
        assert serializer.to_safe_dict(OnlyLog(phone="13812345678"))["phone"] == "13812345678"

    def test_marker_limited_to_log_applies_for_log_scene(self) -> None:
        class OnlyLog(BaseModel):
            phone: Annotated[str, sensitive(MaskType.PHONE, (MaskScene.LOG,))]

        serializer = PydanticMaskingSerializer()
        safe = serializer.to_safe_dict(OnlyLog(phone="13812345678"), MaskScene.LOG)
        assert safe["phone"] == "138****5678"

    def test_scene_falls_back_to_name_rule_when_marker_gated_out(self) -> None:
        class OnlyLog(BaseModel):
            password: Annotated[str, sensitive(MaskType.PHONE, (MaskScene.LOG,))]

        serializer = PydanticMaskingSerializer(
            DefaultMaskingService(
                DesensitizeProperties(sensitive_keys={"password": MaskType.PASSWORD})
            )
        )
        assert serializer.to_safe_dict(OnlyLog(password="x"))["password"] == "******"


class TestOutputForms:
    def test_json_is_parseable_and_stable(self, serializer, user) -> None:
        import json

        parsed = json.loads(serializer.to_safe_json(user))
        assert parsed == serializer.to_safe_dict(user)

    def test_json_round_trip_contains_no_plaintext(self, serializer, user) -> None:
        payload = serializer.to_safe_json(user)
        assert "13812345678" not in payload
        assert "文一路 1 号" not in payload
        assert "长安街 2 号" not in payload
        assert "内部备注" not in payload

    def test_non_model_rejected(self, serializer) -> None:
        with pytest.raises(TypeError, match="BaseModel"):
            serializer.to_safe_dict({"not": "a model"})

    def test_datetime_and_enum_dump_as_json_scalars(self, serializer) -> None:
        from datetime import datetime
        from enum import StrEnum

        class Level(StrEnum):
            ADMIN = "admin"

        class Session(BaseModel):
            at: datetime
            level: Level

        safe = serializer.to_safe_dict(Session(at=datetime(2026, 1, 1), level=Level.ADMIN))
        assert isinstance(safe["at"], str)
        assert safe["level"] == "admin"


class TestCustomService:
    def test_disabled_masking_passes_everything_through(self) -> None:
        class Secret(BaseModel):
            phone: Annotated[str, sensitive(MaskType.PHONE)]

        disabled = DefaultMaskingService(DesensitizeProperties(enabled=False))
        serializer = PydanticMaskingSerializer(disabled)
        assert serializer.to_safe_dict(Secret(phone="13812345678"))["phone"] == "13812345678"

    def test_custom_key_map_via_injected_service(self) -> None:
        class Profile(BaseModel):
            token: str

        serializer = PydanticMaskingSerializer(
            DefaultMaskingService(
                DesensitizeProperties(sensitive_keys={"token": MaskType.PASSWORD})
            )
        )
        assert serializer.to_safe_dict(Profile(token="abc"))["token"] == "******"