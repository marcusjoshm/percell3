"""Threshold-Layer Background Subtraction Plugin (single-derived-FOV approach).

For each source FOV, creates ONE derived FOV where:
- Each cell's pixels are subtracted by its intensity group's background value
- Background is estimated from dilute-phase pixels (inside ROI bboxes, outside masks)
- Pixels outside all ROIs are set to NaN
- Output dtype is float32 with NaN fill semantics

Replaces the old multi-derived-FOV approach (one per intensity group).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from percell4.plugins.base import AnalysisPlugin, PluginResult

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


class ThresholdBGSubtractionPlugin(AnalysisPlugin):
    """Per-group background subtraction with single derived FOV output.

    Algorithm:
    1. For each source FOV, get cells and their intensity group assignments.
    2. For each group, estimate background from dilute-phase pixels
       (inside cell bboxes but outside cell masks in the label image).
    3. Create a single derived FOV: each cell subtracted by its group's BG,
       NaN outside all ROIs.
    4. Derived FOV preserves cell_identity_id references.
    """

    name = "threshold_bg_subtraction"
    description = (
        "Per-group histogram-based background subtraction "
        "(single derived FOV, NaN outside ROIs)"
    )

    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        from percell4.core.db_types import uuid_to_hex
        from percell4.plugins.peak_detection import render_peak_histogram
        from percell4.plugins.threshold_bg_subtraction_core import (
            CellBGInfo,
            build_derived_image,
            estimate_group_background,
        )

        channel: str = kwargs.get("channel", "")
        if not channel:
            raise RuntimeError("'channel' parameter is required.")

        # Resolve channel info
        exp = store.db.get_experiment()
        exp_id = exp["id"]
        all_channels = store.db.get_channels(exp_id)
        channel_index_by_name = {
            ch["name"]: idx for idx, ch in enumerate(all_channels)
        }
        if channel not in channel_index_by_name:
            raise RuntimeError(f"Channel '{channel}' not found in experiment.")
        target_ch_idx = channel_index_by_name[channel]

        # Get intensity groups
        all_groups = store.db.get_intensity_groups(exp_id)
        if not all_groups:
            raise RuntimeError(
                "No intensity groups found. "
                "Run 'Grouped intensity thresholding' first."
            )

        # Build group lookup: group_id -> group row
        group_by_id = {g["id"]: g for g in all_groups}

        # Prepare histogram export directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        histograms_dir = store.root / "exports" / "bgsub_histograms"
        histograms_dir.mkdir(parents=True, exist_ok=True)

        derived_count = 0
        errors: list[str] = []

        for fov_idx, fov_id in enumerate(fov_ids):
            fov = store.db.get_fov(fov_id)
            if fov is None:
                errors.append(f"FOV index {fov_idx}: not found")
                continue

            fov_hex = uuid_to_hex(fov_id)
            fov_name = fov["auto_name"] or "unknown"

            # Read target channel image
            try:
                image = store.layers.read_image_channel_numpy(
                    fov_hex, target_ch_idx
                )
            except Exception as exc:
                errors.append(f"FOV {fov_name}: cannot read channel: {exc}")
                continue

            # Get cells (top-level ROIs) for this FOV
            cells = store.db.get_cells(fov_id)
            if not cells:
                errors.append(f"FOV {fov_name}: no cells, skipping")
                continue

            # Get active segmentation to read label image
            active = store.db.get_active_assignments(fov_id)
            seg_assigns = active.get("segmentation", [])
            if not seg_assigns:
                errors.append(
                    f"FOV {fov_name}: no segmentation assignment, skipping"
                )
                continue

            seg_set_id = seg_assigns[0]["segmentation_set_id"]
            seg_set_hex = uuid_to_hex(seg_set_id)

            try:
                label_image = store.layers.read_labels(seg_set_hex, fov_hex)
            except Exception as exc:
                errors.append(
                    f"FOV {fov_name}: cannot read labels: {exc}"
                )
                continue

            # Get cell group assignments: roi_id -> group info
            roi_to_group = self._get_roi_group_map(store, cells, group_by_id)

            if not roi_to_group:
                errors.append(
                    f"FOV {fov_name}: no cells have group assignments, "
                    f"skipping"
                )
                continue

            # Group cells by intensity group
            groups_to_cells: dict[bytes, list[dict]] = {}
            for cell in cells:
                group_info = roi_to_group.get(cell["id"])
                if group_info is not None:
                    gid = group_info["group_id"]
                    groups_to_cells.setdefault(gid, []).append(cell)

            # Estimate background per group
            group_bg_values: dict[bytes, float] = {}
            for gid, group_cells in groups_to_cells.items():
                group = group_by_id[gid]
                label_ids = [c["label_id"] for c in group_cells]
                bboxes = [
                    (c["bbox_y"], c["bbox_x"], c["bbox_h"], c["bbox_w"])
                    for c in group_cells
                ]

                bg_val = estimate_group_background(
                    image, label_image, label_ids, bboxes
                )
                group_bg_values[gid] = bg_val

                logger.info(
                    "FOV %s, group %s: BG = %.2f (%d cells)",
                    fov_name,
                    group["name"],
                    bg_val,
                    len(group_cells),
                )

            # Build CellBGInfo list for all cells with group assignments
            cell_bg_infos: list[CellBGInfo] = []
            for cell in cells:
                group_info = roi_to_group.get(cell["id"])
                if group_info is None:
                    continue
                gid = group_info["group_id"]
                group = group_by_id[gid]
                cell_bg_infos.append(
                    CellBGInfo(
                        label_id=cell["label_id"],
                        group_name=group["name"],
                        bg_value=group_bg_values[gid],
                        bbox=(
                            cell["bbox_y"],
                            cell["bbox_x"],
                            cell["bbox_h"],
                            cell["bbox_w"],
                        ),
                    )
                )

            # Build the derived image for the target channel
            derived_channel = build_derived_image(
                image, label_image, cell_bg_infos
            )

            # Build transform: replace target channel with derived,
            # convert all channels to float32 (NaN-safe)
            def make_transform(
                derived_ch: np.ndarray,
                ch_idx: int,
            ) -> Callable[
                [dict[int, np.ndarray]], dict[int, np.ndarray]
            ]:
                def transform_fn(
                    arrays: dict[int, np.ndarray],
                ) -> dict[int, np.ndarray]:
                    result = {}
                    for idx, arr in arrays.items():
                        if idx == ch_idx:
                            result[idx] = derived_ch
                        else:
                            result[idx] = arr.astype(np.float32)
                    return result

                return transform_fn

            # Collect bg_values for params
            params_bg = {
                group_by_id[gid]["name"]: bg_val
                for gid, bg_val in group_bg_values.items()
            }

            try:
                store.create_derived_fov(
                    source_fov_id=fov_id,
                    derivation_op="threshold_bg_subtraction",
                    params={
                        "channel": channel,
                        "bg_values": params_bg,
                    },
                    transform_fn=make_transform(
                        derived_channel, target_ch_idx
                    ),
                )
                derived_count += 1
            except Exception as exc:
                errors.append(
                    f"FOV {fov_name}: failed to create derived FOV: {exc}"
                )
                continue

            # Save diagnostic histograms (one per group)
            for gid, bg_val in group_bg_values.items():
                group = group_by_id[gid]
                try:
                    from percell4.plugins.peak_detection import (
                        find_gaussian_peaks,
                    )

                    # Re-collect dilute pixels for histogram rendering
                    group_cells = groups_to_cells[gid]
                    dilute_pixels = self._collect_dilute_pixels(
                        image, label_image, group_cells
                    )
                    if len(dilute_pixels) > 0:
                        peak_result = find_gaussian_peaks(dilute_pixels)
                        if peak_result is not None:
                            hist_title = (
                                f"{fov_name} / {group['name']} / {channel}"
                            )
                            safe_name = (
                                f"{fov_name}_{group['name']}"
                                f"_{channel}_{timestamp}.png"
                            )
                            hist_path = histograms_dir / safe_name
                            render_peak_histogram(
                                peak_result, hist_title, hist_path
                            )
                except Exception as exc:
                    logger.warning(
                        "Failed to save histogram for group %s: %s",
                        group["name"],
                        exc,
                    )

            if on_progress:
                on_progress(fov_idx + 1, len(fov_ids), fov_name)

        return PluginResult(
            fovs_processed=len(fov_ids),
            derived_fovs_created=derived_count,
            errors=errors,
        )

    @staticmethod
    def _get_roi_group_map(
        store: ExperimentStore,
        cells: list,
        group_by_id: dict[bytes, Any],
    ) -> dict[bytes, dict[str, Any]]:
        """Build mapping from roi_id to group info.

        Returns:
            Dict mapping roi_id -> {"group_id": bytes, "group_name": str}.
        """
        roi_ids = [c["id"] for c in cells]
        if not roi_ids:
            return {}

        # Query cell_group_assignments for these ROIs
        placeholders = ",".join("?" for _ in roi_ids)
        rows = store.db.connection.execute(
            f"SELECT cga.roi_id, cga.intensity_group_id "
            f"FROM cell_group_assignments cga "
            f"WHERE cga.roi_id IN ({placeholders})",
            roi_ids,
        ).fetchall()

        result: dict[bytes, dict[str, Any]] = {}
        for row in rows:
            gid = row["intensity_group_id"]
            if gid in group_by_id:
                result[row["roi_id"]] = {
                    "group_id": gid,
                    "group_name": group_by_id[gid]["name"],
                }
        return result

    @staticmethod
    def _collect_dilute_pixels(
        image: np.ndarray,
        label_image: np.ndarray,
        cells: list,
    ) -> np.ndarray:
        """Collect dilute-phase pixels for diagnostic histogram.

        Returns 1D array of pixel values from inside cell bboxes
        but outside cell masks.
        """
        dilute_pixels: list[np.ndarray] = []
        for cell in cells:
            by = cell["bbox_y"]
            bx = cell["bbox_x"]
            bh = cell["bbox_h"]
            bw = cell["bbox_w"]

            roi_image = image[by : by + bh, bx : bx + bw]
            roi_labels = label_image[by : by + bh, bx : bx + bw]
            dilute_mask = roi_labels == 0
            pixels = roi_image[dilute_mask]
            if len(pixels) > 0:
                dilute_pixels.append(pixels)

        if dilute_pixels:
            return np.concatenate(dilute_pixels)
        return np.array([], dtype=image.dtype)
