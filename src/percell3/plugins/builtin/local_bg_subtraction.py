"""Local Background Subtraction Plugin — per-particle local BG estimation.

Uses Gaussian peak detection on a dilated ring around each particle to estimate
and subtract the local background from measurement channel intensities.

This is the PerCell 3 port of the m7G Cap Enrichment Analysis algorithm,
made channel-agnostic and universal.

Output is per-particle CSV files, one per condition.
"""

from __future__ import annotations

import csv
import logging
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

# CSV export column order (norm_mean_intensity appended when normalization_channel is set)
CSV_COLUMNS = [
    "particle_id",
    "cell_id",
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

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="local_bg_subtraction",
            version="1.0.0",
            description="Per-particle local background subtraction with Gaussian peak detection",
            author="PerCell Team",
        )

    def required_inputs(self) -> list[PluginInputRequirement]:
        return [
            PluginInputRequirement(kind=InputKind.SEGMENTATION),
            PluginInputRequirement(kind=InputKind.THRESHOLD),
        ]

    def validate(self, store: ExperimentStore) -> list[str]:
        """Check experiment has cells, channels, and particle masks."""
        errors: list[str] = []

        channels = store.get_channels()
        if not channels:
            errors.append("No channels found in the experiment.")

        cell_count = store.get_cell_count()
        if cell_count == 0:
            errors.append("No cells found. Run segmentation first.")

        threshold_runs = store.get_threshold_runs()
        if not threshold_runs:
            errors.append("No threshold runs found. Run thresholding first to generate particle masks.")

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
                    "description": "Channel whose particle mask to dilate and measure",
                },
                "exclusion_channel": {
                    "type": ["string", "null"],
                    "description": "Optional channel mask to exclude from background ring",
                    "default": None,
                },
                "dilation_pixels": {
                    "type": "integer",
                    "description": "Ring dilation amount in pixels",
                    "default": 5,
                },
                "max_background": {
                    "type": ["number", "null"],
                    "description": "Upper bound on background estimate",
                    "default": None,
                },
                "normalization_channel": {
                    "type": ["string", "null"],
                    "description": "Optional channel whose mean intensity inside each particle is reported for normalization",
                    "default": None,
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
        """Execute background subtraction across FOVs.

        Output is per-particle: one CSV per condition with a row for each
        particle.  No cell-level aggregation is written to the database.

        Parameters dict keys:
            measurement_channel: Channel name for intensity measurement.
            particle_channel: Channel whose particle labels to use.
            exclusion_channel: Optional channel mask to exclude from ring.
            dilation_pixels: Ring dilation (default 5).
            max_background: Upper bound on BG estimate (default None).
            export_csv: Whether to export per-particle CSV (default True).
        """
        from percell3.plugins.builtin.bg_subtraction_core import process_particles_for_cell

        params = parameters or {}
        meas_channel = params["measurement_channel"]
        particle_channel = params["particle_channel"]
        exclusion_channel = params.get("exclusion_channel")
        normalization_channel = params.get("normalization_channel")
        dilation_pixels = params.get("dilation_pixels", 5)
        max_background = params.get("max_background")
        do_export_csv = params.get("export_csv", True)

        # Validate that at least one threshold run exists for the particle channel
        all_threshold_runs = store.get_threshold_runs()
        particle_runs = [
            tr for tr in all_threshold_runs if tr.channel == particle_channel
        ]
        if not particle_runs:
            raise RuntimeError(
                f"No threshold run found for channel '{particle_channel}'. "
                "Run 'Grouped intensity thresholding' first to generate particle masks."
            )

        # Determine FOVs to process
        if cell_ids is not None:
            # Get FOV IDs from the given cell_ids
            cells_df = store.get_cells()
            cells_df = cells_df[cells_df["id"].isin(cell_ids)]
            fov_ids = sorted(cells_df["fov_id"].unique().tolist())
        else:
            fovs = store.get_fovs()
            fov_ids = [f.id for f in fovs]

        # Collect per-particle rows grouped by condition
        rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        cells_processed = 0
        warnings: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            # Resolve per-FOV run IDs
            seg_runs = store.list_segmentation_runs(fov_id)
            seg_run_id = seg_runs[0].id if seg_runs else None
            fov_thr_runs = [tr for tr in particle_runs if tr.fov_id == fov_id]
            thr_run_id = fov_thr_runs[-1].id if fov_thr_runs else None

            if seg_run_id is None or thr_run_id is None:
                warnings.append(f"Skipped FOV {fov_id}: missing seg or threshold run")
                continue

            # Read images for this FOV
            try:
                cell_labels = store.read_labels(fov_id, seg_run_id)
                particle_labels = store.read_particle_labels(fov_id, particle_channel, thr_run_id)
                measurement_image = store.read_image_numpy(fov_id, meas_channel)
            except Exception as exc:
                logger.warning(
                    "Skipping FOV %s: failed to read data: %s",
                    fov_info.display_name, exc,
                )
                warnings.append(f"Skipped FOV {fov_info.display_name}: {exc}")
                continue

            # Read normalization channel image if specified
            norm_image = None
            if normalization_channel:
                try:
                    norm_image = store.read_image_numpy(fov_id, normalization_channel)
                except Exception as exc:
                    logger.warning(
                        "FOV %s: failed to read normalization channel '%s': %s",
                        fov_info.display_name, normalization_channel, exc,
                    )
                    warnings.append(
                        f"FOV {fov_info.display_name}: normalization channel "
                        f"'{normalization_channel}' unavailable: {exc}"
                    )

            # Read exclusion mask if specified
            exclusion_mask = None
            if exclusion_channel:
                try:
                    excl_thr_runs = [
                        tr for tr in all_threshold_runs
                        if tr.channel == exclusion_channel and tr.fov_id == fov_id
                    ]
                    if excl_thr_runs:
                        excl_raw = store.read_mask(fov_id, exclusion_channel, excl_thr_runs[-1].id)
                        exclusion_mask = excl_raw > 0
                except Exception:
                    logger.debug(
                        "No exclusion mask for FOV %s channel %s, proceeding without",
                        fov_info.display_name, exclusion_channel,
                    )

            # Get cells for this FOV
            cells_df = store.get_cells(fov_id=fov_id)
            if cell_ids is not None:
                cells_df = cells_df[cells_df["id"].isin(cell_ids)]

            if cells_df.empty:
                continue

            # Process each cell
            for _, cell_row in cells_df.iterrows():
                cell_id = int(cell_row["id"])
                label_val = int(cell_row["label_value"])
                bx = int(cell_row["bbox_x"])
                by = int(cell_row["bbox_y"])
                bw = int(cell_row["bbox_w"])
                bh = int(cell_row["bbox_h"])

                # Crop to cell bounding box
                label_crop = cell_labels[by:by + bh, bx:bx + bw]
                particle_crop = particle_labels[by:by + bh, bx:bx + bw]
                meas_crop = measurement_image[by:by + bh, bx:bx + bw]

                cell_mask = label_crop == label_val

                # Crop exclusion mask if available
                excl_crop = None
                if exclusion_mask is not None:
                    excl_crop = exclusion_mask[by:by + bh, bx:bx + bw]

                # Run per-particle BG subtraction
                results = process_particles_for_cell(
                    cell_id=cell_id,
                    cell_mask=cell_mask,
                    particle_labels=particle_crop,
                    measurement_image=meas_crop,
                    exclusion_mask=excl_crop,
                    dilation_pixels=dilation_pixels,
                    max_background=max_background,
                )

                if not results:
                    continue

                cells_processed += 1

                # Crop normalization image to cell bbox if available
                norm_crop = None
                if norm_image is not None:
                    norm_crop = norm_image[by:by + bh, bx:bx + bw]

                # Collect per-particle rows
                condition = fov_info.condition or "uncategorized"
                for r in results:
                    # Measure normalization channel mean inside this particle
                    norm_mean = ""
                    if norm_crop is not None:
                        p_mask = (particle_crop == r.particle_label) & cell_mask
                        if np.any(p_mask):
                            norm_mean = float(np.mean(
                                norm_crop[p_mask].astype(np.float64)
                            ))

                    rows_by_condition[condition].append({
                        "particle_id": r.particle_label,
                        "cell_id": r.cell_id,
                        "fov_id": fov_id,
                        "fov_name": fov_info.display_name,
                        "condition": condition,
                        "bio_rep": fov_info.bio_rep,
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

            if progress_callback:
                progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)

        # Export per-condition CSVs
        custom_outputs: dict[str, str] = {}
        if do_export_csv and rows_by_condition:
            csv_paths = self._export_csvs(store, rows_by_condition, meas_channel)
            for condition, path in csv_paths.items():
                custom_outputs[f"csv_{condition}"] = str(path)

        if particles_processed == 0:
            warnings.append("No particles found with valid background rings.")

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
        """Write per-particle results to one CSV per condition.

        Returns:
            Mapping of condition name to the CSV path written.
        """
        exports_dir = Path(store.path) / "exports"
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
