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

logger = logging.getLogger(__name__)

PARTITION_CSV_COLUMNS = [
    "particle_id",
    "cell_id",
    "cell_label",
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


class CondensatePartitioningRatioPlugin(AnalysisPlugin):
    """Per-particle condensate/dilute partitioning ratio analysis.

    Measures RNP granules (condensed phase) and a dilated ring around each
    particle (dilute phase), then computes the partitioning ratio
    (condensate_mean / dilute_mean) for each particle.
    """

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="condensate_partitioning_ratio",
            version="1.0.0",
            description="Per-particle condensate/dilute partitioning ratio with dilation ring measurement",
            author="PerCell Team",
        )

    def required_inputs(self) -> list[PluginInputRequirement]:
        return [
            PluginInputRequirement(kind=InputKind.SEGMENTATION),
            PluginInputRequirement(kind=InputKind.THRESHOLD),
        ]

    def validate(self, store: ExperimentStore) -> list[str]:
        errors: list[str] = []

        channels = store.get_channels()
        if not channels:
            errors.append("No channels found in the experiment.")

        cell_count = store.get_cell_count()
        if cell_count == 0:
            errors.append("No cells found. Run segmentation first.")

        thresholds = store.get_thresholds()
        if not thresholds:
            errors.append(
                "No threshold runs found. Run thresholding first to generate particle masks."
            )

        return errors

    def get_parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "measurement_channel": {
                    "type": "string",
                    "description": "Channel for intensity measurement",
                },
                "particle_channel": {
                    "type": "string",
                    "description": "Channel whose particle mask defines condensates",
                },
                "gap_pixels": {
                    "type": "integer",
                    "description": "Exclusion zone around particle in pixels (not measured; clears PSF)",
                    "default": 3,
                    "minimum": 0,
                },
                "ring_pixels": {
                    "type": "integer",
                    "description": "Measurement ring width beyond the gap in pixels",
                    "default": 2,
                    "minimum": 1,
                },
                "min_ring_pixels": {
                    "type": "integer",
                    "description": "Particles with ring area below this threshold get NaN ratio",
                    "default": 10,
                    "minimum": 0,
                },
                "export_csv": {
                    "type": "boolean",
                    "description": "Export per-particle CSV",
                    "default": True,
                },
            },
            "required": ["measurement_channel", "particle_channel"],
        }

    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        from scipy.ndimage import binary_dilation
        from skimage.morphology import disk

        params = parameters or {}
        meas_channel = params["measurement_channel"]
        particle_channel = params["particle_channel"]
        gap_pixels = params.get("gap_pixels", 3)
        ring_pixels = params.get("ring_pixels", 2)
        min_ring_pixels = params.get("min_ring_pixels", 10)
        do_export_csv = params.get("export_csv", True)

        # Find threshold runs for particle channel
        all_thresholds = store.get_thresholds()
        particle_runs = [
            tr for tr in all_thresholds if tr.source_channel == particle_channel
        ]
        if not particle_runs:
            raise RuntimeError(
                f"No threshold run found for channel '{particle_channel}'. "
                "Run 'Grouped intensity thresholding' first to generate particle masks."
            )

        # Determine FOVs to process
        if cell_ids is not None:
            cells_df = store.get_cells()
            cells_df = cells_df[cells_df["id"].isin(cell_ids)]
            fov_ids = sorted(cells_df["fov_id"].unique().tolist())
        else:
            fovs = store.get_fovs()
            fov_ids = [f.id for f in fovs]

        # Accumulators
        rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        cells_processed = 0
        nan_count = 0
        warnings: list[str] = []

        # Build threshold lookup by ID
        threshold_map = {tr.id: tr for tr in all_thresholds}

        # Pre-build structuring elements
        inner_selem = disk(gap_pixels) if gap_pixels > 0 else None
        outer_selem = disk(gap_pixels + ring_pixels)

        for fov_idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            # Resolve thresholds from config matrix
            fov_config = store.get_fov_config(fov_id)
            fov_threshold_pairs: list[tuple[int, int, str]] = []
            for entry in fov_config:
                if entry.threshold_id is None:
                    continue
                thr_info = threshold_map.get(entry.threshold_id)
                if thr_info is None:
                    continue
                if thr_info.source_channel != particle_channel:
                    continue
                fov_threshold_pairs.append(
                    (entry.segmentation_id, entry.threshold_id, thr_info.name)
                )

            if not fov_threshold_pairs:
                # Fallback: use source_fov_id matching
                seg_runs = [
                    s
                    for s in store.get_segmentations(seg_type="cellular")
                    if s.source_fov_id == fov_id
                ]
                fov_thr_runs = [
                    tr for tr in particle_runs if tr.source_fov_id == fov_id
                ]
                if seg_runs and fov_thr_runs:
                    fov_threshold_pairs = [
                        (seg_runs[0].id, fov_thr_runs[-1].id, fov_thr_runs[-1].name)
                    ]

            if not fov_threshold_pairs:
                warnings.append(
                    f"Skipped FOV {fov_id}: no matching threshold configured"
                )
                if progress_callback:
                    progress_callback(
                        fov_idx + 1, len(fov_ids), fov_info.display_name
                    )
                continue

            # Use the segmentation from the first config entry
            seg_run_id = fov_threshold_pairs[0][0]

            # Read cell labels once
            try:
                cell_labels = store.read_labels(seg_run_id)
            except Exception as exc:
                logger.warning(
                    "Skipping FOV %s: failed to read cell labels: %s",
                    fov_info.display_name,
                    exc,
                )
                warnings.append(f"Skipped FOV {fov_info.display_name}: {exc}")
                if progress_callback:
                    progress_callback(
                        fov_idx + 1, len(fov_ids), fov_info.display_name
                    )
                continue

            # Merge particle labels from all matching thresholds
            h, w = cell_labels.shape
            merged_particle_labels = np.zeros((h, w), dtype=np.int32)
            label_offset = 0
            loaded_thr_names: list[str] = []
            any_labels_read = False

            for _, thr_run_id, thr_name in fov_threshold_pairs:
                try:
                    plabels = store.read_particle_labels(thr_run_id)
                except Exception:
                    logger.debug(
                        "FOV %s: threshold '%s' has no particle labels, skipping",
                        fov_info.display_name,
                        thr_name,
                    )
                    continue

                any_labels_read = True
                loaded_thr_names.append(thr_name)

                # Renumber to avoid collisions
                mask = plabels > 0
                if np.any(mask):
                    merged_particle_labels[mask] = plabels[mask] + label_offset
                    label_offset += int(plabels.max())

            if not any_labels_read:
                warnings.append(
                    f"Skipped FOV {fov_info.display_name}: "
                    "no particle labels found in any configured threshold"
                )
                if progress_callback:
                    progress_callback(
                        fov_idx + 1, len(fov_ids), fov_info.display_name
                    )
                continue

            combined_thr_name = "+".join(loaded_thr_names)

            # Read measurement image
            try:
                measurement_image = store.read_image_numpy(fov_id, meas_channel)
            except Exception as exc:
                logger.warning(
                    "Skipping FOV %s: failed to read measurement image: %s",
                    fov_info.display_name,
                    exc,
                )
                warnings.append(f"Skipped FOV {fov_info.display_name}: {exc}")
                if progress_callback:
                    progress_callback(
                        fov_idx + 1, len(fov_ids), fov_info.display_name
                    )
                continue

            # Get cells for this FOV
            cells_df = store.get_cells(fov_id=fov_id)
            if cell_ids is not None:
                cells_df = cells_df[cells_df["id"].isin(cell_ids)]

            if cells_df.empty:
                if progress_callback:
                    progress_callback(
                        fov_idx + 1, len(fov_ids), fov_info.display_name
                    )
                continue

            condition = fov_info.condition or "uncategorized"
            pixel_size_um = fov_info.pixel_size_um

            # Process each cell
            for _, cell_row in cells_df.iterrows():
                cell_id = int(cell_row["id"])
                label_val = int(cell_row["label_value"])
                bx = int(cell_row["bbox_x"])
                by = int(cell_row["bbox_y"])
                bw = int(cell_row["bbox_w"])
                bh = int(cell_row["bbox_h"])

                # Crop to cell bounding box
                label_crop = cell_labels[by : by + bh, bx : bx + bw]
                particle_crop = merged_particle_labels[by : by + bh, bx : bx + bw]
                meas_crop = measurement_image[by : by + bh, bx : bx + bw]

                cell_mask = label_crop == label_val

                # Find particles within this cell
                particles_in_cell = particle_crop[cell_mask]
                unique_particles = np.unique(particles_in_cell)
                unique_particles = unique_particles[unique_particles > 0]

                if len(unique_particles) == 0:
                    continue

                cells_processed += 1

                # Build mask of all particles in this crop for exclusion
                all_particles_in_crop = particle_crop > 0

                for particle_label in unique_particles:
                    particle_mask = particle_crop == particle_label

                    # --- Condensate measurement (inside particle) ---
                    condensate_pixels = meas_crop[particle_mask].astype(np.float64)
                    condensate_area_pixels = int(particle_mask.sum())
                    condensate_mean = float(np.mean(condensate_pixels))
                    condensate_integrated = float(np.sum(condensate_pixels))

                    if pixel_size_um is not None:
                        condensate_area_um2 = condensate_area_pixels * (
                            pixel_size_um**2
                        )
                    else:
                        condensate_area_um2 = math.nan

                    # --- Ring construction ---
                    all_other_particles = all_particles_in_crop & ~particle_mask

                    if inner_selem is not None:
                        inner = binary_dilation(particle_mask, structure=inner_selem)
                    else:
                        # gap_pixels == 0: inner boundary is the particle itself
                        inner = particle_mask

                    outer = binary_dilation(particle_mask, structure=outer_selem)

                    ring = outer & ~inner
                    ring = ring & cell_mask  # clip to cell boundary
                    ring = ring & ~all_other_particles  # exclude other condensates

                    ring_area = int(ring.sum())

                    # --- Ring quality check ---
                    if ring_area < min_ring_pixels:
                        # Insufficient ring area — NaN for dilute and ratio
                        nan_count += 1
                        dilute_area_pixels = ring_area
                        dilute_mean = math.nan
                        dilute_integrated = math.nan
                        partitioning_ratio = math.nan

                        if pixel_size_um is not None:
                            dilute_area_um2 = dilute_area_pixels * (
                                pixel_size_um**2
                            )
                        else:
                            dilute_area_um2 = math.nan
                    else:
                        # --- Dilute measurement (ring pixels) ---
                        dilute_pixels = meas_crop[ring].astype(np.float64)
                        dilute_area_pixels = ring_area
                        dilute_mean = float(np.mean(dilute_pixels))
                        dilute_integrated = float(np.sum(dilute_pixels))

                        if pixel_size_um is not None:
                            dilute_area_um2 = dilute_area_pixels * (
                                pixel_size_um**2
                            )
                        else:
                            dilute_area_um2 = math.nan

                        # --- Ratio ---
                        if dilute_mean == 0.0:
                            partitioning_ratio = math.nan
                            nan_count += 1
                        else:
                            partitioning_ratio = condensate_mean / dilute_mean

                    # Build row
                    rows_by_condition[condition].append(
                        {
                            "particle_id": int(particle_label),
                            "cell_id": cell_id,
                            "cell_label": label_val,
                            "fov_id": fov_id,
                            "fov_name": fov_info.display_name,
                            "condition": condition,
                            "bio_rep": fov_info.bio_rep,
                            "threshold_name": combined_thr_name,
                            "condensate_area_pixels": condensate_area_pixels,
                            "condensate_area_um2": condensate_area_um2,
                            "condensate_mean_intensity": condensate_mean,
                            "condensate_integrated_intensity": condensate_integrated,
                            "dilute_area_pixels": dilute_area_pixels,
                            "dilute_area_um2": dilute_area_um2,
                            "dilute_mean_intensity": dilute_mean,
                            "dilute_integrated_intensity": dilute_integrated,
                            "partitioning_ratio": partitioning_ratio,
                        }
                    )
                    particles_processed += 1

            if progress_callback:
                progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)

        # Export CSVs
        custom_outputs: dict[str, str] = {}
        if do_export_csv and rows_by_condition:
            csv_paths = self._export_csvs(store, rows_by_condition, meas_channel)
            for cond, path in csv_paths.items():
                custom_outputs[f"csv_partitioning_{cond}"] = str(path)

        # Build warnings
        if nan_count > 0:
            warnings.append(
                f"{nan_count} particle(s) had insufficient ring area or zero "
                "dilute intensity and received NaN partitioning ratio."
            )

        if particles_processed == 0:
            warnings.append("No particles found in any cell.")

        return PluginResult(
            measurements_written=particles_processed,
            cells_processed=cells_processed,
            custom_outputs=custom_outputs,
            warnings=warnings,
        )

    def _export_csvs(
        self,
        store: ExperimentStore,
        rows_by_condition: dict[str, list[dict]],
        meas_channel: str,
    ) -> dict[str, Path]:
        """Write per-particle partitioning results to one CSV per condition.

        Args:
            store: ExperimentStore for determining export path.
            rows_by_condition: Rows grouped by condition name.
            meas_channel: Measurement channel name (used in filename).

        Returns:
            Mapping of condition name to CSV file path.
        """
        exports_dir = Path(store.path) / "exports"
        exports_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: dict[str, Path] = {}

        for condition, rows in sorted(rows_by_condition.items()):
            safe_condition = condition.replace(" ", "_").replace("/", "_")
            filename = f"partitioning_ratio_{meas_channel}_{safe_condition}_{timestamp}.csv"
            csv_path = exports_dir / filename

            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PARTITION_CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            logger.info(
                "Exported partitioning ratio CSV for condition '%s' to %s (%d rows)",
                condition,
                csv_path,
                len(rows),
            )
            paths[condition] = csv_path

        return paths
