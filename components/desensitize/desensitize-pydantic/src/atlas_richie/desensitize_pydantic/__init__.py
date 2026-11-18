"""Pydantic v2 模型的 API 响应脱敏（对位 Java `desensitize-jackson`）。

此前 core 的 `_write_bean` 对 pydantic 模型会落到 `__slots__`（内部属性）或
无标记的 `__dict__`：字段级标记完全不可见，API 响应明文。本包补上执行器。

对位关系：Java 用 Jackson serializer 绑定 `@Sensitive` 注解；pydantic v2 的
等价物是 `Annotated[str, Sensitive(MaskType.PHONE)]`——标记进入
`model_fields[name].metadata`，由本包读取。

掩蔽次序与 Java 一致：先按字段名跑规则（`mask_map`，如 password/id_card），
显式标记的结果**覆盖**之——标记是作者声明，优先于名字猜测。嵌套模型逐层
解析，`transient` 字段（`Annotated[..., Transient()]`）不输出。

本包只依赖 pydantic，不绑 Web 框架；FastAPI 等调用方自行接线（见 README）。
"""

from __future__ import annotations

from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel

from atlas_richie.desensitize_core import (
    DefaultMaskingService,
    MaskContext,
    MaskScene,
    MaskType,
    MaskingService,
    Sensitive,
)

__all__ = ["PydanticMaskingSerializer", "Transient", "sensitive"]


class Transient:
    """Field marker: excluded from masked output entirely (Java `transient`).

    Use as `Annotated[str, Transient()]` — presence alone is the signal.
    """


def sensitive(
    mask_type: MaskType,
    scenes: tuple[MaskScene, ...] = (MaskScene.API_RESPONSE, MaskScene.LOG),
) -> Sensitive:
    """Convenience for `Annotated[str, sensitive(MaskType.PHONE)]`."""
    return Sensitive(mask_type, tuple(scenes))


_LIST_ORIGINS = (list, set, frozenset)


def _unwrap_annotation(annotation: Any) -> Any:
    """Peel Annotated / Optional / list[X] down to the element annotation."""
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            annotation = get_args(annotation)[0]
            continue
        if origin is Union:  # Optional[X] is Union[X, None]
            non_none = [a for a in get_args(annotation) if a is not type(None)]
            if len(non_none) == 1:
                annotation = non_none[0]
                continue
        if origin in _LIST_ORIGINS:
            args = get_args(annotation)
            if len(args) == 1:
                annotation = args[0]
                continue
        return annotation


def _is_model(annotation: Any) -> bool:
    unwrapped = _unwrap_annotation(annotation)
    return isinstance(unwrapped, type) and issubclass(unwrapped, BaseModel)


def _model_class(annotation: Any) -> type[BaseModel] | None:
    unwrapped = _unwrap_annotation(annotation)
    if isinstance(unwrapped, type) and issubclass(unwrapped, BaseModel):
        return unwrapped
    return None


class PydanticMaskingSerializer:
    """Masks pydantic v2 models for a scene (default API_RESPONSE)."""

    def __init__(self, masking_service: MaskingService | None = None) -> None:
        self._masking = masking_service if masking_service is not None else DefaultMaskingService()

    def to_safe_json(self, model: BaseModel, scene: MaskScene = MaskScene.API_RESPONSE) -> str:
        import json

        return json.dumps(
            self.to_safe_dict(model, scene), ensure_ascii=False, separators=(",", ":")
        )

    def to_safe_dict(self, model: BaseModel, scene: MaskScene = MaskScene.API_RESPONSE) -> dict:
        if not isinstance(model, BaseModel):
            raise TypeError(f"expected a pydantic BaseModel, got {type(model).__name__}")
        transient = _transient_fields(type(model))
        dumped = model.model_dump(mode="json", exclude=transient or None)
        # 1) name-based rules（password / id_card 等按名字命中）
        masked = self._masking.mask_map(dumped, scene) or {}
        # 2) 显式标记覆盖名字规则，嵌套模型递归
        return self._apply_markers(type(model), dumped, masked, scene)

    def _apply_markers(
        self,
        model_cls: type[BaseModel],
        raw: dict,
        partially_masked: dict,
        scene: MaskScene,
    ) -> dict:
        out: dict[str, Any] = {}
        for name, value in partially_masked.items():
            info = model_cls.model_fields.get(name)
            marker = _marker_of(info)
            nested_cls = _model_class(info.annotation) if info is not None else None
            if (
                marker is not None
                and marker.applies_to(scene)
                and isinstance(raw.get(name), str)
            ):
                context = MaskContext.of(scene, name, model_cls)
                out[name] = self._masking.mask(
                    raw[name], marker.type, scene, context
                )
            elif isinstance(value, dict) and nested_cls is not None:
                out[name] = self._apply_markers(
                    nested_cls, raw.get(name) or {}, _drop_transient(value, nested_cls), scene
                )
            elif isinstance(value, list) and nested_cls is not None:
                raw_items = raw.get(name) or []
                out[name] = [
                    self._apply_markers(nested_cls, item_raw, _drop_transient(item, nested_cls), scene)
                    for item_raw, item in zip(raw_items, value)
                    if isinstance(item, dict)
                ] or value
            else:
                out[name] = value
        return out


def _marker_of(info: Any) -> Sensitive | None:
    if info is None:
        return None
    for item in info.metadata or ():
        if isinstance(item, Sensitive):
            return item
    return None


def _drop_transient(value: dict, model_cls: type[BaseModel]) -> dict:
    transient = _transient_fields(model_cls)
    if not transient:
        return value
    return {k: v for k, v in value.items() if k not in transient}


def _transient_fields(model_cls: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for name, info in model_cls.model_fields.items():
        if any(isinstance(item, Transient) for item in info.metadata or ()):
            names.add(name)
    return names
