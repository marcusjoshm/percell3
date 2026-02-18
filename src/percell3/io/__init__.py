"""PerCell 3 IO — Format readers for LIF, TIFF, CZI."""

from __future__ import annotations

from pathlib import Path

from percell3.io.engine import ImportEngine
from percell3.io.models import (
    ChannelMapping,
    DiscoveredFile,
    ImportPlan,
    ImportResult,
    ScanResult,
    TokenConfig,
    ZTransform,
)
from percell3.io.scanner import FileScanner

__all__ = [
    "ChannelMapping",
    "DiscoveredFile",
    "FileScanner",
    "ImportEngine",
    "ImportPlan",
    "ImportResult",
    "ScanResult",
    "TokenConfig",
    "ZTransform",
    "scan",
]


def scan(
    path: Path,
    token_config: TokenConfig | None = None,
    files: list[Path] | None = None,
) -> ScanResult:
    """Scan a directory for TIFF files. Convenience wrapper.

    Args:
        path: Directory to scan.
        token_config: Token patterns for filename parsing.
            Uses defaults if not provided.
        files: Optional explicit file list (skips directory walking).

    Returns:
        ScanResult with discovered files and extracted dimensions.
    """
    return FileScanner().scan(path, token_config or TokenConfig(), files=files)
