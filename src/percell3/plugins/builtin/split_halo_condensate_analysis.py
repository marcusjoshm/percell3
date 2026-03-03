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

GRANULE_CSV_COLUMNS = [
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

DILUTE_CSV_COLUMNS = [
    "cell_id",
    "fov_id",
    "fov_name",
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

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="split_halo_condensate_analysis",
            version="1.0.0",
            description="Split-Halo BiFC condensate analysis: granule + dilute phase measurements with derived FOV images",
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
                    "description": "Channel whose particle mask defines granules",
                },
                "exclusion_channel": {
                    "type": ["string", "null"],
                    "description": "Optional channel mask to exclude from background ring",
                    "default": None,
                },
                "ring_dilation_pixels": {
                    "type": "integer",
                    "description": "Dilation for granule background ring (pixels)",
                    "default": 5,
                },
                "exclusion_dilation_pixels": {
                    "type": "integer",
                    "description": "Dilation for dilute phase exclusion zone (pixels)",
                    "default": 5,
                },
                "max_background": {
                    "type": ["number", "null"],
                    "description": "Upper bound on background estimate",
                    "default": None,
                },
                "normalization_channel": {
                    "type": ["string", "null"],
                    "description": "Optional channel whose mean intensity inside each particle/dilute region is reported for normalization",
                    "default": None,
                },
                "export_csv": {
                    "type": "boolean",
                    "description": "Export per-particle and per-cell CSVs",
                    "default": True,
                },
                "save_images": {
                    "type": "boolean",
                    "description": "Create derived condensed/dilute phase FOVs",
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

        from percell3.plugins.builtin.bg_subtraction_core import (
            estimate_background_gaussian,
            process_particles_for_cell,
        )

        params = parameters or {}
        meas_channel = params["measurement_channel"]
        particle_channel = params["particle_channel"]
        exclusion_channel = params.get("exclusion_channel")
        ring_dilation_pixels = params.get("ring_dilation_pixels", 5)
        exclusion_dilation_pixels = params.get("exclusion_dilation_pixels", 5)
        max_background = params.get("max_background")
        normalization_channel = params.get("normalization_channel")
        do_export_csv = params.get("export_csv", True)
        do_save_images = params.get("save_images", True)

        # Find threshold run for particle channel
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

        # Collect rows grouped by condition
        granule_rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        dilute_rows_by_condition: dict[str, list[dict]] = defaultdict(list)
        particles_processed = 0
        cells_processed = 0
        dilute_cells_processed = 0
        warnings: list[str] = []

        # Pre-build existing derived FOV name→id map for overwrite on re-run
        existing_fov_map: dict[str, int] = {}
        if do_save_images:
            all_fovs = store.get_fovs()
            existing_fov_map = {f.display_name: f.id for f in all_fovs}

        exclusion_selem = disk(exclusion_dilation_pixels)

        for fov_idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            # Resolve per-FOV run IDs
            seg_runs = [
                s for s in store.get_segmentations(seg_type="cellular")
                if s.source_fov_id == fov_id
            ]
            seg_run_id = seg_runs[0].id if seg_runs else None
            fov_thr_runs = [tr for tr in particle_runs if tr.source_fov_id == fov_id]
            thr_run_id = fov_thr_runs[-1].id if fov_thr_runs else None

            if seg_run_id is None or thr_run_id is None:
                warnings.append(f"Skipped FOV {fov_id}: missing seg or threshold run")
                continue

            # Read images for this FOV
            try:
                cell_labels = store.read_labels(seg_run_id)
                particle_labels = store.read_particle_labels(thr_run_id)
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
                    excl_thr_runs = [
                        tr for tr in all_thresholds
                        if tr.source_channel == exclusion_channel and tr.source_fov_id == fov_id
                    ]
                    if excl_thr_runs:
                        excl_raw = store.read_mask(excl_thr_runs[-1].id)
                        exclusion_mask = excl_raw > 0
                except Exception:
                    logger.debug(
                        "No exclusion mask for FOV %s channel %s, proceeding without",
                        fov_info.display_name, exclusion_channel,
                    )

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

            # Get cells for this FOV
            cells_df = store.get_cells(fov_id=fov_id)
            if cell_ids is not None:
                cells_df = cells_df[cells_df["id"].isin(cell_ids)]

            if cells_df.empty:
                if progress_callback:
                    progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)
                continue

            # Initialize full-FOV masks for derived image creation
            h, w = cell_labels.shape
            condensed_mask = np.zeros((h, w), dtype=bool)
            dilute_mask_full = np.zeros((h, w), dtype=bool)

            condition = fov_info.condition or "uncategorized"

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

                # --- Granule measurement (per-particle) ---
                results = process_particles_for_cell(
                    cell_id=cell_id,
                    cell_mask=cell_mask,
                    particle_labels=particle_crop,
                    measurement_image=meas_crop,
                    exclusion_mask=excl_crop,
                    dilation_pixels=ring_dilation_pixels,
                    max_background=max_background,
                )

                if results:
                    cells_processed += 1

                    # Crop normalization image to cell bbox if available
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

                        granule_rows_by_condition[condition].append({
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

                    # Measure normalization channel mean in dilute region
                    dilute_norm_mean = ""
                    if norm_image is not None:
                        norm_crop_dilute = norm_image[by:by + bh, bx:bx + bw]
                        if np.any(dilute_mask):
                            dilute_norm_mean = float(np.mean(
                                norm_crop_dilute[dilute_mask].astype(np.float64)
                            ))

                    dilute_rows_by_condition[condition].append({
                        "cell_id": cell_id,
                        "fov_id": fov_id,
                        "fov_name": fov_info.display_name,
                        "condition": condition,
                        "bio_rep": fov_info.bio_rep,
                        "dilute_area_pixels": dilute_pixels,
                        "raw_mean_intensity": raw_mean,
                        "raw_integrated_intensity": raw_integrated,
                        "bg_estimate": bg_value,
                        "bg_sub_mean_intensity": bg_sub_mean,
                        "bg_sub_integrated_intensity": bg_sub_integrated,
                        "norm_mean_intensity": dilute_norm_mean,
                    })
                    dilute_cells_processed += 1

                # --- Accumulate full-FOV masks ---
                condensed_mask[by:by + bh, bx:bx + bw] |= all_particles_mask
                dilute_mask_full[by:by + bh, bx:bx + bw] |= dilute_mask

            # --- Derived FOV creation (per FOV) ---
            if do_save_images:
                self._create_derived_fovs(
                    store, fov_id, fov_info, condensed_mask, dilute_mask_full,
                    existing_fov_map, warnings,
                )

            if progress_callback:
                progress_callback(fov_idx + 1, len(fov_ids), fov_info.display_name)

        # Export CSVs
        custom_outputs: dict[str, str] = {}
        if do_export_csv:
            if granule_rows_by_condition:
                granule_paths = self._export_csvs(
                    store, granule_rows_by_condition, meas_channel, "granule",
                )
                for cond, path in granule_paths.items():
                    custom_outputs[f"csv_granule_{cond}"] = str(path)

            if dilute_rows_by_condition:
                dilute_paths = self._export_csvs(
                    store, dilute_rows_by_condition, meas_channel, "dilute",
                )
                for cond, path in dilute_paths.items():
                    custom_outputs[f"csv_dilute_{cond}"] = str(path)

        if particles_processed == 0:
            warnings.append("No particles found with valid background rings.")

        return PluginResult(
            measurements_written=particles_processed,
            cells_processed=cells_processed + dilute_cells_processed,
            custom_outputs=custom_outputs,
            warnings=warnings,
        )

    def _create_derived_fovs(
        self,
        store: ExperimentStore,
        fov_id: int,
        fov_info: Any,
        condensed_mask: np.ndarray,
        dilute_mask: np.ndarray,
        existing_fov_map: dict[str, int],
        warnings: list[str],
    ) -> None:
        """Create or overwrite condensed_phase and dilute_phase derived FOVs."""
        channels = store.get_channels()

        for prefix, mask in [
            ("condensed_phase", condensed_mask),
            ("dilute_phase", dilute_mask),
        ]:
            derived_name = f"{prefix}_{fov_info.display_name}"

            if derived_name in existing_fov_map:
                # Overwrite existing derived FOV images
                derived_fov_id = existing_fov_map[derived_name]
            else:
                derived_fov_id = store.add_fov(
                    condition=fov_info.condition,
                    bio_rep=fov_info.bio_rep,
                    display_name=derived_name,
                    width=fov_info.width,
                    height=fov_info.height,
                    pixel_size_um=fov_info.pixel_size_um,
                )
                existing_fov_map[derived_name] = derived_fov_id

            for ch in channels:
                try:
                    ch_image = store.read_image_numpy(fov_id, ch.name)
                    masked = np.where(mask, ch_image, 0).astype(ch_image.dtype)
                    store.write_image(derived_fov_id, ch.name, masked)
                except Exception as exc:
                    logger.warning(
                        "Failed to write channel '%s' for derived FOV '%s': %s",
                        ch.name, derived_name, exc,
                    )

    def _export_csvs(
        self,
        store: ExperimentStore,
        rows_by_condition: dict[str, list[dict]],
        meas_channel: str,
        measurement_type: str,
    ) -> dict[str, Path]:
        """Write measurement results to one CSV per condition.

        Args:
            measurement_type: "granule" or "dilute" — controls filename and columns.
        """
        exports_dir = Path(store.path) / "exports"
        exports_dir.mkdir(exist_ok=True)

        columns = GRANULE_CSV_COLUMNS if measurement_type == "granule" else DILUTE_CSV_COLUMNS
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: dict[str, Path] = {}

        for condition, rows in sorted(rows_by_condition.items()):
            safe_condition = condition.replace(" ", "_").replace("/", "_")
            filename = f"condensate_{measurement_type}_{meas_channel}_{safe_condition}_{timestamp}.csv"
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
