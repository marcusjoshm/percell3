"""Data models for the IO module."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_MAX_PATTERN_LENGTH = 200


@dataclass(frozen=True)
class TokenConfig:
    """Configurable token patterns for filename parsing.

    Each pattern should contain exactly one capture group that extracts
    the token value from the filename.
    """

    channel: str = r"_ch(\d+)"
    timepoint: str = r"_t(\d+)"
    z_slice: str = r"_z(\d+)"
    fov: str | None = None

    def __post_init__(self) -> None:
        """Validate regex patterns are compilable and not excessively long."""
        for field_name in ("channel", "timepoint", "z_slice", "fov"):
            pattern = getattr(self, field_name)
            if pattern is None:
                continue
            if len(pattern) > _MAX_PATTERN_LENGTH:
                raise ValueError(
                    f"Token pattern '{field_name}' exceeds max length "
                    f"{_MAX_PATTERN_LENGTH}"
                )
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex for '{field_name}': {e}"
                ) from e


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
    fovs: list[str]
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


_VALID_Z_METHODS = frozenset({"mip", "sum", "mean", "keep", "slice"})


@dataclass(frozen=True)
class ZTransform:
    """How to handle Z-stacks."""

    method: str  # "mip", "sum", "mean", "keep", "slice"
    slice_index: int | None = None

    def __post_init__(self) -> None:
        """Validate method and slice_index at construction time."""
        if self.method not in _VALID_Z_METHODS:
            raise ValueError(
                f"Invalid Z-transform method: {self.method!r}. "
                f"Must be one of {sorted(_VALID_Z_METHODS)}"
            )
        if self.method == "slice" and self.slice_index is None:
            raise ValueError("slice_index is required when method is 'slice'")


@dataclass
class ImportPlan:
    """Complete specification for an import."""

    source_path: Path
    condition: str
    channel_mappings: list[ChannelMapping]
    fov_names: dict[str, str]
    z_transform: ZTransform
    pixel_size_um: float | None
    token_config: TokenConfig
    condition_map: dict[str, str] = field(default_factory=dict)
    source_files: list[Path] | None = None  # Transient — not serialized to YAML

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

    fovs_imported: int
    channels_registered: int
    images_written: int
    skipped: int
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
