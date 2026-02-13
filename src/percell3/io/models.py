"""Data models for the IO module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TokenConfig:
    """Configurable token patterns for filename parsing.

    Each pattern should contain exactly one capture group that extracts
    the token value from the filename.
    """

    channel: str = r"_ch(\d+)"
    timepoint: str = r"_t(\d+)"
    z_slice: str = r"_z(\d+)"
    region: str | None = None


@dataclass(frozen=True)
class DiscoveredFile:
    """A single file with its parsed tokens."""

    path: Path
    tokens: dict[str, str]
    shape: tuple[int, ...]
    dtype: str
    pixel_size_um: float | None


@dataclass(frozen=True)
class ScanResult:
    """What the scanner found — presented to user for review."""

    source_path: Path
    files: list[DiscoveredFile]
    channels: list[str]
    regions: list[str]
    timepoints: list[str]
    z_slices: list[str]
    pixel_size_um: float | None
    warnings: list[str]


@dataclass(frozen=True)
class ChannelMapping:
    """Map a discovered channel token to a named channel."""

    token_value: str
    name: str
    role: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class ZTransform:
    """How to handle Z-stacks."""

    method: str  # "mip", "sum", "mean", "keep", "slice"
    slice_index: int | None = None


@dataclass
class ImportPlan:
    """Complete specification for an import."""

    source_path: Path
    condition: str
    channel_mappings: list[ChannelMapping]
    region_names: dict[str, str]
    z_transform: ZTransform
    pixel_size_um: float | None
    token_config: TokenConfig

    def to_yaml(self, path: Path) -> None:
        """Serialize this plan to a YAML file."""
        from percell3.io.serialization import plan_to_yaml

        plan_to_yaml(self, path)

    @classmethod
    def from_yaml(cls, path: Path) -> ImportPlan:
        """Deserialize an ImportPlan from a YAML file."""
        from percell3.io.serialization import plan_from_yaml

        return plan_from_yaml(path)


@dataclass(frozen=True)
class ImportResult:
    """What happened during import."""

    regions_imported: int
    channels_registered: int
    images_written: int
    skipped: int
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
