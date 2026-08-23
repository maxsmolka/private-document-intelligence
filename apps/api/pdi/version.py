"""Application version sourced from installed package metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    PDI_VERSION = version("pdi-api")
except PackageNotFoundError:  # pragma: no cover - only for unpackaged source use
    PDI_VERSION = "0+unknown"
