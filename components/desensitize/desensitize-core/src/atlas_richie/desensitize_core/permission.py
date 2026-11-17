"""Plaintext-permission evaluation.

Ported from `cn.richie696.component.desensitize.core.permission` (Java). The
evaluator is a `Protocol` so callers can plug their own RBAC without this package
depending on any identity or web framework.
"""

from __future__ import annotations

from typing import Protocol

from .model import MaskContext
from .properties import DesensitizeProperties


class MaskPermissionEvaluator(Protocol):
    def should_mask(self, context: MaskContext) -> bool:
        """True means mask; False means the caller may see plaintext."""
        ...


class DefaultMaskPermissionEvaluator:
    """Masks unless permission control is on AND a plaintext role is present."""

    def __init__(self, properties: DesensitizeProperties) -> None:
        self._properties = properties

    def should_mask(self, context: MaskContext) -> bool:
        permission = self._properties.permission
        if not permission.enabled:
            return True
        plain_roles = permission.plain_text_roles
        if not plain_roles:
            return True
        if not context.roles:
            return True
        return not any(role in plain_roles for role in context.roles)


__all__ = ["DefaultMaskPermissionEvaluator", "MaskPermissionEvaluator"]
