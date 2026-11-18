"""嵌入模型 SPI 与模态路由（对位 Java `ModalityAwareEmbeddingService`）。

模型本体由调用方注入（OpenAI/本地模型/任何 SDK），core 只定义契约与路由，
因此保持零第三方依赖——与 statemachine 的 callable 注入同一原则。

文本是基线能力（text_model 必填）；图片可选，未配置时显式抛
`UnsupportedModalityError` 而不是静默退回文本模型——那会把图片当字符串
嵌入，产出看似成功实则无意义的向量。

图片按 Java 语义嵌入其 data URL（`data:{mime};base64,{...}`），供 CLIP 类
模型消费。
"""

from __future__ import annotations

import base64
from typing import Protocol, runtime_checkable

from .engine import VectorStoreError
from .model import ImageContent, Modality, TextContent, VectorContent


class UnsupportedModalityError(VectorStoreError):
    """The requested modality has no configured embedding model."""


@runtime_checkable
class EmbeddingModel(Protocol):
    """Caller-supplied embedding backend."""

    def embed(self, text: str) -> tuple[float, ...]: ...

    def dimensions(self) -> int: ...


class ModalityAwareEmbeddingService:
    def __init__(
        self,
        text_model: EmbeddingModel,
        image_model: EmbeddingModel | None = None,
    ) -> None:
        if text_model is None:
            raise ValueError("text_model is required — text embedding is the baseline")
        self._text_model = text_model
        self._image_model = image_model

    @property
    def text_model(self) -> EmbeddingModel:
        return self._text_model

    @property
    def image_model(self) -> EmbeddingModel | None:
        return self._image_model

    def set_text_model(self, model: EmbeddingModel) -> None:
        if model is None:
            raise ValueError("text_model is required — text embedding is the baseline")
        self._text_model = model

    def set_image_model(self, model: EmbeddingModel | None) -> None:
        self._image_model = model

    def supports_modality(self, modality: Modality | None) -> bool:
        if modality is None:
            return False
        if modality is Modality.TEXT:
            return True
        return self._image_model is not None

    def dimension_for(self, modality: Modality | None) -> int:
        if modality is None:
            return 0
        if modality is Modality.TEXT:
            return self._text_model.dimensions()
        return self._image_model.dimensions() if self._image_model is not None else 0

    def embed(self, modality: Modality, content: VectorContent) -> tuple[float, ...]:
        if content is None:
            raise ValueError("content must not be None")
        if modality is Modality.TEXT:
            if not isinstance(content, TextContent):
                raise ValueError(
                    f"TEXT modality requires TextContent, got {type(content).__name__}"
                )
            return tuple(self._text_model.embed(content.text))
        if modality is Modality.IMAGE:
            if self._image_model is None:
                raise UnsupportedModalityError(
                    "IMAGE modality is not configured — inject an image embedding model"
                )
            if not isinstance(content, ImageContent):
                raise ValueError(
                    f"IMAGE modality requires ImageContent, got {type(content).__name__}"
                )
            return tuple(self._image_model.embed(_data_url(content)))
        raise UnsupportedModalityError(f"unknown modality: {modality!r}")


def _data_url(image: ImageContent) -> str:
    encoded = base64.b64encode(image.data or b"").decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


__all__ = [
    "EmbeddingModel",
    "ModalityAwareEmbeddingService",
    "UnsupportedModalityError",
]