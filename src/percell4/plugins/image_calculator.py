"""Image Calculator Plugin — pixel-level arithmetic on channel images.

Mirrors ImageJ's ``Process > Math`` (single-channel with constant) and
``Process > Image Calculator`` (two-channel operations).  Operates on one
FOV at a time, always producing a non-destructive derived FOV.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult
from percell4.plugins.image_calculator_core import (
    OPERATIONS,
    apply_single_channel,
    apply_two_channel,
)

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

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

    name = "image_calculator"
    description = (
        "Pixel-level arithmetic: single-channel math with a constant "
        "or two-channel operations between selected channels"
    )

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        mode: str = kwargs.get("mode", "")
        operation: str = kwargs.get("operation", "")
        channel_a: str = kwargs.get("channel_a", "")
        channel_b: str | None = kwargs.get("channel_b")
        constant: float | None = kwargs.get("constant")

        # Validate
        if not mode:
            raise RuntimeError("'mode' parameter is required.")
        if not operation:
            raise RuntimeError("'operation' parameter is required.")
        if not channel_a:
            raise RuntimeError("'channel_a' parameter is required.")
        if operation not in OPERATIONS:
            raise RuntimeError(
                f"Unknown operation: {operation!r}. Must be one of {OPERATIONS}"
            )

        # zero_to_nan mode: special shorthand that replaces zeros with NaN
        if mode == "zero_to_nan":
            operation = "zero_to_nan"
            # channel_a may be a single channel or we process all listed channels
            channels_list: list[str] = kwargs.get("channels", [])
            if channels_list:
                exp = store.db.get_experiment()
                all_channels = store.db.get_channels(exp["id"])
                ch_idx_map = {
                    ch["name"]: idx for idx, ch in enumerate(all_channels)
                }
                return self._run_zero_to_nan(
                    store, fov_ids, channels_list, ch_idx_map,
                    on_progress,
                )
            # Fall through to single_channel path with zero_to_nan op
            constant = 0.0  # unused but satisfies validation

        if constant is not None and not np.isfinite(constant):
            if operation != "zero_to_nan":
                raise RuntimeError(f"'constant' must be a finite number, got {constant!r}")

        if mode == "single_channel" or mode == "zero_to_nan":
            if constant is None and operation != "zero_to_nan":
                raise RuntimeError("'constant' is required for single_channel mode.")
            if constant is None:
                constant = 0.0  # placeholder for zero_to_nan
        elif mode == "two_channel":
            if channel_b is None:
                raise RuntimeError("'channel_b' is required for two_channel mode.")
        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")

        # Resolve channel indices
        exp = store.db.get_experiment()
        all_channels = store.db.get_channels(exp["id"])
        channel_names = {ch["name"] for ch in all_channels}

        if channel_a not in channel_names:
            raise RuntimeError(f"Channel '{channel_a}' not found in experiment.")
        if mode == "two_channel" and channel_b not in channel_names:
            raise RuntimeError(f"Channel '{channel_b}' not found in experiment.")

        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }
        idx_a = channel_index_by_name[channel_a]
        idx_b = channel_index_by_name.get(channel_b, -1) if channel_b else -1

        derived_count = 0
        errors: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            if on_progress:
                fov = store.db.get_fov(fov_id)
                name = fov["auto_name"] if fov else "unknown"
                on_progress(fov_idx, len(fov_ids), name)

            def transform_fn(
                arrays: dict[int, np.ndarray],
                _mode: str = mode,
                _op: str = operation,
                _idx_a: int = idx_a,
                _idx_b: int = idx_b,
                _const: float | None = constant,
            ) -> dict[int, np.ndarray]:
                result = dict(arrays)
                if _idx_a not in result:
                    return result

                if _mode == "single_channel":
                    result[_idx_a] = apply_single_channel(
                        result[_idx_a], _op, _const  # type: ignore[arg-type]
                    )
                else:
                    if _idx_b not in result:
                        return result
                    result[_idx_a] = apply_two_channel(
                        result[_idx_a], result[_idx_b], _op
                    )
                    # Zero out channel_b (consumed)
                    result[_idx_b] = np.zeros_like(result[_idx_b])

                return result

            try:
                op_suffix = f"{operation}_{constant}" if mode == "single_channel" else f"{operation}_{channel_b}"
                store.create_derived_fov(
                    source_fov_id=fov_id,
                    derivation_op=f"calc_{op_suffix}",
                    params={
                        "mode": mode,
                        "operation": operation,
                        "channel_a": channel_a,
                        "channel_b": channel_b,
                        "constant": constant,
                    },
                    transform_fn=transform_fn,
                )
                derived_count += 1
            except Exception as exc:
                errors.append(f"FOV {fov_id!r}: {exc}")

        if on_progress:
            on_progress(len(fov_ids), len(fov_ids), "Done")

        return PluginResult(
            fovs_processed=len(fov_ids),
            derived_fovs_created=derived_count,
            errors=errors,
        )

    def _run_zero_to_nan(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        channels: list[str],
        channel_index_by_name: dict[str, int],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> PluginResult:
        """Replace zero pixels with NaN in selected channels (absorbed nan_zero).

        For each source FOV a derived FOV is created. Selected channels are cast
        to float32 and every zero pixel is set to NaN. Unselected channels are
        copied unchanged.
        """
        target_indices = {channel_index_by_name[name] for name in channels}

        derived_count = 0
        errors: list[str] = []

        for idx, fov_id in enumerate(fov_ids):
            if on_progress:
                fov = store.db.get_fov(fov_id)
                name = fov["auto_name"] if fov else "unknown"
                on_progress(idx, len(fov_ids), name)

            def transform_fn(
                arrays: dict[int, np.ndarray],
                _targets: set[int] = target_indices,
            ) -> dict[int, np.ndarray]:
                result: dict[int, np.ndarray] = {}
                for ch_idx, image in arrays.items():
                    image = image.astype(np.float32)
                    if ch_idx in _targets:
                        image[image == 0] = np.nan
                    result[ch_idx] = image
                return result

            try:
                store.create_derived_fov(
                    source_fov_id=fov_id,
                    derivation_op="zero_to_nan",
                    params={"channels": channels},
                    transform_fn=transform_fn,
                )
                derived_count += 1
            except Exception as exc:
                errors.append(f"FOV {fov_id!r}: {exc}")

        if on_progress:
            on_progress(len(fov_ids), len(fov_ids), "Done")

        return PluginResult(
            fovs_processed=len(fov_ids),
            derived_fovs_created=derived_count,
            errors=errors,
        )
