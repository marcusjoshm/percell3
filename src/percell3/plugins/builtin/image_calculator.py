"""Image Calculator Plugin — pixel-level arithmetic on channel images.

Mirrors ImageJ's ``Process > Math`` (single-channel with constant) and
``Process > Image Calculator`` (two-channel operations).  Operates on one
FOV at a time, always producing a non-destructive derived FOV.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult
from percell3.plugins.builtin.image_calculator_core import (
    OPERATIONS,
    apply_single_channel,
    apply_two_channel,
)

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class ImageCalculatorPlugin(AnalysisPlugin):
    """Pixel-level arithmetic on single channels or between two channels.

    Two modes:

    ``single_channel``
        Apply *operation* between every pixel in *channel_a* and a scalar
        *constant*.  The derived FOV keeps all channels; only *channel_a*
        is modified.

    ``two_channel``
        Apply *operation* pixel-wise between *channel_a* and *channel_b*.
        The computed result is written to the *channel_a* slot; the
        *channel_b* slot is zeroed.  All other channels are copied.
    """

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="image_calculator",
            version="1.0.0",
            description=(
                "Pixel-level arithmetic: single-channel math with a constant "
                "or two-channel operations between selected channels"
            ),
            author="PerCell Team",
        )

    def validate(self, store: ExperimentStore) -> list[str]:
        errors: list[str] = []
        if not store.get_channels():
            errors.append("No channels found in the experiment.")
        if not store.get_fovs():
            errors.append("No FOVs found in the experiment.")
        return errors

    def get_parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["single_channel", "two_channel"],
                    "description": "Whether to apply math with a constant or between two channels",
                },
                "operation": {
                    "type": "string",
                    "enum": list(OPERATIONS),
                    "description": "Arithmetic operation to apply",
                },
                "fov_id": {
                    "type": "integer",
                    "description": "FOV to process",
                },
                "channel_a": {
                    "type": "string",
                    "description": "Primary channel to operate on",
                },
                "channel_b": {
                    "type": ["string", "null"],
                    "description": "Second channel (required for two_channel mode)",
                    "default": None,
                },
                "constant": {
                    "type": ["number", "null"],
                    "description": "Constant value (required for single_channel mode)",
                    "default": None,
                },
            },
            "required": ["mode", "operation", "fov_id", "channel_a"],
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        if parameters is None:
            raise RuntimeError("Parameters are required for image_calculator.")

        mode: str = parameters["mode"]
        operation: str = parameters["operation"]
        fov_id: int = parameters["fov_id"]
        channel_a: str = parameters["channel_a"]
        channel_b: str | None = parameters.get("channel_b")
        constant: float | None = parameters.get("constant")

        # -- validate mode-specific params --------------------------------
        if constant is not None and not np.isfinite(constant):
            raise RuntimeError(f"'constant' must be a finite number, got {constant!r}")

        if mode == "single_channel":
            if constant is None:
                raise RuntimeError("'constant' is required for single_channel mode.")
        elif mode == "two_channel":
            if channel_b is None:
                raise RuntimeError("'channel_b' is required for two_channel mode.")
        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")

        if operation not in OPERATIONS:
            raise RuntimeError(
                f"Unknown operation: {operation!r}. Must be one of {OPERATIONS}"
            )

        # -- resolve FOV and channels -------------------------------------
        fov_info = store.get_fov_by_id(fov_id)
        channels = store.get_channels()
        channel_names = {ch.name for ch in channels}

        if channel_a not in channel_names:
            raise RuntimeError(f"Channel '{channel_a}' not found in experiment.")
        if mode == "two_channel" and channel_b not in channel_names:
            raise RuntimeError(f"Channel '{channel_b}' not found in experiment.")

        # -- read images --------------------------------------------------
        image_a = store.read_image_numpy(fov_id, channel_a)

        if progress_callback:
            progress_callback(0, 1, f"Computing {operation} on {fov_info.display_name}")

        # -- compute result -----------------------------------------------
        if mode == "single_channel":
            result = apply_single_channel(image_a, operation, constant)
            derived_name = (
                f"{fov_info.display_name}_{channel_a}_{operation}_{constant}"
            )
        else:
            image_b = store.read_image_numpy(fov_id, channel_b)
            result = apply_two_channel(image_a, image_b, operation)
            derived_name = (
                f"{fov_info.display_name}_{channel_a}_{operation}_{channel_b}"
            )

        # -- create or reuse derived FOV ----------------------------------
        existing_fov_map = {f.display_name: f.id for f in store.get_fovs()}

        if derived_name in existing_fov_map:
            derived_fov_id = existing_fov_map[derived_name]
        else:
            derived_fov_id = store.add_fov(
                condition=fov_info.condition,
                bio_rep=fov_info.bio_rep,
                display_name=derived_name,
                width=fov_info.width,
                height=fov_info.height,
                pixel_size_um=fov_info.pixel_size_um,
            )

        # -- write channels to derived FOV --------------------------------
        for ch in channels:
            if ch.name == channel_a:
                store.write_image(derived_fov_id, ch.name, result)
            elif mode == "two_channel" and ch.name == channel_b:
                # channel_b was consumed — write zeros
                zeros = np.zeros_like(image_a)
                store.write_image(derived_fov_id, ch.name, zeros)
            else:
                # copy unchanged
                ch_image = store.read_image_numpy(fov_id, ch.name)
                store.write_image(derived_fov_id, ch.name, ch_image)

        if progress_callback:
            progress_callback(1, 1, "Done")

        return PluginResult(
            measurements_written=0,
            cells_processed=0,
            custom_outputs={"derived_fov_id": str(derived_fov_id)},
        )
