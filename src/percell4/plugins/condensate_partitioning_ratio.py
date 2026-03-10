"""Condensate Partitioning Ratio Plugin — per-particle condensate/dilute phase analysis.

Measures the partitioning of individual condensates by comparing fluorescence
intensity inside each particle (condensed phase) to intensity in a dilated ring
outside each particle (dilute phase), then reporting the ratio.

Two-step dilation ring construction:
  1. Dilate particle mask by gap_pixels (exclusion zone, clears PSF)
  2. Dilate particle mask by gap_pixels + ring_pixels (outer boundary)
  3. Ring = outer & ~inner, clipped to cell mask, excluding other particles

Output: per-particle CSV with area, mean/integrated intensity for both phases,
and partitioning ratio (condensate_mean / dilute_mean).
"""

from __future__ import annotations

import csv
import logging
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

PARTITION_CSV_COLUMNS_BASE = [
    "particle_id",
    "roi_id",
    "roi_label",
    "fov_id",
    "fov_name",
    "condition",
    "bio_rep",
    "threshold_name",
    "condensate_area_pixels",
    "condensate_mean_intensity",
    "condensate_integrated_intensity",
    "dilute_area_pixels",
    "dilute_mean_intensity",
    "dilute_integrated_intensity",
    "partitioning_ratio",
]

PARTITION_CSV_COLUMNS_UM2 = [
    "particle_id",
    "roi_id",
    "roi_label",
    "fov_id",
    "fov_name",
    "condition",
    "bio_rep",
    "threshold_name",
    "condensate_area_pixels",
    "condensate_area_um2",
    "condensate_mean_intensity",
    "condensate_integrated_intensity",
    "dilute_area_pixels",
    "dilute_area_um2",
    "dilute_mean_intensity",
    "dilute_integrated_intensity",
    "partitioning_ratio",
]

# Default columns list (with um2 for backward compatibility)
PARTITION_CSV_COLUMNS = PARTITION_CSV_COLUMNS_UM2


