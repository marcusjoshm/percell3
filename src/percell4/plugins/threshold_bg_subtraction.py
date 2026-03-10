"""Threshold-Layer Background Subtraction Plugin.

Separates "histogram source" FOVs (dilute-phase controls) from "apply" FOVs
(full images). Background is estimated from the histogram FOV's masked pixels,
then subtracted from the apply FOV's channel image. Derived FOVs are full
copies of the apply FOV with only the selected channel replaced.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


class ThresholdBGSubtractionPlugin(AnalysisPlugin):
    """Per-threshold-layer background subtraction using histogram peak detection.

    For each (histogram FOV, apply FOV) pairing:
    1. Extracts masked pixel intensities from the histogram FOV's channel.
    2. Estimates background via Gaussian-smoothed histogram peak detection.
    3. Subtracts background from the apply FOV's channel image (clipped at zero).
    4. Creates a derived FOV with ALL channels from the apply FOV.
    5. Copies assignments from the apply FOV (via create_derived_fov).
    6. Saves a diagnostic histogram PNG.
    """

    name = "threshold_bg_subtraction"
    description = "Per-threshold-layer histogram-based background subtraction"

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        from percell4.core.db_types import uuid_to_hex
        from percell4.plugins.peak_detection import find_gaussian_peaks, render_peak_histogram

        channel: str = kwargs.get("channel", "")
        pairings: list[dict[str, bytes]] = kwargs.get("pairings", [])

        if not channel:
            raise RuntimeError("'channel' parameter is required.")
        if not pairings:
            raise RuntimeError("'pairings' parameter is required.")

        # Resolve channel index
        exp = store.db.get_experiment()
        all_channels = store.db.get_channels(exp["id"])
        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }
        if channel not in channel_index_by_name:
            raise RuntimeError(f"Channel '{channel}' not found in experiment.")

        target_ch_idx = channel_index_by_name[channel]

        # Prepare histogram export directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        histograms_dir = store.root / "exports" / "bgsub_histograms"
        histograms_dir.mkdir(parents=True, exist_ok=True)

        derived_count = 0
        errors: list[str] = []

        for pair_idx, pairing in enumerate(pairings):
            hist_fov_id: bytes = pairing["histogram_fov_id"]
            apply_fov_id: bytes = pairing["apply_fov_id"]

            hist_fov = store.db.get_fov(hist_fov_id)
            apply_fov = store.db.get_fov(apply_fov_id)

            if hist_fov is None or apply_fov is None:
                errors.append(f"Pairing {pair_idx}: FOV not found")
                continue

            # Read histogram FOV channel image
            hist_hex = uuid_to_hex(hist_fov_id)
            try:
                hist_image = store.layers.read_image_channel_numpy(
                    hist_hex, target_ch_idx
                )
            except Exception as exc:
                errors.append(
                    f"Skipped histogram FOV {hist_fov['auto_name']}: {exc}"
                )
                continue

            # Get mask assignments from histogram FOV
            active = store.db.get_active_assignments(hist_fov_id)
            mask_assigns = active.get("mask", [])

            if not mask_assigns:
                errors.append(
                    f"Histogram FOV {hist_fov['auto_name']}: "
                    f"no mask assignments, skipping."
                )
                continue

            for mask_assign in mask_assigns:
                mask_id = mask_assign["threshold_mask_id"]
                mask_hex = uuid_to_hex(mask_id)

                # Read mask
                try:
                    mask_raw = store.layers.read_mask(mask_hex)
                except Exception as exc:
                    errors.append(
                        f"Histogram FOV {hist_fov['auto_name']}, "
                        f"mask: failed to read: {exc}"
                    )
                    continue

                if mask_raw.shape != hist_image.shape:
                    errors.append(
                        f"Histogram FOV {hist_fov['auto_name']}: "
                        f"mask shape {mask_raw.shape} != "
                        f"image shape {hist_image.shape}, skipping."
                    )
                    continue

                mask_bool = mask_raw > 0
                masked_pixels = hist_image[mask_bool]

                if len(masked_pixels) == 0:
                    errors.append(
                        f"Histogram FOV {hist_fov['auto_name']}: "
                        f"mask has no non-zero pixels, skipping."
                    )
                    continue

                # Estimate background
                peak_result = find_gaussian_peaks(masked_pixels)
                if peak_result is None:
                    errors.append(
                        f"Histogram FOV {hist_fov['auto_name']}: "
                        f"no valid intensity data for peak detection, skipping."
                    )
                    continue

                bg_value = peak_result.background_value

                # Build transform function that subtracts bg from target channel
                def transform_fn(
                    arrays: dict[int, np.ndarray],
                    _bg: float = bg_value,
                    _target: int = target_ch_idx,
                ) -> dict[int, np.ndarray]:
                    result = dict(arrays)
                    if _target in result:
                        img = result[_target]
                        derived = np.clip(
                            img.astype(np.int32) - int(_bg),
                            0,
                            int(np.iinfo(img.dtype).max)
                            if np.issubdtype(img.dtype, np.integer)
                            else None,
                        ).astype(img.dtype)
                        result[_target] = derived
                    return result

                try:
                    store.create_derived_fov(
                        source_fov_id=apply_fov_id,
                        derivation_op=f"bgsub_{channel}",
                        params={
                            "channel": channel,
                            "bg_value": bg_value,
                        },
                        transform_fn=transform_fn,
                    )
                    derived_count += 1
                except Exception as exc:
                    errors.append(f"Failed to create derived FOV: {exc}")

                # Save histogram PNG
                hist_title = (
                    f"{hist_fov['auto_name']} / {channel}"
                )
                safe_name = (
                    f"{hist_fov['auto_name']}_{channel}_{timestamp}.png"
                )
                hist_path = histograms_dir / safe_name
                try:
                    render_peak_histogram(peak_result, hist_title, hist_path)
                except Exception as exc:
                    logger.warning("Failed to save histogram PNG: %s", exc)

            if on_progress:
                on_progress(
                    pair_idx + 1, len(pairings),
                    hist_fov["auto_name"] or "unknown",
                )

        return PluginResult(
            fovs_processed=len(pairings),
            derived_fovs_created=derived_count,
            errors=errors,
        )
