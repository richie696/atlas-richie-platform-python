"""Masking contract tests.

Strategy expectations are additionally pinned by a 600-case randomised
differential run against the compiled Java strategies (byte-identical output).
Service/registry/permission expectations are ported from the Java module's
`MaskingServiceTest`, `SensitiveKeyRegistryTest`, `MaskRuleRegistryTest` and
`DefaultMaskPermissionEvaluatorTest`.
"""

from __future__ import annotations

import pytest

from atlas_richie.desensitize_core import (
    BankCardMaskingStrategy,
    DefaultMaskPermissionEvaluator,
    DefaultMaskingService,
    DesensitizeProperties,
    EmailMaskingStrategy,
    MaskContext,
    MaskRule,
    MaskRuleRegistry,
    MaskScene,
    MaskType,
    MaskingStrategyRegistry,
    NameMaskingStrategy,
    PasswordMaskingStrategy,
    Permission,
    SceneOverride,
    SensitiveKeyRegistry,
    TypeRule,
    default_keep_left,
    default_keep_right,
    default_mask_length,
)

pytestmark = pytest.mark.unit


class TestStrategies:
    def test_phone_keeps_3_and_4(self) -> None:
        rule = MaskRule.of(MaskType.PHONE)
        assert MaskingStrategyRegistry().require(MaskType.PHONE).mask("13812348000", rule) == "138****8000"

    def test_id_card_keeps_6_and_4(self) -> None:
        rule = MaskRule.of(MaskType.ID_CARD)
        assert MaskingStrategyRegistry().require(MaskType.ID_CARD).mask("110101199003077758", rule) == "110101********7758"

    def test_keep_edge_masks_everything_when_too_short(self) -> None:
        rule = MaskRule(MaskType.PHONE, 3, 4, "*", None, None)
        assert MaskingStrategyRegistry().require(MaskType.PHONE).mask("1234567", rule) == "*******"

    def test_api_key_uses_fixed_mask_length(self) -> None:
        rule = MaskRule.of(MaskType.API_KEY)
        assert rule.mask_length == 4
        raw = "sk-abcdefghijklmnopqrstuvwxyz"
        # first 4 + exactly 4 masks + last 4, regardless of the real middle length
        assert MaskingStrategyRegistry().require(MaskType.API_KEY).mask(raw, rule) == raw[:4] + "****" + raw[-4:]

    def test_bank_card_grouped_format_ignores_mask_char(self) -> None:
        rule = MaskRule(MaskType.BANK_CARD, 4, 4, "#", None, None)
        assert BankCardMaskingStrategy().mask("6222021234567890123", rule) == "6222 **** **** 0123"

    def test_bank_card_strips_ascii_whitespace(self) -> None:
        rule = MaskRule.of(MaskType.BANK_CARD)
        assert BankCardMaskingStrategy().mask("6222 0212 3456 7890", rule) == "6222 **** **** 7890"

    def test_bank_card_short_input_masks_original_length(self) -> None:
        rule = MaskRule.of(MaskType.BANK_CARD, "#")
        assert BankCardMaskingStrategy().mask("1234 5678", rule) == "#########"

    def test_email_keeps_domain_and_first_char(self) -> None:
        rule = MaskRule.of(MaskType.EMAIL)
        assert EmailMaskingStrategy().mask("alice@example.com", rule) == "a***@example.com"

    def test_email_single_char_local_part_is_kept(self) -> None:
        assert EmailMaskingStrategy().mask("a@b.com", MaskRule.of(MaskType.EMAIL)) == "a***@b.com"

    def test_email_without_at_masks_up_to_three(self) -> None:
        rule = MaskRule.of(MaskType.EMAIL, "#")
        assert EmailMaskingStrategy().mask("abcdef", rule) == "###"
        assert EmailMaskingStrategy().mask("ab", rule) == "##"

    def test_email_leading_at_is_invalid(self) -> None:
        assert EmailMaskingStrategy().mask("@example.com", MaskRule.of(MaskType.EMAIL, "#")) == "###"

    def test_name_keeps_first_character(self) -> None:
        rule = MaskRule.of(MaskType.NAME)
        assert NameMaskingStrategy().mask("张三丰", rule) == "张**"
        assert NameMaskingStrategy().mask("张", rule) == "*"

    def test_password_never_shorter_than_six(self) -> None:
        rule = MaskRule.of(MaskType.PASSWORD)
        assert PasswordMaskingStrategy().mask("abc", rule) == "******"
        assert PasswordMaskingStrategy().mask("abcdefgh", rule) == "********"

    @pytest.mark.parametrize("strategy_type", list(MaskType))
    def test_none_and_empty_pass_through(self, strategy_type: MaskType) -> None:
        if strategy_type is MaskType.CUSTOM:
            pytest.skip("CUSTOM has no built-in strategy")
        strategy = MaskingStrategyRegistry().require(strategy_type)
        rule = MaskRule.of(strategy_type)
        assert strategy.mask(None, rule) is None
        assert strategy.mask("", rule) == ""