class CondensatePartitioningRatioPlugin(AnalysisPlugin):
    """Per-particle condensate/dilute partitioning ratio analysis.

    Measures RNP granules (condensed phase) and a dilated ring around each
    particle (dilute phase), then computes the partitioning ratio
    (condensate_mean / dilute_mean) for each particle.
    """

    name = "condensate_partitioning_ratio"
    description = (
        "Per-particle condensate/dilute partitioning ratio "
        "with dilation ring measurement"
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

        meas_channel: str = kwargs.get("measurement_channel", "")
        particle_channel: str = kwargs.get("particle_channel", "")
        gap_pixels: int = kwargs.get("gap_pixels", 3)
        ring_pixels: int = kwargs.get("ring_pixels", 2)
        min_ring_pixels: int = kwargs.get("min_ring_pixels", 10)
        do_export_csv: bool = kwargs.get("export_csv", True)

        if not meas_channel:
            raise RuntimeError("'measurement_channel' parameter is required.")
        if not particle_channel:
            raise RuntimeError("'particle_channel' parameter is required.")

        # Resolve channel indices
        exp = store.db.get_experiment()
        exp_id = exp["id"]
        all_channels = store.db.get_channels(exp_id)
        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }

        if meas_channel not in channel_index_by_name:
            raise RuntimeError(f"Measurement channel '{meas_channel}' not found.")

        meas_ch_idx = channel_index_by_name[meas_channel]

        # Pre-build structuring elements
        inner_selem = disk(gap_pixels) if gap_pixels > 0 else None
        outer_selem = disk(gap_pixels + ring_pixels)

        # Accumulators
        rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        rois_processed = 0
        nan_count = 0
        errors: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov = store.db.get_fov(fov_id)
            if fov is None:
                errors.append(f"FOV not found: {uuid_to_str(fov_id)}")
                continue

            fov_hex = uuid_to_hex(fov_id)
            fov_name = fov["auto_name"] or "unknown"

            # Get pixel_size_um from FOV record
            fov_pixel_size_um: float | None = None
            try:
                fov_pixel_size_um = fov["pixel_size_um"]
            except (IndexError, KeyError):
                pass

            if on_progress:
                on_progress(fov_idx, len(fov_ids), fov_name)

            # Get active assignments
            active = store.db.get_active_assignments(fov_id)
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

            # Resolve condition name
            condition_name = "uncategorized"
            if fov["condition_id"]:
                conditions = store.db.get_conditions(exp_id)
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

                # Find particles within this cell
                particles_in_cell = particle_crop[cell_mask]
                unique_particles = np.unique(particles_in_cell)
                unique_particles = unique_particles[unique_particles > 0]

                if len(unique_particles) == 0:
                    continue

                rois_processed += 1
                all_particles_in_crop = particle_crop > 0

                for particle_label in unique_particles:
                    particle_mask = particle_crop == particle_label

                    # Condensate measurement
                    condensate_pixels = meas_crop[particle_mask].astype(np.float64)
                    condensate_area_pixels = int(particle_mask.sum())
                    condensate_mean = float(np.mean(condensate_pixels))
                    condensate_integrated = float(np.sum(condensate_pixels))
                    condensate_area_um2: float | None = None
                    if fov_pixel_size_um is not None:
                        condensate_area_um2 = condensate_area_pixels * (fov_pixel_size_um ** 2)

                    # Ring construction
                    all_other_particles = all_particles_in_crop & ~particle_mask

                    if inner_selem is not None:
                        inner = binary_dilation(particle_mask, structure=inner_selem)
                    else:
                        inner = particle_mask

                    outer = binary_dilation(particle_mask, structure=outer_selem)
                    ring = outer & ~inner
                    ring = ring & cell_mask
                    ring = ring & ~all_other_particles
                    ring_area = int(ring.sum())

                    if ring_area < min_ring_pixels:
                        nan_count += 1
                        dilute_area_pixels = ring_area
                        dilute_mean = math.nan
                        dilute_integrated = math.nan
                        partitioning_ratio = math.nan
                    else:
                        dilute_pixels_arr = meas_crop[ring].astype(np.float64)
                        dilute_area_pixels = ring_area
                        dilute_mean = float(np.mean(dilute_pixels_arr))
                        dilute_integrated = float(np.sum(dilute_pixels_arr))

                        if dilute_mean == 0.0:
                            partitioning_ratio = math.nan
                            nan_count += 1
                        else:
                            partitioning_ratio = condensate_mean / dilute_mean

                    dilute_area_um2: float | None = None
                    if fov_pixel_size_um is not None:
                        dilute_area_um2 = dilute_area_pixels * (fov_pixel_size_um ** 2)

                    row_dict: dict[str, Any] = {
                        "particle_id": int(particle_label),
                        "roi_id": uuid_to_str(roi["id"]),
                        "roi_label": label_val,
                        "fov_id": uuid_to_str(fov_id),
                        "fov_name": fov_name,
                        "condition": condition_name,
                        "bio_rep": "",
                        "threshold_name": "",
                        "condensate_area_pixels": condensate_area_pixels,
                        "condensate_mean_intensity": condensate_mean,
                        "condensate_integrated_intensity": condensate_integrated,
                        "dilute_area_pixels": dilute_area_pixels,
                        "dilute_mean_intensity": dilute_mean,
                        "dilute_integrated_intensity": dilute_integrated,
                        "partitioning_ratio": partitioning_ratio,
                    }

                    # Include _um2 columns only when pixel_size_um is available
                    if fov_pixel_size_um is not None:
                        row_dict["condensate_area_um2"] = condensate_area_um2
                        row_dict["dilute_area_um2"] = dilute_area_um2

                    rows_by_condition[condition_name].append(row_dict)
                    particles_processed += 1

        if on_progress:
            on_progress(len(fov_ids), len(fov_ids), "Done")

        # Export CSVs
        if do_export_csv and rows_by_condition:
            self._export_csvs(store, rows_by_condition, meas_channel)

        if nan_count > 0:
            errors.append(
                f"{nan_count} particle(s) had insufficient ring area or zero "
                "dilute intensity and received NaN partitioning ratio."
            )

        if particles_processed == 0:
            errors.append("No particles found in any cell.")

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
        """Write per-particle partitioning results to one CSV per condition."""
        exports_dir = store.root / "exports"
        exports_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: dict[str, Path] = {}

        for condition, rows in sorted(rows_by_condition.items()):
            safe_condition = condition.replace(" ", "_").replace("/", "_")
            filename = (
                f"partitioning_ratio_{meas_channel}"
                f"_{safe_condition}_{timestamp}.csv"
            )
            csv_path = exports_dir / filename

            # Determine columns: include _um2 only if any row has them
            has_um2 = any("condensate_area_um2" in r for r in rows)
            columns = PARTITION_CSV_COLUMNS_UM2 if has_um2 else PARTITION_CSV_COLUMNS_BASE

            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=columns, extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(rows)

            logger.info(
                "Exported partitioning ratio CSV for condition '%s' to %s (%d rows)",
                condition, csv_path, len(rows),
            )
            paths[condition] = csv_path

        return paths
