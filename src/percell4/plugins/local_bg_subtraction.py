"""Local Background Subtraction Plugin — per-particle local BG estimation.

Uses Gaussian peak detection on a dilated ring around each particle to estimate
and subtract the local background from measurement channel intensities.

This is a measurement-only plugin — no derived FOVs are created.
Output is per-particle CSV files, one per condition.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

# CSV export column order
CSV_COLUMNS = [
    "particle_id",
    "roi_id",
    "fov_id",
    "fov_name",
    "condition",
    "bio_rep",
    "area_pixels",
    "raw_mean_intensity",
    "raw_integrated_intensity",
    "bg_estimate",
    "bg_ring_pixels",
    "bg_sub_mean_intensity",
    "bg_sub_integrated_intensity",
    "norm_mean_intensity",
]


class LocalBGSubtractionPlugin(AnalysisPlugin):
    """Per-particle local background subtraction using Gaussian peak detection.

    For each particle in a thresholded mask, dilates to form a background ring,
    estimates local background from the ring's intensity histogram, and subtracts
    it from the measurement channel intensities.
    """

    name = "local_bg_subtraction"
    description = "Per-particle local background subtraction with Gaussian peak detection"

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        from percell4.core.db_types import uuid_to_hex, uuid_to_str
        from percell4.plugins.bg_subtraction_core import process_particles_for_roi

        measurement_channel: str = kwargs.get("measurement_channel", "")
        particle_channel: str = kwargs.get("particle_channel", "")
        exclusion_channel: str | None = kwargs.get("exclusion_channel")
        normalization_channel: str | None = kwargs.get("normalization_channel")
        dilation_pixels: int = kwargs.get("dilation_pixels", 5)
        max_background: float | None = kwargs.get("max_background")
        do_export_csv: bool = kwargs.get("export_csv", True)

        if not measurement_channel:
            raise RuntimeError("'measurement_channel' parameter is required.")
        if not particle_channel:
            raise RuntimeError("'particle_channel' parameter is required.")

        # Resolve channel indices
        exp = store.get_experiment()
        exp_id = exp["id"]
        all_channels = store.get_channels(exp_id)
        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }

        if measurement_channel not in channel_index_by_name:
            raise RuntimeError(
                f"Measurement channel '{measurement_channel}' not found."
            )

        meas_ch_idx = channel_index_by_name[measurement_channel]
        norm_ch_idx = (
            channel_index_by_name.get(normalization_channel)
            if normalization_channel
            else None
        )

        # Collect per-particle rows grouped by condition
        rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        rois_processed = 0
        errors: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov = store.get_fov(fov_id)
            if fov is None:
                errors.append(f"FOV {uuid_to_str(fov_id)}: not found")
                continue

            fov_hex = uuid_to_hex(fov_id)
            fov_name = fov["auto_name"] or "unknown"

            if on_progress:
                on_progress(fov_idx, len(fov_ids), fov_name)

            # Read measurement image
            try:
                measurement_image = store.layers.read_image_channel_numpy(
                    fov_hex, meas_ch_idx
                )
            except Exception as exc:
                errors.append(f"FOV {fov_name}: failed to read measurement image: {exc}")
                continue

            # Read normalization image if needed
            norm_image = None
            if norm_ch_idx is not None:
                try:
                    norm_image = store.layers.read_image_channel_numpy(
                        fov_hex, norm_ch_idx
                    )
                except Exception as exc:
                    errors.append(
                        f"FOV {fov_name}: normalization channel unavailable: {exc}"
                    )

            # Get active segmentation assignments
            active = store.get_active_assignments(fov_id)
            seg_assigns = active.get("segmentation", [])
            mask_assigns = active.get("mask", [])

            if not seg_assigns:
                errors.append(f"FOV {fov_name}: no segmentation assignment")
                continue

            # Use first segmentation
            seg_assign = seg_assigns[0]
            seg_set_id = seg_assign["segmentation_set_id"]
            roi_type_id = seg_assign["roi_type_id"]
            seg_hex = uuid_to_hex(seg_set_id)

            # Read labels
            try:
                cell_labels = store.layers.read_labels(seg_hex, fov_hex)
            except Exception as exc:
                errors.append(f"FOV {fov_name}: failed to read labels: {exc}")
                continue

            # Read particle mask (threshold mask)
            particle_labels = None
            for ma in mask_assigns:
                mask_id = ma["threshold_mask_id"]
                mask_hex = uuid_to_hex(mask_id)
                try:
                    particle_labels = store.layers.read_mask(mask_hex)
                    break
                except Exception:
                    continue

            if particle_labels is None:
                errors.append(f"FOV {fov_name}: no particle labels available")
                continue

            # Read exclusion mask
            exclusion_mask = None
            # Exclusion not yet mapped in percell4 assignment model; placeholder

            # Get ROIs for this FOV
            rois = store.db.get_rois_by_fov_and_type(fov_id, roi_type_id)
            if roi_ids is not None:
                roi_id_set = set(roi_ids)
                rois = [r for r in rois if r["id"] in roi_id_set]

            if not rois:
                continue

            # Resolve condition name
            condition_name = "uncategorized"
            if fov["condition_id"]:
                conditions = store.get_conditions(exp_id)
                for c in conditions:
                    if c["id"] == fov["condition_id"]:
                        condition_name = c["name"]
                        break

            # Process each ROI
            for roi in rois:
                label_val = roi["label_id"]
                by = roi["bbox_y"]
                bx = roi["bbox_x"]
                bh = roi["bbox_h"]
                bw = roi["bbox_w"]

                # Crop to ROI bounding box
                label_crop = cell_labels[by:by + bh, bx:bx + bw]
                particle_crop = particle_labels[by:by + bh, bx:bx + bw]
                meas_crop = measurement_image[by:by + bh, bx:bx + bw]

                cell_mask = label_crop == label_val

                # Crop exclusion mask if available
                excl_crop = None
                if exclusion_mask is not None:
                    excl_crop = exclusion_mask[by:by + bh, bx:bx + bw]

                # Run per-particle BG subtraction
                results = process_particles_for_roi(
                    roi_id=roi["id"],
                    cell_mask=cell_mask,
                    particle_labels=particle_crop,
                    measurement_image=meas_crop,
                    exclusion_mask=excl_crop,
                    dilation_pixels=dilation_pixels,
                    max_background=max_background,
                )

                if not results:
                    continue

                rois_processed += 1

                # Crop normalization image if available
                norm_crop = None
                if norm_image is not None:
                    norm_crop = norm_image[by:by + bh, bx:bx + bw]

                for r in results:
                    # Measure normalization channel mean inside this particle
                    norm_mean = ""
                    if norm_crop is not None:
                        p_mask = (particle_crop == r.particle_label) & cell_mask
                        if np.any(p_mask):
                            norm_mean = float(np.mean(
                                norm_crop[p_mask].astype(np.float64)
                            ))

                    rows_by_condition[condition_name].append({
                        "particle_id": r.particle_label,
                        "roi_id": uuid_to_str(r.roi_id),
                        "fov_id": uuid_to_str(fov_id),
                        "fov_name": fov_name,
                        "condition": condition_name,
                        "bio_rep": "",
                        "area_pixels": r.area_pixels,
                        "raw_mean_intensity": r.raw_mean_intensity,
                        "raw_integrated_intensity": r.raw_integrated_intensity,
                        "bg_estimate": r.bg_estimate,
                        "bg_ring_pixels": r.bg_ring_pixels,
                        "bg_sub_mean_intensity": r.bg_sub_mean_intensity,
                        "bg_sub_integrated_intensity": r.bg_sub_integrated_intensity,
                        "norm_mean_intensity": norm_mean,
                    })
                    particles_processed += 1

        if on_progress:
            on_progress(len(fov_ids), len(fov_ids), "Done")

        # Export CSVs
        custom_outputs: dict[str, str] = {}
        if do_export_csv and rows_by_condition:
            csv_paths = self._export_csvs(store, rows_by_condition, measurement_channel)
            for condition, path in csv_paths.items():
                custom_outputs[f"csv_{condition}"] = str(path)

        if particles_processed == 0:
            errors.append("No particles found with valid background rings.")

        return PluginResult(
            fovs_processed=len(fov_ids),
            rois_processed=rois_processed,
            measurements_added=particles_processed,
            errors=errors,
        )

    def _export_csvs(
        self,
        store: ExperimentStore,
        rows_by_condition: dict[str, list[dict]],
        meas_channel: str,
    ) -> dict[str, Path]:
        """Write per-particle results to one CSV per condition."""
        exports_dir = store.root / "exports"
        exports_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: dict[str, Path] = {}

        for condition, rows in sorted(rows_by_condition.items()):
            safe_condition = condition.replace(" ", "_").replace("/", "_")
            filename = f"bg_subtraction_{meas_channel}_{safe_condition}_{timestamp}.csv"
            csv_path = exports_dir / filename

            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            logger.info(
                "Exported per-particle CSV for condition '%s' to %s (%d rows)",
                condition, csv_path, len(rows),
            )
            paths[condition] = csv_path

        return paths
