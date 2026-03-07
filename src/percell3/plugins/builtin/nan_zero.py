"""NaN-Zero Plugin — replace zero-valued pixels with NaN in selected channels.

When measuring mean intensity in microscopy images, zero-valued pixels (from
background subtraction or masking) skew the mean downward.  Converting zeros
to NaN allows ``np.nanmean`` to exclude them.  Produces a derived FOV for
each input FOV with the selected channels converted to float32 and zeros
replaced by NaN.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from percell3.plugins.base import AnalysisPlugin, PluginInfo, PluginResult

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class NanZeroPlugin(AnalysisPlugin):
    """Replace zero-valued pixels with NaN in selected channels.

    For each source FOV a derived FOV is created.  Selected channels are
    cast to ``float32`` and every zero pixel is set to ``np.nan``.
    Unselected channels are copied unchanged.  The source FOV's
    ``fov_config`` entries (segmentation + threshold assignments) are
    duplicated onto the derived FOV, cells are copied, and measurements
    are automatically computed so the derived FOV is immediately exportable.
    """

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="nan_zero",
            version="1.0.0",
            description="Replace zero pixels with NaN in selected channels",
            author="PerCell Team",
        )

    def validate(self, store: ExperimentStore) -> list[str]:
        errors: list[str] = []
        if not store.get_channels():
            errors.append("No channels found in the experiment.")
        if not store.get_fovs():
            errors.append("No FOVs found in the experiment.")
        return errors

    def get_parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fov_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "FOV IDs to process",
                },
                "channels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Channel names in which to replace zeros with NaN",
                },
                "name_prefix": {
                    "type": "string",
                    "description": "Prefix for derived FOV names",
                    "default": "nan_zero",
                },
            },
            "required": ["fov_ids", "channels"],
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        if parameters is None:
            raise RuntimeError("Parameters are required for nan_zero.")

        fov_ids: list[int] = parameters["fov_ids"]
        target_channels: list[str] = parameters["channels"]
        name_prefix: str = parameters.get("name_prefix", "nan_zero")

        all_channels = store.get_channels()
        channel_names = {ch.name for ch in all_channels}
        for ch_name in target_channels:
            if ch_name not in channel_names:
                raise RuntimeError(f"Channel '{ch_name}' not found in experiment.")

        existing_fov_map = {f.display_name: f.id for f in store.get_fovs()}
        derived_fov_ids: list[int] = []
        total_measurements = 0

        for idx, fov_id in enumerate(fov_ids):
            fov_info = store.get_fov_by_id(fov_id)

            if progress_callback:
                progress_callback(idx, len(fov_ids), fov_info.display_name)

            derived_name = f"{name_prefix}_{fov_info.display_name}"

            # -- create or reuse derived FOV ------------------------------
            if derived_name in existing_fov_map:
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

            derived_fov_ids.append(derived_fov_id)

            # -- write channels -------------------------------------------
            # All channels are cast to float32 so the zarr array has a
            # uniform dtype that supports NaN values.
            for ch in all_channels:
                image = store.read_image_numpy(fov_id, ch.name)
                image = image.astype(np.float32)
                if ch.name in target_channels:
                    image[image == 0] = np.nan
                store.write_image(derived_fov_id, ch.name, image)

            # -- copy fov_config entries ----------------------------------
            source_config = store.get_fov_config(fov_id)
            for entry in source_config:
                try:
                    store.set_fov_config_entry(
                        derived_fov_id,
                        entry.segmentation_id,
                        entry.threshold_id,
                        entry.scopes,
                    )
                except ValueError:
                    logger.warning(
                        "Skipped config entry (seg=%d) for derived FOV %d: "
                        "dimension mismatch",
                        entry.segmentation_id,
                        derived_fov_id,
                    )

            # -- duplicate cells so the derived FOV is measurable ---------
            from percell3.core.models import CellRecord

            source_cells = store.get_cells(fov_id=fov_id, is_valid=False)
            if not source_cells.empty:
                existing_derived = store.get_cells(
                    fov_id=derived_fov_id, is_valid=False,
                )
                if existing_derived.empty:
                    records = [
                        CellRecord(
                            fov_id=derived_fov_id,
                            segmentation_id=int(row["segmentation_id"]),
                            label_value=int(row["label_value"]),
                            centroid_x=float(row["centroid_x"]),
                            centroid_y=float(row["centroid_y"]),
                            bbox_x=int(row["bbox_x"]),
                            bbox_y=int(row["bbox_y"]),
                            bbox_w=int(row["bbox_w"]),
                            bbox_h=int(row["bbox_h"]),
                            area_pixels=float(row["area_pixels"]),
                            area_um2=row.get("area_um2"),
                            perimeter=row.get("perimeter"),
                            circularity=row.get("circularity"),
                        )
                        for _, row in source_cells.iterrows()
                    ]
                    store.add_cells(records)

            # -- auto-measure the derived FOV -----------------------------
            total_measurements += self._measure_derived_fov(
                store, derived_fov_id, source_config,
            )

        if progress_callback:
            progress_callback(len(fov_ids), len(fov_ids), "Done")

        return PluginResult(
            measurements_written=total_measurements,
            cells_processed=0,
            custom_outputs={
                "derived_fov_ids": ", ".join(str(fid) for fid in derived_fov_ids),
                "fovs_processed": str(len(fov_ids)),
            },
        )

    @staticmethod
    def _measure_derived_fov(
        store: "ExperimentStore",
        fov_id: int,
        config: list,
    ) -> int:
        """Run whole_cell and masked measurements on the derived FOV."""
        from percell3.measure.measurer import Measurer

        channels = store.get_channels()
        if not channels:
            return 0

        channel_names = [ch.name for ch in channels]
        measurer = Measurer()
        total = 0

        for entry in config:
            try:
                # Whole-cell measurement
                count = measurer.measure_fov(
                    store, fov_id, channel_names, entry.segmentation_id,
                )
                total += count

                # Masked measurement (if threshold is configured)
                if entry.threshold_id is not None:
                    mask_scopes = [
                        s for s in entry.scopes
                        if s in ("mask_inside", "mask_outside")
                    ]
                    if mask_scopes:
                        count = measurer.measure_fov_masked(
                            store, fov_id, channel_names,
                            segmentation_id=entry.segmentation_id,
                            threshold_id=entry.threshold_id,
                            scopes=mask_scopes,
                        )
                        total += count
            except Exception:
                logger.exception(
                    "Auto-measurement failed for derived FOV %d, "
                    "segmentation %d",
                    fov_id, entry.segmentation_id,
                )

        return total
