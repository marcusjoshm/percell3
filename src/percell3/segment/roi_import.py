"""Import pre-existing label images and Cellpose _seg.npy files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, RegionInfo
from percell3.segment.label_processor import extract_cells


def _validate_region(
    store: ExperimentStore, region: str, condition: str,
) -> RegionInfo:
    """Look up a region by name, raising ValueError if not found."""
    region_info = store.get_regions(condition=condition)
    for r in region_info:
        if r.name == region:
            return r
    raise ValueError(f"Region {region!r} not found in condition {condition!r}")


def store_labels_and_cells(
    store: ExperimentStore,
    labels: np.ndarray,
    region: str,
    condition: str,
    run_id: int,
    region_id: int,
    pixel_size_um: float | None,
    timepoint: str | None = None,
) -> int:
    """Write labels to zarr, extract cells, insert into DB, update run count.

    This is the shared primitive used by both the napari viewer save-back
    and ``RoiImporter``. Callers are responsible for creating the
    segmentation run (``store.add_segmentation_run``) beforehand.

    Args:
        store: An open ExperimentStore.
        labels: 2D int32 label array.
        region: Region name.
        condition: Condition name.
        run_id: Segmentation run ID (already created).
        region_id: Database ID of the region.
        pixel_size_um: Physical pixel size in micrometers (or None).
        timepoint: Optional timepoint.

    Returns:
        Number of cells extracted and inserted.
    """
    store.write_labels(region, condition, labels, run_id, timepoint)

    cells = extract_cells(labels, region_id, run_id, pixel_size_um)
    if cells:
        store.add_cells(cells)

    store.update_segmentation_run_cell_count(run_id, len(cells))
    return len(cells)


class RoiImporter:
    """Import pre-computed label images into an ExperimentStore.

    Supports:
    - Direct numpy label arrays (integer masks)
    - Cellpose ``_seg.npy`` files (saved by Cellpose GUI)
    """

    def import_labels(
        self,
        labels: np.ndarray,
        store: ExperimentStore,
        region: str,
        condition: str,
        channel: str = "manual",
        source: str = "manual",
        timepoint: str | None = None,
    ) -> int:
        """Import a pre-computed label image.

        Args:
            labels: 2D integer array where pixel value = cell ID, 0 = background.
            store: Target ExperimentStore.
            region: Region name.
            condition: Condition name.
            channel: Channel name for segmentation run record.
            source: Source identifier (stored as model_name in segmentation run).
            timepoint: Optional timepoint.

        Returns:
            Segmentation run ID.

        Raises:
            ValueError: If labels is not 2D or has non-integer dtype.
        """
        if not np.issubdtype(labels.dtype, np.integer):
            raise ValueError(
                f"Labels must have integer dtype, got {labels.dtype}. "
                "Cast to int32 before importing."
            )
        if labels.ndim != 2:
            raise ValueError(
                f"Labels must be 2D, got {labels.ndim}D with shape {labels.shape}"
            )

        labels_int32 = np.asarray(labels, dtype=np.int32)

        target_region = _validate_region(store, region, condition)

        run_id = store.add_segmentation_run(
            channel, source, {"source": source, "imported": True}
        )

        store_labels_and_cells(
            store, labels_int32, region, condition, run_id,
            target_region.id, target_region.pixel_size_um, timepoint,
        )
        return run_id

    def import_cellpose_seg(
        self,
        seg_path: Path,
        store: ExperimentStore,
        region: str,
        condition: str,
        channel: str = "manual",
        timepoint: str | None = None,
    ) -> int:
        """Import a Cellpose ``_seg.npy`` file.

        .. warning::

            This uses ``np.load(allow_pickle=True)`` because the Cellpose
            ``_seg.npy`` format stores a pickled dictionary. Only load files
            from trusted sources — a malicious ``.npy`` file can execute
            arbitrary code during deserialization.

        Args:
            seg_path: Path to the ``_seg.npy`` file.
            store: Target ExperimentStore.
            region: Region name.
            condition: Condition name.
            channel: Channel name for segmentation run record.
            timepoint: Optional timepoint.

        Returns:
            Segmentation run ID.

        Raises:
            ValueError: If the file doesn't contain a "masks" key.
            FileNotFoundError: If the path doesn't exist.
        """
        seg_path = Path(seg_path)
        if not seg_path.exists():
            raise FileNotFoundError(f"Cellpose seg file not found: {seg_path}")

        seg_data = np.load(str(seg_path), allow_pickle=True).item()

        if not isinstance(seg_data, dict):
            raise ValueError(
                f"Expected dict from _seg.npy, got {type(seg_data).__name__}"
            )
        if "masks" not in seg_data:
            raise ValueError(
                f"Cellpose _seg.npy missing 'masks' key. "
                f"Available keys: {list(seg_data.keys())}"
            )

        masks = np.asarray(seg_data["masks"], dtype=np.int32)

        target_region = _validate_region(store, region, condition)

        params: dict = {"source": "cellpose-gui", "imported": True}
        if "est_diam" in seg_data:
            params["diameter"] = float(seg_data["est_diam"])
        if "model_path" in seg_data:
            params["model_path"] = str(seg_data["model_path"])

        run_id = store.add_segmentation_run(channel, "cellpose-gui", params)

        store_labels_and_cells(
            store, masks, region, condition, run_id,
            target_region.id, target_region.pixel_size_um, timepoint,
        )
        return run_id
