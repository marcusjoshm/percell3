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
from typing import TYPE_CHECKING, Any

import numpy as np

from percell3.plugins.base import (
    AnalysisPlugin,
    InputKind,
    PluginInfo,
    PluginInputRequirement,
    PluginResult,
)

if TYPE_CHECKING:
    from percell3.core import ExperimentStore
    from percell3.core.models import FovInfo, ThresholdInfo

logger = logging.getLogger(__name__)


class ThresholdBGSubtractionPlugin(AnalysisPlugin):
    """Per-threshold-layer background subtraction using histogram peak detection.

    For each (histogram FOV, apply FOV) pairing:
    1. Extracts masked pixel intensities from the histogram FOV's channel.
    2. Estimates background via Gaussian-smoothed histogram peak detection.
    3. Subtracts background from the apply FOV's channel image (clipped at zero).
    4. Creates a derived FOV with ALL channels from the apply FOV.
    5. Copies fov_config entries from the apply FOV.
    6. Saves a diagnostic histogram PNG.
    """

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="threshold_bg_subtraction",
            version="2.0.0",
            description="Per-threshold-layer histogram-based background subtraction",
            author="PerCell Team",
        )

    def required_inputs(self) -> list[PluginInputRequirement]:
        return [PluginInputRequirement(kind=InputKind.THRESHOLD)]

    def validate(self, store: ExperimentStore) -> list[str]:
        errors: list[str] = []
        if not store.get_channels():
            errors.append("No channels found in the experiment.")
        if not store.get_thresholds():
            errors.append(
                "No threshold layers found. "
                "Run 'Grouped intensity thresholding' first."
            )
        return errors

    def get_parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel to subtract background from",
                },
                "pairings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "histogram_fov_id": {"type": "integer"},
                            "apply_fov_id": {"type": "integer"},
                        },
                        "required": ["histogram_fov_id", "apply_fov_id"],
                    },
                    "description": "Histogram FOV → apply FOV pairings",
                },
            },
            "required": ["channel", "pairings"],
        }

    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        if parameters is None:
            raise RuntimeError("Parameters are required for threshold_bg_subtraction.")

        channel: str = parameters["channel"]
        pairings: list[dict[str, int]] = parameters["pairings"]

        # Build lookup for idempotent re-runs
        fov_name_to_id: dict[str, int] = {
            f.display_name: f.id for f in store.get_fovs()
        }

        # Build threshold lookup
        all_thresholds = store.get_thresholds()
        threshold_map: dict[int, ThresholdInfo] = {t.id: t for t in all_thresholds}

        # Channel list for full-copy derived FOVs
        channels = store.get_channels()

        # Prepare histogram export directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        histograms_dir = Path(store.path) / "exports" / "bgsub_histograms"
        histograms_dir.mkdir(parents=True, exist_ok=True)

        results_summary: list[dict[str, Any]] = []
        warnings: list[str] = []

        for pair_idx, pairing in enumerate(pairings):
            hist_fov_id = pairing["histogram_fov_id"]
            apply_fov_id = pairing["apply_fov_id"]

            hist_fov_info = store.get_fov_by_id(hist_fov_id)
            apply_fov_info = store.get_fov_by_id(apply_fov_id)

            # Load histogram FOV's channel image for background estimation
            try:
                hist_channel_image = store.read_image_numpy(hist_fov_id, channel)
            except Exception as exc:
                warnings.append(
                    f"Skipped histogram FOV {hist_fov_info.display_name}: {exc}"
                )
                continue

            # Get configured thresholds from the histogram FOV
            hist_config = store.get_fov_config(hist_fov_id)
            threshold_ids = [
                entry.threshold_id
                for entry in hist_config
                if entry.threshold_id is not None
            ]
            unique_threshold_ids = list(dict.fromkeys(threshold_ids))

            if not unique_threshold_ids:
                warnings.append(
                    f"Histogram FOV {hist_fov_info.display_name}: "
                    f"no threshold layers configured, skipping."
                )
                continue

            for threshold_id in unique_threshold_ids:
                thr_info = threshold_map.get(threshold_id)
                if thr_info is None:
                    continue

                result = self._process_threshold(
                    store=store,
                    hist_fov_info=hist_fov_info,
                    apply_fov_info=apply_fov_info,
                    apply_fov_id=apply_fov_id,
                    channel=channel,
                    hist_channel_image=hist_channel_image,
                    thr_info=thr_info,
                    channels=channels,
                    fov_name_to_id=fov_name_to_id,
                    histograms_dir=histograms_dir,
                    timestamp=timestamp,
                    warnings=warnings,
                )
                if result is not None:
                    results_summary.append(result)

            if progress_callback:
                progress_callback(
                    pair_idx + 1, len(pairings), hist_fov_info.display_name,
                )

        # Build custom_outputs with background values
        custom_outputs: dict[str, str] = {}
        for r in results_summary:
            custom_outputs[f"bg_{r['derived_name']}"] = f"{r['bg_value']:.2f}"
        if histograms_dir.exists() and any(histograms_dir.iterdir()):
            custom_outputs["histograms_dir"] = str(histograms_dir)

        return PluginResult(
            measurements_written=0,
            cells_processed=0,
            custom_outputs=custom_outputs,
            warnings=warnings,
        )

    def _process_threshold(
        self,
        store: ExperimentStore,
        hist_fov_info: FovInfo,
        apply_fov_info: FovInfo,
        apply_fov_id: int,
        channel: str,
        hist_channel_image: np.ndarray,
        thr_info: ThresholdInfo,
        channels: list,
        fov_name_to_id: dict[str, int],
        histograms_dir: Path,
        timestamp: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        """Process a single histogram FOV x apply FOV x threshold combination.

        Returns a summary dict or None if skipped.
        """
        from percell3.plugins.builtin.peak_detection import (
            find_gaussian_peaks,
            render_peak_histogram,
        )

        # Load mask from the threshold (lives on the histogram FOV)
        try:
            mask_raw = store.read_mask(thr_info.id)
        except Exception as exc:
            warnings.append(
                f"Histogram FOV {hist_fov_info.display_name}, "
                f"threshold {thr_info.name}: failed to read mask: {exc}"
            )
            return None

        if mask_raw.shape != hist_channel_image.shape:
            warnings.append(
                f"Histogram FOV {hist_fov_info.display_name}, "
                f"threshold {thr_info.name}: mask shape {mask_raw.shape} != "
                f"image shape {hist_channel_image.shape}, skipping."
            )
            return None

        mask_bool = mask_raw > 0

        # Extract masked pixel intensities from histogram FOV
        masked_pixels = hist_channel_image[mask_bool]
        if len(masked_pixels) == 0:
            warnings.append(
                f"Histogram FOV {hist_fov_info.display_name}, "
                f"threshold {thr_info.name}: "
                f"mask has no non-zero pixels, skipping."
            )
            return None

        # Estimate background from histogram FOV
        peak_result = find_gaussian_peaks(masked_pixels)
        if peak_result is None:
            warnings.append(
                f"Histogram FOV {hist_fov_info.display_name}, "
                f"threshold {thr_info.name}: "
                f"no valid intensity data for peak detection, skipping."
            )
            return None

        bg_value = peak_result.background_value

        # Load apply FOV's channel image for subtraction
        try:
            apply_channel_image = store.read_image_numpy(apply_fov_id, channel)
        except Exception as exc:
            warnings.append(
                f"Skipped apply FOV {apply_fov_info.display_name}: {exc}"
            )
            return None

        # Build derived image with safe unsigned subtraction (applied globally)
        derived_image = np.clip(
            apply_channel_image.astype(np.int32) - int(bg_value),
            0,
            int(np.iinfo(apply_channel_image.dtype).max)
            if np.issubdtype(apply_channel_image.dtype, np.integer)
            else None,
        ).astype(apply_channel_image.dtype)

        # Derive FOV name from the APPLY FOV
        derived_name = (
            f"{apply_fov_info.display_name}_bgsub_{thr_info.name}_{channel}"
        )

        # Create or reuse derived FOV (metadata from apply FOV)
        if derived_name in fov_name_to_id:
            derived_fov_id = fov_name_to_id[derived_name]
        else:
            derived_fov_id = store.add_fov(
                condition=apply_fov_info.condition,
                bio_rep=apply_fov_info.bio_rep,
                display_name=derived_name,
                width=apply_fov_info.width,
                height=apply_fov_info.height,
                pixel_size_um=apply_fov_info.pixel_size_um,
            )
            fov_name_to_id[derived_name] = derived_fov_id

        # Write ALL channels — subtracted channel replaced, others copied
        for ch in channels:
            if ch.name == channel:
                store.write_image(derived_fov_id, ch.name, derived_image)
            else:
                try:
                    ch_image = store.read_image_numpy(apply_fov_id, ch.name)
                    store.write_image(derived_fov_id, ch.name, ch_image)
                except Exception:
                    pass  # Channel may not exist on this FOV

        # Copy fov_config from apply FOV to derived FOV
        apply_config = store.get_fov_config(apply_fov_id)
        for entry in apply_config:
            try:
                store.set_fov_config_entry(
                    derived_fov_id,
                    entry.segmentation_id,
                    threshold_id=entry.threshold_id,
                    scopes=entry.scopes,
                )
            except Exception:
                pass  # Config may already exist from previous run

        # Save histogram PNG
        hist_title = (
            f"{hist_fov_info.display_name} / {thr_info.name} / {channel}"
        )
        safe_name = (
            f"{hist_fov_info.display_name}_{thr_info.name}"
            f"_{channel}_{timestamp}.png"
        )
        hist_path = histograms_dir / safe_name
        try:
            render_peak_histogram(peak_result, hist_title, hist_path)
        except Exception as exc:
            logger.warning("Failed to save histogram PNG: %s", exc)

        return {
            "histogram_fov": hist_fov_info.display_name,
            "apply_fov": apply_fov_info.display_name,
            "threshold": thr_info.name,
            "channel": channel,
            "bg_value": bg_value,
            "derived_name": derived_name,
        }
