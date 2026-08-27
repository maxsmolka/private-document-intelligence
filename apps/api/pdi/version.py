"""Application version sourced from installed package metadata."""

import os
from importlib.metadata import PackageNotFoundError, version

PDI_VERSION = os.getenv("PDI_BUILD_VERSION", "")
if not PDI_VERSION:
    try:
        PDI_VERSION = version("pdi-api")
    except PackageNotFoundError:  # pragma: no cover - only for unpackaged source use
        PDI_VERSION = "0+unknown"
