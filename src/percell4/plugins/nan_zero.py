"""NaN-Zero Plugin — replace zero-valued pixels with NaN in selected channels.

When measuring mean intensity in microscopy images, zero-valued pixels (from
background subtraction or masking) skew the mean downward.  Converting zeros
to NaN allows ``np.nanmean`` to exclude them.  Produces a derived FOV for
each input FOV with the selected channels converted to float32 and zeros
replaced by NaN.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


class NanZeroPlugin(AnalysisPlugin):
    """Replace zero-valued pixels with NaN in selected channels.

    For each source FOV a derived FOV is created using
    ``store.create_derived_fov()``.  Selected channels are cast to
    ``float32`` and every zero pixel is set to ``np.nan``.  Unselected
    channels are copied unchanged.

    The derived FOV four-step contract (create FOV, copy assignments,
    duplicate ROIs, set status) is handled by ``create_derived_fov()``.
    """

    name = "nan_zero"
    description = "Replace zero pixels with NaN in selected channels"

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        channels: list[str] | None = kwargs.get("channels")
        if not channels:
            raise RuntimeError("'channels' parameter is required for nan_zero.")

        # Resolve experiment channels
        exp = store.db.get_experiment()
        all_channels = store.db.get_channels(exp["id"])
        channel_names = {ch["name"] for ch in all_channels}
        for ch_name in channels:
            if ch_name not in channel_names:
                raise RuntimeError(
                    f"Channel '{ch_name}' not found in experiment."
                )

        # Build channel name -> index mapping
        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }

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
                    derivation_op="nan_zero",
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
