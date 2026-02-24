"""Local Background Subtraction Plugin — per-particle local BG estimation.

Uses Gaussian peak detection on a dilated ring around each particle to estimate
and subtract the local background from measurement channel intensities.

This is the PerCell 3 port of the m7G Cap Enrichment Analysis algorithm,
made channel-agnostic and universal.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)

# Metrics written to the measurements table (cell-level aggregates)
BG_SUB_METRICS = [
    "bg_sub_mean_intensity",
    "bg_sub_integrated_intensity",
    "bg_estimate",
    "bg_sub_particle_count",
]

# CSV export column order
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

        Parameters dict keys:
            measurement_channel: Channel name for intensity measurement.
            particle_channel: Channel whose particle labels to use.
            exclusion_channel: Optional channel mask to exclude from ring.
            dilation_pixels: Ring dilation (default 5).
            max_background: Upper bound on BG estimate (default None).
            export_csv: Whether to export per-particle CSV (default True).
        """
        from percell3.core.models import MeasurementRecord
        from percell3.plugins.builtin.bg_subtraction_core import process_particles_for_cell

        params = parameters or {}
        meas_channel = params["measurement_channel"]
        particle_channel = params["particle_channel"]
        exclusion_channel = params.get("exclusion_channel")
        dilation_pixels = params.get("dilation_pixels", 5)
        max_background = params.get("max_background")
        do_export_csv = params.get("export_csv", True)

        # Resolve channel IDs
        meas_ch_info = store.get_channel(meas_channel)

        # Find the most recent threshold run for the particle channel
        threshold_runs = store.get_threshold_runs()
        particle_runs = [
            tr for tr in threshold_runs if tr["channel"] == particle_channel
        ]
        if not particle_runs:
            raise RuntimeError(
                f"No threshold run found for channel '{particle_channel}'. "
                "Run 'Apply threshold' first to generate particle masks."
            )
        threshold_run_id = particle_runs[-1]["id"]  # most recent

        # Determine FOVs to process
        if cell_ids is not None:
            # Get FOV IDs from the given cell_ids
            cells_df = store.get_cells()
            cells_df = cells_df[cells_df["id"].isin(cell_ids)]
            fov_ids = sorted(cells_df["fov_id"].unique().tolist())
        else:
            fovs = store.get_fovs()
            fov_ids = [f.id for f in fovs]

        # Collect per-particle rows for CSV export
        csv_rows: list[dict] = []
        all_measurements: list[MeasurementRecord] = []
        cells_processed = 0
        warnings: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            # Read images for this FOV
            try:
                cell_labels = store.read_labels(fov_id)
                particle_labels = store.read_particle_labels(fov_id, particle_channel)
                measurement_image = store.read_image_numpy(fov_id, meas_channel)
            except Exception as exc:
                logger.warning(
                    "Skipping FOV %s: failed to read data: %s",
                    fov_info.display_name, exc,
                )
                warnings.append(f"Skipped FOV {fov_info.display_name}: {exc}")
                continue

            # Read exclusion mask if specified
            exclusion_mask = None
            if exclusion_channel:
                try:
                    excl_raw = store.read_mask(fov_id, exclusion_channel)
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

                # Aggregate per-cell: weighted by particle area
                valid_results = [r for r in results if not np.isnan(r.bg_estimate)]

                if valid_results:
                    total_area = sum(r.area_pixels for r in valid_results)
                    if total_area > 0:
                        cell_bg_estimate = sum(
                            r.bg_estimate * r.area_pixels for r in valid_results
                        ) / total_area
                        cell_bg_sub_mean = sum(
                            r.bg_sub_mean_intensity * r.area_pixels for r in valid_results
                        ) / total_area
                    else:
                        cell_bg_estimate = 0.0
                        cell_bg_sub_mean = 0.0
                    cell_bg_sub_integrated = sum(
                        r.bg_sub_integrated_intensity for r in valid_results
                    )
                    cell_particle_count = float(len(valid_results))
                else:
                    cell_bg_estimate = float("nan")
                    cell_bg_sub_mean = float("nan")
                    cell_bg_sub_integrated = float("nan")
                    cell_particle_count = 0.0

                all_measurements.extend([
                    MeasurementRecord(
                        cell_id=cell_id,
                        channel_id=meas_ch_info.id,
                        metric="bg_sub_mean_intensity",
                        value=cell_bg_sub_mean,
                        scope="whole_cell",
                    ),
                    MeasurementRecord(
                        cell_id=cell_id,
                        channel_id=meas_ch_info.id,
                        metric="bg_sub_integrated_intensity",
                        value=cell_bg_sub_integrated,
                        scope="whole_cell",
                    ),
                    MeasurementRecord(
                        cell_id=cell_id,
                        channel_id=meas_ch_info.id,
                        metric="bg_estimate",
                        value=cell_bg_estimate,
                        scope="whole_cell",
                    ),
                    MeasurementRecord(
                        cell_id=cell_id,
                        channel_id=meas_ch_info.id,
                        metric="bg_sub_particle_count",
                        value=cell_particle_count,
                        scope="whole_cell",
                    ),
                ])

                # Collect per-particle CSV rows
                for r in results:
                    csv_rows.append({
                        "particle_id": r.particle_label,
                        "cell_id": r.cell_id,
                        "fov_id": fov_id,
                        "fov_name": fov_info.display_name,
                        "condition": fov_info.condition,
                        "bio_rep": fov_info.bio_rep,
                        "area_pixels": r.area_pixels,
                        "raw_mean_intensity": r.raw_mean_intensity,
                        "raw_integrated_intensity": r.raw_integrated_intensity,
                        "bg_estimate": r.bg_estimate,
                        "bg_ring_pixels": r.bg_ring_pixels,
                        "bg_sub_mean_intensity": r.bg_sub_mean_intensity,
                        "bg_sub_integrated_intensity": r.bg_sub_integrated_intensity,
                    })

                cells_processed += 1

            if progress_callback:
                progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)

        # Write cell-level measurements to store
        if all_measurements:
            store.add_measurements(all_measurements)

        # Export per-particle CSV
        custom_outputs: dict[str, str] = {}
        if do_export_csv and csv_rows:
            csv_path = self._export_csv(store, csv_rows, meas_channel)
            custom_outputs["csv"] = str(csv_path)

        if not csv_rows:
            warnings.append("No particles found with valid background rings.")

        return PluginResult(
            measurements_written=len(all_measurements),
            cells_processed=cells_processed,
            custom_outputs=custom_outputs,
            warnings=warnings,
        )

    def _export_csv(
        self,
        store: ExperimentStore,
        rows: list[dict],
        meas_channel: str,
    ) -> Path:
        """Write per-particle results to CSV in the experiment's exports directory."""
        exports_dir = Path(store.path) / "exports"
        exports_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bg_subtraction_{meas_channel}_{timestamp}.csv"
        csv_path = exports_dir / filename

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Exported per-particle CSV to %s (%d rows)", csv_path, len(rows))
        return csv_path
