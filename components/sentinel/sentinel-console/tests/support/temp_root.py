"""Resolve the temp root used by the console test suite.

`/private/tmp` keeps the macOS behaviour identical and stays inside Docker
Desktop's default file-sharing paths, which the container-backed acceptance
flows rely on. It does not exist on Linux, so fall back to the platform temp
directory there instead of failing every temp-dir test with FileNotFoundError.
"""

from __future__ import annotations

import os
import tempfile

TEMP_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else tempfile.gettempdir()