class TestRuleDefaults:
    @pytest.mark.parametrize(
        ("mask_type", "left", "right", "length"),
        [
            (MaskType.PHONE, 3, 4, None),
            (MaskType.ID_CARD, 6, 4, None),
            (MaskType.BANK_CARD, 4, 4, None),
            (MaskType.NAME, 1, 0, None),
            (MaskType.ADDRESS, 6, 0, None),
            (MaskType.API_KEY, 4, 4, 4),
            (MaskType.EMAIL, 0, 0, None),
            (MaskType.PASSWORD, 0, 0, None),
            (MaskType.CUSTOM, 0, 0, None),
        ],
    )
    def test_defaults(self, mask_type: MaskType, left: int, right: int, length: int | None) -> None:
        assert default_keep_left(mask_type) == left
        assert default_keep_right(mask_type) == right
        assert default_mask_length(mask_type) == length


class TestStrategyRegistry:
    def test_custom_type_has_no_strategy(self) -> None:
        with pytest.raises(RuntimeError, match="CUSTOM"):
            MaskingStrategyRegistry().require(MaskType.CUSTOM)

    def test_custom_type_is_served_by_a_registered_extension_strategy(self) -> None:
        class _Extension:
            def supports(self, mask_type: MaskType) -> bool:
                return mask_type is MaskType.CUSTOM

            def mask(self, raw, rule):
                return f"<{rule.custom_strategy}>"

        registry = MaskingStrategyRegistry([_Extension()])
        rule = MaskRule(MaskType.CUSTOM, 0, 0, "*", "beanName")

        assert registry.require(MaskType.CUSTOM).mask("payload", rule) == "<beanName>"

    def test_first_registration_wins(self) -> None:
        class _Override:
            def supports(self, mask_type: MaskType) -> bool:
                return mask_type is MaskType.PHONE

            def mask(self, raw, rule):
                return "override"

        registry = MaskingStrategyRegistry([_Override()])
        assert registry.require(MaskType.PHONE).mask("13812348000", MaskRule.of(MaskType.PHONE)) == "override"


class TestSensitiveKeyRegistry:
    def test_resolve_ignores_case(self) -> None:
        props = DesensitizeProperties(sensitive_keys={"Phone": MaskType.PHONE})
        registry = SensitiveKeyRegistry(props)
        assert registry.resolve("Phone", MaskScene.API_RESPONSE) is MaskType.PHONE
        assert registry.resolve("PHONE", MaskScene.LOG) is MaskType.PHONE

    def test_scene_override(self) -> None:
        props = DesensitizeProperties(
            api_response=SceneOverride({"token": MaskType.EMAIL}),
            log=SceneOverride({"token": MaskType.PASSWORD}),
        )
        registry = SensitiveKeyRegistry(props)
        assert registry.resolve("token", MaskScene.API_RESPONSE) is MaskType.EMAIL
        assert registry.resolve("token", MaskScene.LOG) is MaskType.PASSWORD

    def test_audit_inherits_log_overrides(self) -> None:
        props = DesensitizeProperties(log=SceneOverride({"token": MaskType.PASSWORD}))
        registry = SensitiveKeyRegistry(props)
        assert registry.resolve("token", MaskScene.AUDIT) is MaskType.PASSWORD

    def test_exception_scene_has_only_global_keys(self) -> None:
        props = DesensitizeProperties(
            sensitive_keys={"phone": MaskType.PHONE},
            log=SceneOverride({"token": MaskType.PASSWORD}),
        )
        registry = SensitiveKeyRegistry(props)
        assert registry.resolve("token", MaskScene.EXCEPTION) is None
        assert registry.resolve("phone", MaskScene.EXCEPTION) is MaskType.PHONE

    def test_unknown_key_and_none(self) -> None:
        registry = SensitiveKeyRegistry(DesensitizeProperties())
        assert registry.resolve("nope", MaskScene.LOG) is None
        assert registry.resolve(None, MaskScene.LOG) is None


