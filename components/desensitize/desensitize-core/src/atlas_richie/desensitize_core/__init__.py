"""Framework-neutral data masking: strategies, rules, scenes, permissions.

Zero runtime dependencies. Serialization and logging adapters are deliberately
separate concerns; this package only decides what a masked value looks like.
"""

import importlib.metadata

from .model import (
    MaskContext,
    MaskRule,
    MaskScene,
    MaskType,
    default_keep_left,
    default_keep_right,
    default_mask_length,
)
from .permission import DefaultMaskPermissionEvaluator, MaskPermissionEvaluator
from .properties import DesensitizeProperties, Permission, SceneOverride, TypeRule
from .registry import MaskRuleRegistry, SensitiveKeyRegistry
from .serializer import (
    MAX_DEPTH,
    DefaultObjectMaskingService,
    ObjectMaskingService,
    SafeLogSerializer,
    SensitiveLogArg,
)
from .service import DefaultMaskingService, MaskingService
from .support import Sensitive, sensitive_field, transient_field
from .strategies import (
    AddressMaskingStrategy,
    ApiKeyMaskingStrategy,
    BankCardMaskingStrategy,
    EmailMaskingStrategy,
    IdCardMaskingStrategy,
    MaskingStrategy,
    MaskingStrategyRegistry,
    NameMaskingStrategy,
    PasswordMaskingStrategy,
    PhoneMaskingStrategy,
    default_strategies,
)

__version__ = importlib.metadata.version("atlas-richie-desensitize-core")

__all__ = [
    "MAX_DEPTH",
    "AddressMaskingStrategy",
    "ApiKeyMaskingStrategy",
    "BankCardMaskingStrategy",
    "DefaultMaskPermissionEvaluator",
    "DefaultMaskingService",
    "DefaultObjectMaskingService",
    "DesensitizeProperties",
    "EmailMaskingStrategy",
    "IdCardMaskingStrategy",
    "MaskContext",
    "MaskPermissionEvaluator",
    "MaskRule",
    "MaskRuleRegistry",
    "MaskScene",
    "MaskType",
    "MaskingService",
    "MaskingStrategy",
    "MaskingStrategyRegistry",
    "NameMaskingStrategy",
    "ObjectMaskingService",
    "PasswordMaskingStrategy",
    "Permission",
    "PhoneMaskingStrategy",
    "SafeLogSerializer",
    "SceneOverride",
    "Sensitive",
    "SensitiveKeyRegistry",
    "SensitiveLogArg",
    "TypeRule",
    "__version__",
    "default_keep_left",
    "default_keep_right",
    "default_mask_length",
    "default_strategies",
    "sensitive_field",
    "transient_field",
]
