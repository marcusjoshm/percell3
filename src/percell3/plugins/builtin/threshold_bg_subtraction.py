"""Threshold-Layer Background Subtraction Plugin.

For each FOV and configured threshold layer, estimates the background intensity
from a histogram of masked pixels and subtracts it, producing a derived FOV
with the background-subtracted image.
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

    For each selected FOV and each of its configured threshold layers:
    1. Extracts masked pixel intensities from the selected channel.
    2. Estimates background via Gaussian-smoothed histogram peak detection.
    3. Subtracts background (clipped at zero) from masked pixels.
    4. Creates a derived FOV with the subtracted image.
    5. Saves a diagnostic histogram PNG.
    """

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="threshold_bg_subtraction",
            version="1.0.0",
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
                "fov_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "FOV IDs to process",
                },
            },
            "required": ["channel", "fov_ids"],
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
        fov_ids: list[int] = parameters["fov_ids"]

        # Build lookup for idempotent re-runs
        fov_name_to_id: dict[str, int] = {
            f.display_name: f.id for f in store.get_fovs()
        }

        # Build threshold lookup
        all_thresholds = store.get_thresholds()
        threshold_map: dict[int, ThresholdInfo] = {t.id: t for t in all_thresholds}

        # Prepare histogram export directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        histograms_dir = Path(store.path) / "exports" / "bgsub_histograms"
        histograms_dir.mkdir(parents=True, exist_ok=True)

        results_summary: list[dict[str, Any]] = []
        warnings: list[str] = []
        fovs_created = 0

        for fov_idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            # Load channel image once per FOV
            try:
                channel_image = store.read_image_numpy(fov_id, channel)
            except Exception as exc:
                warnings.append(f"Skipped FOV {fov_info.display_name}: {exc}")
                continue

            # Get configured thresholds for this FOV
            fov_config = store.get_fov_config(fov_id)
            threshold_ids = [
                entry.threshold_id
                for entry in fov_config
                if entry.threshold_id is not None
            ]
            # Deduplicate while preserving order
            seen: set[int] = set()
            unique_threshold_ids: list[int] = []
            for tid in threshold_ids:
                if tid not in seen:
                    seen.add(tid)
                    unique_threshold_ids.append(tid)

            if not unique_threshold_ids:
                warnings.append(
                    f"FOV {fov_info.display_name}: no threshold layers configured, skipping."
                )
                continue

            for threshold_id in unique_threshold_ids:
                thr_info = threshold_map.get(threshold_id)
                if thr_info is None:
                    continue

                result = self._process_threshold(
                    store=store,
                    fov_info=fov_info,
                    channel=channel,
                    channel_image=channel_image,
                    thr_info=thr_info,
                    fov_name_to_id=fov_name_to_id,
                    histograms_dir=histograms_dir,
                    timestamp=timestamp,
                    warnings=warnings,
                )
                if result is not None:
                    results_summary.append(result)
                    fovs_created += 1

            if progress_callback:
                progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)

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
            # Store summary for CLI to display
        )

    def _process_threshold(
        self,
        store: ExperimentStore,
        fov_info: FovInfo,
        channel: str,
        channel_image: np.ndarray,
        thr_info: ThresholdInfo,
        fov_name_to_id: dict[str, int],
        histograms_dir: Path,
        timestamp: str,
        warnings: list[str],
    ) -> dict[str, Any] | None:
        """Process a single FOV x threshold combination.

        Returns a summary dict or None if skipped.
        """
        from percell3.plugins.builtin.peak_detection import (
            find_gaussian_peaks,
            render_peak_histogram,
        )

        # Load mask
        try:
            mask_raw = store.read_mask(thr_info.id)
        except Exception as exc:
            warnings.append(
                f"FOV {fov_info.display_name}, threshold {thr_info.name}: "
                f"failed to read mask: {exc}"
            )
            return None

        mask_bool = mask_raw > 0

        # Extract masked pixel intensities
        masked_pixels = channel_image[mask_bool]
        if len(masked_pixels) == 0:
            warnings.append(
                f"FOV {fov_info.display_name}, threshold {thr_info.name}: "
                f"mask has no non-zero pixels, skipping."
            )
            return None

        # Estimate background
        peak_result = find_gaussian_peaks(masked_pixels)
        if peak_result is None:
            warnings.append(
                f"FOV {fov_info.display_name}, threshold {thr_info.name}: "
                f"no valid intensity data for peak detection, skipping."
            )
            return None

        bg_value = peak_result.background_value

        # Build derived image with safe unsigned subtraction
        subtracted = np.clip(
            channel_image.astype(np.int32) - int(bg_value),
            0,
            int(np.iinfo(channel_image.dtype).max) if np.issubdtype(channel_image.dtype, np.integer) else None,
        )
        derived_image = np.where(
            mask_bool,
            subtracted,
            channel_image.dtype.type(0),
        ).astype(channel_image.dtype)

        # Derive FOV name
        derived_name = f"{fov_info.display_name}_bgsub_{thr_info.name}_{channel}"

        # Create or reuse derived FOV
        if derived_name in fov_name_to_id:
            derived_fov_id = fov_name_to_id[derived_name]
        else:
            derived_fov_id = store.add_fov(
                condition=fov_info.condition,
                bio_rep=fov_info.bio_rep,
                display_name=derived_name,
                width=fov_info.width,
                height=fov_info.height,
                pixel_size_um=fov_info.pixel_size_um,
            )
            fov_name_to_id[derived_name] = derived_fov_id

        # Write derived image
        store.write_image(derived_fov_id, channel, derived_image)

        # Save histogram PNG
        hist_title = f"{fov_info.display_name} / {thr_info.name} / {channel}"
        safe_name = (
            f"{fov_info.display_name}_{thr_info.name}_{channel}_{timestamp}.png"
        )
        hist_path = histograms_dir / safe_name
        try:
            render_peak_histogram(peak_result, hist_title, hist_path)
        except Exception as exc:
            logger.warning("Failed to save histogram PNG: %s", exc)

        return {
            "source_fov": fov_info.display_name,
            "threshold": thr_info.name,
            "channel": channel,
            "bg_value": bg_value,
            "derived_name": derived_name,
        }
