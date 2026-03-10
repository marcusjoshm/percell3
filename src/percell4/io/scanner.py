"""File discovery for PerCell 4 image import.

Scans directories for supported image files (TIFF, LIF, CZI) and returns
structured FileInfo records. Pure file-system operations — no database or
Zarr dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class FileInfo:
    """Metadata about a discovered image file.

    Attributes:
        path: Absolute path to the file.
        format: File format identifier ('tiff', 'lif', 'czi').
        name: Stem of the filename (no extension).
        channel_count: Number of channels if known, else None.
    """

    path: Path
    format: str  # 'tiff', 'lif', 'czi'
    name: str  # stem of filename
    channel_count: int | None = None


# Mapping from extension to format identifier
_EXTENSION_FORMAT: dict[str, str] = {
    ".tif": "tiff",
    ".tiff": "tiff",
    ".lif": "lif",
    ".czi": "czi",
}


def scan_directory(
    directory: Path,
    extensions: tuple[str, ...] = (".tif", ".tiff", ".lif", ".czi"),
) -> list[FileInfo]:
    """Discover image files in a directory.

    Walks the directory tree (non-recursive, top level only) for files
    matching the requested extensions. Returns a sorted list of FileInfo.

    Symlinks are skipped to prevent directory escape and circular loops.

    Args:
        directory: Directory to scan.
        extensions: Tuple of file extensions to match (case-insensitive).

    Returns:
        List of FileInfo, sorted by name.

    Raises:
        FileNotFoundError: If *directory* does not exist.
        ValueError: If *directory* is not a directory.
    """
    directory = Path(directory)

    if not directory.exists():
        raise FileNotFoundError(f"Directory does not exist: {directory}")
    if not directory.is_dir():
        raise ValueError(f"Path is not a directory: {directory}")

    ext_set = {e.lower() for e in extensions}
    results: list[FileInfo] = []

    for child in sorted(directory.iterdir()):
        if child.is_symlink():
            continue
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix not in ext_set:
            continue

        fmt = _EXTENSION_FORMAT.get(suffix, suffix.lstrip("."))
        results.append(
            FileInfo(
                path=child.resolve(),
                format=fmt,
                name=child.stem,
            )
        )

    return results
