"""Logging-side desensitization: MDC context, interception and the masking SPI.

Ported from `cn.richie696.component.desensitize.logging` (Java; see the Java parent README §3.3 for the log desensitization design). The core
algorithms live in atlas-richie-desensitize-core; this package only adapts them
to the Python logging stack.

Zero runtime dependencies beyond the standard library and desensitize-core.
"""

import importlib.metadata

from .filters import SensitiveLogArgFilter, SensitiveMdcFilter
from .formatter import MdcFormatter, mdc_of
from .mdc import MdcContext
from .service import DefaultLoggingMaskingService, LoggingMaskingService

__version__ = importlib.metadata.version("atlas-richie-desensitize-logging")

__all__ = [
    "DefaultLoggingMaskingService",
    "LoggingMaskingService",
    "MdcContext",
    "MdcFormatter",
    "SensitiveLogArgFilter",
    "SensitiveMdcFilter",
    "__version__",
    "mdc_of",
]
