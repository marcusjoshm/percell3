"""YAML serialization for ImportPlan.

Requires pyyaml. Raises ImportError with clear install instructions
if pyyaml is not available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from percell3.io.models import (
    ChannelMapping,
    ImportPlan,
    TokenConfig,
    ZTransform,
)


def _require_yaml() -> Any:
    """Import and return the yaml module, or raise a helpful error."""
    try:
        import yaml

        return yaml
    except ImportError:
        raise ImportError(
            "pyyaml is required for import plan serialization. "
            "Install it with: pip install pyyaml"
        ) from None


def plan_to_yaml(plan: ImportPlan, path: Path) -> None:
    """Serialize an ImportPlan to a YAML file.

    Args:
        plan: The import plan to serialize.
        path: File path to write.
    """
    yaml = _require_yaml()

    data: dict[str, Any] = {
        "source_path": str(plan.source_path),
        "condition": plan.condition,
        "pixel_size_um": plan.pixel_size_um,
        "z_transform": {
            "method": plan.z_transform.method,
        },
        "token_config": {
            "channel": plan.token_config.channel,
            "timepoint": plan.token_config.timepoint,
            "z_slice": plan.token_config.z_slice,
        },
        "channel_mappings": [],
        "fov_names": plan.fov_names,
    }

    if plan.condition_map:
        data["condition_map"] = plan.condition_map

    if plan.z_transform.slice_index is not None:
        data["z_transform"]["slice_index"] = plan.z_transform.slice_index

    if plan.token_config.fov is not None:
        data["token_config"]["fov"] = plan.token_config.fov

    for mapping in plan.channel_mappings:
        entry: dict[str, Any] = {
            "token_value": mapping.token_value,
            "name": mapping.name,
        }
        if mapping.role is not None:
            entry["role"] = mapping.role
        if mapping.color is not None:
            entry["color"] = mapping.color
        data["channel_mappings"].append(entry)

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def plan_from_yaml(path: Path) -> ImportPlan:
    """Deserialize an ImportPlan from a YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        An ImportPlan reconstructed from the YAML.

    Raises:
        FileNotFoundError: If the YAML file doesn't exist.
        ValueError: If the YAML is invalid or missing required fields.
    """
    yaml = _require_yaml()

    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid import plan YAML: expected a mapping, got {type(data).__name__}")

    required = ("source_path", "condition", "z_transform", "token_config")
    for key in required:
        if key not in data:
            raise ValueError(f"Invalid import plan YAML: missing required key '{key}'")

    # Parse z_transform
    zt_data = data["z_transform"]
    z_transform = ZTransform(
        method=zt_data["method"],
        slice_index=zt_data.get("slice_index"),
    )

    # Parse token_config
    tc_data = data["token_config"]
    token_config = TokenConfig(
        channel=tc_data.get("channel", r"_ch(\d+)"),
        timepoint=tc_data.get("timepoint", r"_t(\d+)"),
        z_slice=tc_data.get("z_slice", r"_z(\d+)"),
        fov=tc_data.get("fov"),
    )

    # Parse channel_mappings
    channel_mappings = []
    for cm_data in data.get("channel_mappings", []):
        channel_mappings.append(
            ChannelMapping(
                token_value=cm_data["token_value"],
                name=cm_data["name"],
                role=cm_data.get("role"),
                color=cm_data.get("color"),
            )
        )

    return ImportPlan(
        source_path=Path(data["source_path"]),
        condition=data["condition"],
        channel_mappings=channel_mappings,
        fov_names=data.get("fov_names", {}),
        z_transform=z_transform,
        pixel_size_um=data.get("pixel_size_um"),
        token_config=token_config,
        condition_map=data.get("condition_map", {}),
    )
