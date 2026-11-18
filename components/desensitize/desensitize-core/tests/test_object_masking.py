"""Object-graph and log-safe serialization tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import ClassVar

import pytest

from atlas_richie.desensitize_core import (
    DefaultMaskingService,
    DefaultObjectMaskingService,
    DesensitizeProperties,
    MaskRuleRegistry,
    MaskScene,
    MaskType,
    SafeLogSerializer,
    SceneOverride,
    SensitiveLogArg,
    sensitive_field,
    transient_field,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def serializer() -> SafeLogSerializer:
    props = DesensitizeProperties(
        sensitive_keys={"phone": MaskType.PHONE, "email": MaskType.EMAIL, "password": MaskType.PASSWORD}
    )
    service = DefaultMaskingService(props)
    return SafeLogSerializer(service, MaskRuleRegistry(props))


@dataclass
class User:
    name: str
    phone: str = sensitive_field(MaskType.PHONE)
    email: str = sensitive_field(MaskType.EMAIL, scenes=(MaskScene.LOG,))
    secret: str = transient_field(default="hidden")
    kind: ClassVar[str] = "user"


@dataclass
class Team:
    label: str
    lead: User
    members: list[User] = field(default_factory=list)


class TestPrimitives:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, "null"), ("abc", '"abc"'), (True, "true"), (False, "false"), (42, "42"), (1.5, "1.5")],
    )
    def test_scalar_rendering(self, serializer: SafeLogSerializer, value, expected: str) -> None:
        assert serializer.to_safe_json(value) == expected

    def test_bool_is_not_rendered_as_int(self, serializer: SafeLogSerializer) -> None:
        assert serializer.to_safe_json([True, False, 1, 0]) == "[true,false,1,0]"

    def test_output_is_valid_json_even_with_control_chars(self, serializer: SafeLogSerializer) -> None:
        text = 'quote" back\\slash \n \r \t \x00 \x0b'
        rendered = serializer.to_safe_json(text)
        assert json.loads(rendered) == text

    def test_non_ascii_is_not_escaped(self, serializer: SafeLogSerializer) -> None:
        assert serializer.to_safe_json("你好") == '"你好"'


class TestMapsAndCollections:
    def test_sensitive_keys_masked(self, serializer: SafeLogSerializer) -> None:
        rendered = serializer.to_safe_json({"phone": "13812348000", "count": 3})
        assert json.loads(rendered) == {"phone": "138****8000", "count": 3}

    def test_nested_map_is_masked(self, serializer: SafeLogSerializer) -> None:
        rendered = serializer.to_safe_json({"outer": {"email": "alice@example.com"}})
        assert json.loads(rendered) == {"outer": {"email": "a***@example.com"}}

    def test_scene_propagates_into_nested_values(self) -> None:
        """Deviation from Java, which hardcodes LOG for nested map values.

        With an API_RESPONSE-only sensitive key nested one level down, Java would
        serialize it under LOG and leave it unmasked. Honouring the caller's scene
        masks it, which is the actual contract.
        """
        props = DesensitizeProperties(
            api_response=SceneOverride({"token": MaskType.PASSWORD}),
        )
        service = DefaultMaskingService(props)
        nested = SafeLogSerializer(service, MaskRuleRegistry(props))
        rendered = nested.to_safe_json({"a": {"token": "abcdef"}}, MaskScene.API_RESPONSE)
        assert json.loads(rendered)["a"]["token"] == "******"
        # Under LOG the key is not sensitive, so it stays in the clear.
        log_view = nested.to_safe_json({"a": {"token": "abcdef"}}, MaskScene.LOG)
        assert json.loads(log_view)["a"]["token"] == "abcdef"

    def test_list_of_maps(self, serializer: SafeLogSerializer) -> None:
        rendered = serializer.to_safe_json([{"phone": "13812348000"}, {"phone": "13912348000"}])
        assert [item["phone"] for item in json.loads(rendered)] == ["138****8000", "139****8000"]

    def test_tuple_and_set_render_as_arrays(self, serializer: SafeLogSerializer) -> None:
        assert serializer.to_safe_json((1, 2)) == "[1,2]"
        assert json.loads(serializer.to_safe_json({1})) == [1]

    def test_to_safe_string(self, serializer: SafeLogSerializer) -> None:
        assert json.loads(serializer.to_safe_string({"phone": "13812348000"})) == {"phone": "138****8000"}
        assert serializer.to_safe_string(None) == "null"


class TestDepthAndCycles:
    def test_depth_cap(self, serializer: SafeLogSerializer) -> None:
        value: object = "leaf"
        for _ in range(12):
            value = {"n": value}
        assert "[max-depth]" in serializer.to_safe_json(value)

    def test_self_referencing_map_terminates(self, serializer: SafeLogSerializer) -> None:
        cyclic: dict = {"phone": "13812348000"}
        cyclic["self"] = cyclic
        rendered = serializer.to_safe_json(cyclic)
        assert "[circular]" in rendered
        assert json.loads(rendered)["phone"] == "138****8000"

    def test_self_referencing_dataclass_terminates(self, serializer: SafeLogSerializer) -> None:
        @dataclass
        class Node:
            label: str
            child: object = None

        node = Node("root")
        node.child = node
        assert "[max-depth]" in serializer.to_safe_json(node)

    def test_mask_map_alone_is_bounded(self) -> None:
        service = DefaultMaskingService()
        cyclic: dict = {}
        cyclic["self"] = cyclic
        assert service.mask_map(cyclic) == {"self": {"[circular]": "[circular]"}}


class TestDataclassBeans:
    def test_marked_fields_masked_and_transient_skipped(self, serializer: SafeLogSerializer) -> None:
        rendered = json.loads(serializer.to_safe_json(User("张三丰", "13812348000", "alice@example.com")))
        assert rendered["name"] == "张三丰", "unmarked string fields are not masked"
        assert rendered["phone"] == "138****8000"
        assert rendered["email"] == "a***@example.com"
        assert "secret" not in rendered, "transient fields are excluded"
        assert "kind" not in rendered, "ClassVar is not an instance field"

    def test_marker_scenes_are_respected(self, serializer: SafeLogSerializer) -> None:
        user = User("张三丰", "13812348000", "alice@example.com")
        log_view = json.loads(serializer.to_safe_json(user, MaskScene.LOG))
        api_view = json.loads(serializer.to_safe_json(user, MaskScene.API_RESPONSE))
        assert log_view["email"] == "a***@example.com"
        assert api_view["email"] == "alice@example.com", "email marker is LOG-only"
        assert api_view["phone"] == "138****8000", "phone marker covers both scenes"

    def test_nested_dataclass_and_list(self, serializer: SafeLogSerializer) -> None:
        team = Team("core", User("李四", "13912348000", "bob@example.com"),
                    [User("王五", "13712348000", "carol@example.com")])
        rendered = json.loads(serializer.to_safe_json(team))
        assert rendered["lead"]["phone"] == "139****8000"
        assert rendered["members"][0]["phone"] == "137****8000"
        assert rendered["label"] == "core"

    def test_config_driven_field_rules_without_marker(self) -> None:
        @dataclass
        class Plain:
            phone: str

        key = f"{Plain.__module__}.{Plain.__qualname__}"
        props = DesensitizeProperties(fields={key: {"phone": MaskType.PHONE}})
        service = DefaultMaskingService(props)
        serializer = SafeLogSerializer(service, MaskRuleRegistry(props))
        assert json.loads(serializer.to_safe_json(Plain("13812348000")))["phone"] == "138****8000"

    def test_plain_object_with_dict(self, serializer: SafeLogSerializer) -> None:
        class Bag:
            def __init__(self) -> None:
                self.phone = "13812348000"
                self.n = 1

        rendered = json.loads(serializer.to_safe_json(Bag()))
        assert rendered == {"phone": "13812348000", "n": 1}, "no marker and no config rule → unmasked"

    def test_object_with_slots(self, serializer: SafeLogSerializer) -> None:
        class Slotted:
            __slots__ = ("phone",)

            def __init__(self) -> None:
                self.phone = "13812348000"

        assert json.loads(serializer.to_safe_json(Slotted())) == {"phone": "13812348000"}


class TestSensitiveLogArg:
    def test_str_masks_and_never_leaks_raw(self) -> None:
        arg = SensitiveLogArg.phone("13812348000")
        assert str(arg) == "138****8000"
        assert "13812348000" not in str(arg)
        assert "13812348000" not in repr(arg)

    def test_explicit_service_is_used(self) -> None:
        service = DefaultMaskingService(DesensitizeProperties(default_mask_char="#"))
        assert str(SensitiveLogArg.phone("13812348000", service)) == "138####8000"

    @pytest.mark.parametrize(
        ("factory", "value", "expected"),
        [
            ("email", "alice@example.com", "a***@example.com"),
            ("name", "张三丰", "张**"),
            ("password", "abc", "******"),
            ("id_card", "110101199003077758", "110101********7758"),
        ],
    )
    def test_factories(self, factory: str, value: str, expected: str) -> None:
        assert str(getattr(SensitiveLogArg, factory)(value)) == expected

    def test_none_value(self) -> None:
        assert str(SensitiveLogArg.phone(None)) == "null"

    def test_raw_value_is_explicit_only(self) -> None:
        arg = SensitiveLogArg.phone("13812348000")
        assert arg.raw_value == "13812348000"
        assert arg.mask_type is MaskType.PHONE

    def test_safe_in_logging_interpolation(self, caplog) -> None:
        import logging

        logger = logging.getLogger("desensitize.test")
        with caplog.at_level(logging.INFO):
            logger.info("login attempt for %s", SensitiveLogArg.phone("13812348000"))
        assert "13812348000" not in caplog.text
        assert "138****8000" in caplog.text


class TestObjectMaskingServiceFacade:
    def test_delegates_to_serializer(self, serializer: SafeLogSerializer) -> None:
        facade = DefaultObjectMaskingService(serializer)
        assert facade.to_safe_json({"phone": "13812348000"}) == serializer.to_safe_json({"phone": "13812348000"})
        assert facade.to_safe_string(None) == "null"