class TestMaskRuleRegistry:
    def test_to_rule_uses_custom_type_rule_and_default_mask_char(self) -> None:
        props = DesensitizeProperties(
            default_mask_char="x", type_rules={MaskType.PHONE: TypeRule(keep_left=2, keep_right=2)}
        )
        rule = MaskRuleRegistry(props).to_rule(MaskType.PHONE)
        assert (rule.keep_left, rule.keep_right, rule.mask_char) == (2, 2, "x")

    def test_to_rule_uses_configured_fixed_mask_length(self) -> None:
        props = DesensitizeProperties(type_rules={MaskType.PHONE: TypeRule(mask_length=6)})
        assert MaskRuleRegistry(props).to_rule(MaskType.PHONE).mask_length == 6

    def test_to_rule_falls_back_when_type_rule_partial(self) -> None:
        props = DesensitizeProperties(type_rules={MaskType.EMAIL: TypeRule()})
        rule = MaskRuleRegistry(props).to_rule(MaskType.EMAIL)
        assert rule.keep_left == default_keep_left(MaskType.EMAIL)
        assert rule.keep_right == default_keep_right(MaskType.EMAIL)
        assert rule.mask_char == props.default_mask_char

    def test_resolve_field_type_from_config(self) -> None:
        class Profile:
            secret: str

        key = f"{Profile.__module__}.{Profile.__qualname__}"
        props = DesensitizeProperties(fields={key: {"secret": MaskType.PASSWORD}})
        registry = MaskRuleRegistry(props)
        assert registry.resolve_field_type(Profile, "secret", MaskScene.LOG) is MaskType.PASSWORD
        assert registry.resolve_field_type(Profile, "missing", MaskScene.LOG) is None
        assert registry.resolve_field_type(None, "secret", MaskScene.LOG) is None
        assert registry.resolve_field_type(Profile, None, MaskScene.LOG) is None


class TestPermissionEvaluator:
    def test_disabled_permission_always_masks(self) -> None:
        evaluator = DefaultMaskPermissionEvaluator(DesensitizeProperties())
        assert evaluator.should_mask(MaskContext.of(MaskScene.LOG).with_roles({"admin"})) is True

    def test_enabled_without_plain_roles_masks(self) -> None:
        props = DesensitizeProperties(permission=Permission(enabled=True))
        assert DefaultMaskPermissionEvaluator(props).should_mask(MaskContext.of(MaskScene.LOG)) is True

    def test_plain_role_gets_plaintext(self) -> None:
        props = DesensitizeProperties(permission=Permission(enabled=True, plain_text_roles={"auditor"}))
        evaluator = DefaultMaskPermissionEvaluator(props)
        assert evaluator.should_mask(MaskContext.of(MaskScene.LOG).with_roles({"auditor"})) is False
        assert evaluator.should_mask(MaskContext.of(MaskScene.LOG).with_roles({"guest"})) is True
        assert evaluator.should_mask(MaskContext.of(MaskScene.LOG)) is True


class TestMaskingService:
    def test_mask_phone_default_scene(self) -> None:
        assert DefaultMaskingService().mask("13812348000", MaskType.PHONE) == "138****8000"

    def test_none_passes_through(self) -> None:
        assert DefaultMaskingService().mask(None, MaskType.PHONE) is None

    def test_global_switch_off_returns_plaintext(self) -> None:
        service = DefaultMaskingService(DesensitizeProperties(enabled=False))
        assert service.mask("13812348000", MaskType.PHONE) == "13812348000"

    def test_scene_switch_off_returns_plaintext(self) -> None:
        props = DesensitizeProperties(scenes={"log": False})
        service = DefaultMaskingService(props)
        assert service.mask("13812348000", MaskType.PHONE) == "13812348000"
        assert service.mask("13812348000", MaskType.PHONE, MaskScene.API_RESPONSE) == "138****8000"

    def test_permission_plaintext_role_skips_masking(self) -> None:
        props = DesensitizeProperties(permission=Permission(enabled=True, plain_text_roles={"auditor"}))
        service = DefaultMaskingService(props)
        context = MaskContext.of(MaskScene.LOG).with_roles({"auditor"})
        assert service.mask("13812348000", MaskType.PHONE, context=context) == "13812348000"

    def test_mask_map_resolves_sensitive_keys_and_recurses(self) -> None:
        props = DesensitizeProperties(sensitive_keys={"phone": MaskType.PHONE, "email": MaskType.EMAIL})
        service = DefaultMaskingService(props)
        result = service.mask_map(
            {"phone": "13812348000", "count": 3, "nested": {"email": "alice@example.com"}},
            MaskScene.API_RESPONSE,
        )
        assert result == {
            "phone": "138****8000",
            "count": 3,
            "nested": {"email": "a***@example.com"},
        }

    def test_mask_map_preserves_insertion_order(self) -> None:
        service = DefaultMaskingService(DesensitizeProperties(sensitive_keys={"b": MaskType.NAME}))
        result = service.mask_map({"a": 1, "b": "张三丰", "c": None})
        assert list(result) == ["a", "b", "c"]
        assert result["b"] == "张**"
        assert result["c"] is None

    def test_mask_map_none(self) -> None:
        assert DefaultMaskingService().mask_map(None) is None

    def test_custom_mask_char_from_properties(self) -> None:
        service = DefaultMaskingService(DesensitizeProperties(default_mask_char="#"))
        assert service.mask("13812348000", MaskType.PHONE) == "138####8000"
