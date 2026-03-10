"""Split-Halo Condensate Analysis Plugin — BiFC split-Halo sensor analysis.

Measures both condensed phase (RNP granules) and dilute phase (surrounding
cytoplasm) for bimolecular fluorescence complementation assays.

Condensed phase: per-particle local background subtraction (reuses bg_subtraction_core).
Dilute phase: per-cell measurement of cytoplasm excluding a dilated particle mask.

Creates derived FOV images (condensed-only and dilute-only) for surface plot
visualization. Exports separate CSVs for granule and dilute measurements.
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

GRANULE_CSV_COLUMNS = [
    "particle_id",
    "roi_id",
    "roi_label",
    "fov_id",
    "fov_name",
    "threshold_name",
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

DILUTE_CSV_COLUMNS = [
    "roi_id",
    "roi_label",
    "fov_id",
    "fov_name",
    "threshold_name",
    "condition",
    "bio_rep",
    "dilute_area_pixels",
    "raw_mean_intensity",
    "raw_integrated_intensity",
    "bg_estimate",
    "bg_sub_mean_intensity",
    "bg_sub_integrated_intensity",
    "norm_mean_intensity",
]


class SplitHaloCondensateAnalysisPlugin(AnalysisPlugin):
    """Condensed + dilute phase analysis for BiFC split-Halo sensor experiments.

    Measures RNP granules (per-particle with local BG subtraction) and
    surrounding dilute phase (per-cell). Creates derived FOV images for
    surface plot visualization.
    """

    name = "split_halo_condensate_analysis"
    description = (
        "Split-Halo BiFC condensate analysis: granule + dilute phase "
        "measurements with derived FOV images"
    )

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        from scipy.ndimage import binary_dilation
        from skimage.morphology import disk

        from percell4.core.db_types import uuid_to_hex, uuid_to_str
        from percell4.plugins.bg_subtraction_core import (
            estimate_background_gaussian,
            process_particles_for_roi,
        )

        meas_channel: str = kwargs.get("measurement_channel", "")
        particle_channel: str = kwargs.get("particle_channel", "")
        exclusion_channel: str | None = kwargs.get("exclusion_channel")
        ring_dilation_pixels: int = kwargs.get("ring_dilation_pixels", 5)
        exclusion_dilation_pixels: int = kwargs.get("exclusion_dilation_pixels", 5)
        max_background: float | None = kwargs.get("max_background")
        normalization_channel: str | None = kwargs.get("normalization_channel")
        do_export_csv: bool = kwargs.get("export_csv", True)
        do_save_images: bool = kwargs.get("save_images", True)

        if not meas_channel:
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

        if meas_channel not in channel_index_by_name:
            raise RuntimeError(f"Measurement channel '{meas_channel}' not found.")

        meas_ch_idx = channel_index_by_name[meas_channel]
        norm_ch_idx = (
            channel_index_by_name.get(normalization_channel)
            if normalization_channel
            else None
        )

        exclusion_selem = disk(exclusion_dilation_pixels)

        # Accumulators
        granule_rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        dilute_rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        rois_processed = 0
        dilute_rois_processed = 0
        derived_count = 0
        errors: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov = store.get_fov(fov_id)
            if fov is None:
                errors.append(f"FOV not found: {uuid_to_str(fov_id)}")
                continue

            fov_hex = uuid_to_hex(fov_id)
            fov_name = fov["auto_name"] or "unknown"

            if on_progress:
                on_progress(fov_idx, len(fov_ids), fov_name)

            # Get active assignments
            active = store.get_active_assignments(fov_id)
            seg_assigns = active.get("segmentation", [])
            mask_assigns = active.get("mask", [])

            if not seg_assigns:
                errors.append(f"FOV {fov_name}: no segmentation")
                continue

            seg_assign = seg_assigns[0]
            seg_set_id = seg_assign["segmentation_set_id"]
            roi_type_id = seg_assign["roi_type_id"]
            seg_hex = uuid_to_hex(seg_set_id)

            # Read cell labels
            try:
                cell_labels = store.layers.read_labels(seg_hex, fov_hex)
            except Exception as exc:
                errors.append(f"FOV {fov_name}: failed to read labels: {exc}")
                continue

            h, w = cell_labels.shape

            # Read/merge particle labels from mask assignments
            merged_particle_labels = np.zeros((h, w), dtype=np.int32)
            label_offset = 0
            any_labels_read = False

            for ma in mask_assigns:
                mask_id = ma["threshold_mask_id"]
                mask_hex = uuid_to_hex(mask_id)
                try:
                    plabels = store.layers.read_mask(mask_hex)
                    any_labels_read = True
                    mask = plabels > 0
                    if np.any(mask):
                        merged_particle_labels[mask] = plabels[mask] + label_offset
                        label_offset += int(plabels.max())
                except Exception:
                    continue

            if not any_labels_read:
                errors.append(f"FOV {fov_name}: no particle labels")
                continue

            # Read measurement image
            try:
                measurement_image = store.layers.read_image_channel_numpy(
                    fov_hex, meas_ch_idx
                )
            except Exception as exc:
                errors.append(f"FOV {fov_name}: failed to read measurement: {exc}")
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

            # Resolve condition name
            condition_name = "uncategorized"
            if fov["condition_id"]:
                conditions = store.get_conditions(exp_id)
                for c in conditions:
                    if c["id"] == fov["condition_id"]:
                        condition_name = c["name"]
                        break

            # Get ROIs
            rois = store.db.get_rois_by_fov_and_type(fov_id, roi_type_id)
            if roi_ids is not None:
                roi_id_set = set(roi_ids)
                rois = [r for r in rois if r["id"] in roi_id_set]

            if not rois:
                continue

            # Initialize FOV masks for derived images
            condensed_mask = np.zeros((h, w), dtype=bool)
            dilute_mask_full = np.zeros((h, w), dtype=bool)

            # Process each ROI
            for roi in rois:
                label_val = roi["label_id"]
                by = roi["bbox_y"]
                bx = roi["bbox_x"]
                bh = roi["bbox_h"]
                bw = roi["bbox_w"]

                label_crop = cell_labels[by:by + bh, bx:bx + bw]
                particle_crop = merged_particle_labels[by:by + bh, bx:bx + bw]
                meas_crop = measurement_image[by:by + bh, bx:bx + bw]
                cell_mask = label_crop == label_val

                # --- Granule measurement (per-particle) ---
                results = process_particles_for_roi(
                    roi_id=roi["id"],
                    cell_mask=cell_mask,
                    particle_labels=particle_crop,
                    measurement_image=meas_crop,
                    exclusion_mask=None,
                    dilation_pixels=ring_dilation_pixels,
                    max_background=max_background,
                )

                if results:
                    rois_processed += 1
                    norm_crop = None
                    if norm_image is not None:
                        norm_crop = norm_image[by:by + bh, bx:bx + bw]

                    for r in results:
                        norm_mean = ""
                        if norm_crop is not None:
                            p_mask = (particle_crop == r.particle_label) & cell_mask
                            if np.any(p_mask):
                                norm_mean = float(np.mean(
                                    norm_crop[p_mask].astype(np.float64)
                                ))

                        granule_rows_by_condition[condition_name].append({
                            "particle_id": r.particle_label,
                            "roi_id": uuid_to_str(r.roi_id),
                            "roi_label": label_val,
                            "fov_id": uuid_to_str(fov_id),
                            "fov_name": fov_name,
                            "threshold_name": "",
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

                # --- Dilute phase measurement (per-cell) ---
                all_particles_mask = (particle_crop > 0) & cell_mask
                dilated_particles = binary_dilation(
                    all_particles_mask, structure=exclusion_selem,
                )
                dilute_mask = cell_mask & ~dilated_particles
                dilute_pixels = int(np.sum(dilute_mask))

                if dilute_pixels > 0:
                    dilute_intensities = meas_crop[dilute_mask].astype(np.float64)
                    raw_mean = float(np.mean(dilute_intensities))
                    raw_integrated = float(np.sum(dilute_intensities))

                    bg_result = estimate_background_gaussian(
                        dilute_intensities, max_background=max_background,
                    )
                    bg_value = bg_result[0] if bg_result else 0.0

                    bg_sub_mean = raw_mean - bg_value
                    bg_sub_integrated = raw_integrated - (bg_value * dilute_pixels)

                    dilute_norm_mean = ""
                    if norm_image is not None:
                        norm_crop_d = norm_image[by:by + bh, bx:bx + bw]
                        if np.any(dilute_mask):
                            dilute_norm_mean = float(np.mean(
                                norm_crop_d[dilute_mask].astype(np.float64)
                            ))

                    dilute_rows_by_condition[condition_name].append({
                        "roi_id": uuid_to_str(roi["id"]),
                        "roi_label": label_val,
                        "fov_id": uuid_to_str(fov_id),
                        "fov_name": fov_name,
                        "threshold_name": "",
                        "condition": condition_name,
                        "bio_rep": "",
                        "dilute_area_pixels": dilute_pixels,
                        "raw_mean_intensity": raw_mean,
                        "raw_integrated_intensity": raw_integrated,
                        "bg_estimate": bg_value,
                        "bg_sub_mean_intensity": bg_sub_mean,
                        "bg_sub_integrated_intensity": bg_sub_integrated,
                        "norm_mean_intensity": dilute_norm_mean,
                    })
                    dilute_rois_processed += 1

                # Accumulate full-FOV masks
                condensed_mask[by:by + bh, bx:bx + bw] |= all_particles_mask
                dilute_mask_full[by:by + bh, bx:bx + bw] |= dilute_mask

            # --- Derived FOV creation (once per FOV) ---
            if do_save_images:
                for phase_suffix, mask in [
                    ("condensed_phase", condensed_mask),
                    ("dilute_phase", dilute_mask_full),
                ]:
                    def transform_fn(
                        arrays: dict[int, np.ndarray],
                        _mask: np.ndarray = mask,
                    ) -> dict[int, np.ndarray]:
                        return {
                            k: np.where(_mask, v, 0).astype(v.dtype)
                            for k, v in arrays.items()
                        }

                    try:
                        store.create_derived_fov(
                            source_fov_id=fov_id,
                            derivation_op=phase_suffix,
                            params={"measurement_channel": meas_channel},
                            transform_fn=transform_fn,
                        )
                        derived_count += 1
                    except Exception as exc:
                        errors.append(
                            f"Failed to create {phase_suffix} derived FOV: {exc}"
                        )

        if on_progress:
            on_progress(len(fov_ids), len(fov_ids), "Done")

        # Export CSVs
        if do_export_csv:
            if granule_rows_by_condition:
                self._export_csvs(
                    store, granule_rows_by_condition, meas_channel, "granule",
                )
            if dilute_rows_by_condition:
                self._export_csvs(
                    store, dilute_rows_by_condition, meas_channel, "dilute",
                )

        if particles_processed == 0:
            errors.append("No particles found with valid background rings.")

        return PluginResult(
            fovs_processed=len(fov_ids),
            rois_processed=rois_processed + dilute_rois_processed,
            measurements_added=particles_processed,
            derived_fovs_created=derived_count,
            errors=errors,
        )

    def _export_csvs(
        self,
        store: ExperimentStore,
        rows_by_condition: dict[str, list[dict]],
        meas_channel: str,
        measurement_type: str,
    ) -> dict[str, Path]:
        """Write measurement results to one CSV per condition."""
        exports_dir = store.root / "exports"
        exports_dir.mkdir(exist_ok=True)

        columns = (
            GRANULE_CSV_COLUMNS
            if measurement_type == "granule"
            else DILUTE_CSV_COLUMNS
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: dict[str, Path] = {}

        for condition, rows in sorted(rows_by_condition.items()):
            safe_condition = condition.replace(" ", "_").replace("/", "_")
            filename = (
                f"condensate_{measurement_type}_{meas_channel}"
                f"_{safe_condition}_{timestamp}.csv"
            )
            csv_path = exports_dir / filename

            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)

            logger.info(
                "Exported %s CSV for condition '%s' to %s (%d rows)",
                measurement_type, condition, csv_path, len(rows),
            )
            paths[condition] = csv_path

        return paths
