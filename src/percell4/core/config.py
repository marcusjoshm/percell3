"""TOML configuration loader for PerCell 4 experiments.

Parses experiment configuration from TOML files into validated Pydantic v2
models.  The ``ExperimentConfigV1`` model enforces structural constraints
including ROI type hierarchy validation and size limits.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from percell4.core.exceptions import ExperimentError

# ---------------------------------------------------------------------------
# Pydantic v2 configuration models
# ---------------------------------------------------------------------------


class ExperimentMeta(BaseModel):
    """Top-level ``[experiment]`` table in the TOML config."""

    name: str
    description: str = ""


class ChannelSpec(BaseModel):
    """Channel specification from TOML.

    Named ``ChannelSpec`` (not ``ChannelConfig``) to avoid collision with the
    domain dataclass ``ChannelInfo``.
    """

    name: str
    role: str | None = None
    color: str | None = None
    display_order: int = 0


class RoiTypeConfig(BaseModel):
    """ROI type definition with optional parent hierarchy."""

    name: str
    parent_type: str | None = None


class ExperimentConfigV1(BaseModel):
    """Top-level experiment configuration (schema version 1).

    Parsed from a TOML file via :meth:`from_toml`.  Validates channel count,
    ROI type hierarchy, and op_configs payload size.
    """

    experiment: ExperimentMeta
    channels: list[ChannelSpec] = Field(max_length=100)
    roi_types: list[RoiTypeConfig] = Field(
        default_factory=lambda: [RoiTypeConfig(name="cell")]
    )
    op_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @classmethod
    def from_toml(cls, path: Path) -> ExperimentConfigV1:
        """Parse experiment config from a TOML file.

        Args:
            path: Path to the TOML configuration file.

        Returns:
            A validated ``ExperimentConfigV1`` instance.

        Raises:
            ExperimentError: If the TOML contains a ``[[pipelines]]`` section,
                the ROI type hierarchy is invalid, there are too many ROI
                types, or the op_configs payload is too large.
            FileNotFoundError: If *path* does not exist.
        """
        with open(path, "rb") as f:
            data = tomllib.load(f)

        # ---- reject [[pipelines]] -----------------------------------------
        if "pipelines" in data:
            raise ExperimentError(
                "[[pipelines]] is not supported in v1. "
                "Pipeline orchestration is handled by the workflow engine."
            )

        # ---- parse into model (validates channel max_length, types) -------
        config = cls.model_validate(data)

        # ---- validate roi_types count -------------------------------------
        if len(config.roi_types) > 50:
            raise ExperimentError(
                f"Too many roi_types: {len(config.roi_types)} (max 50)"
            )

        # ---- validate roi_type hierarchy ----------------------------------
        _validate_roi_type_hierarchy(config.roi_types)

        # ---- validate op_configs total size < 100 KB ----------------------
        serialised = json.dumps(
            {k: v for k, v in config.op_configs.items()},
            default=str,
        )
        if len(serialised) > 100_000:
            raise ExperimentError(
                f"op_configs too large: {len(serialised)} bytes (max 100000)"
            )

        return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_roi_type_hierarchy(roi_types: list[RoiTypeConfig]) -> None:
    """Check that every ``parent_type`` references a valid name and detect cycles.

    Args:
        roi_types: The list of ROI type definitions to validate.

    Raises:
        ExperimentError: If a ``parent_type`` references a name not in the list,
            or if a circular reference is detected.
    """
    names = {rt.name for rt in roi_types}

    # Check all parent_type references are valid
    for rt in roi_types:
        if rt.parent_type is not None and rt.parent_type not in names:
            raise ExperimentError(
                f"roi_type '{rt.name}' references unknown parent_type "
                f"'{rt.parent_type}'"
            )

    # Build parent lookup and detect cycles
    parent_map: dict[str, str | None] = {
        rt.name: rt.parent_type for rt in roi_types
    }

    for name in names:
        visited: set[str] = set()
        current: str | None = name
        while current is not None:
            if current in visited:
                raise ExperimentError(
                    f"Circular parent_type reference detected involving "
                    f"roi_type '{current}'"
                )
            visited.add(current)
            current = parent_map.get(current)
