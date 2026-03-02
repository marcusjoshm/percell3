"""Import pre-existing label images and Cellpose _seg.npy files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from percell3.core import ExperimentStore
from percell3.core.models import FovInfo
from percell3.segment.label_processor import extract_cells


def store_labels_and_cells(
    store: ExperimentStore,
    labels: np.ndarray,
    fov_id: int,
    segmentation_id: int,
    pixel_size_um: float | None = None,
) -> int:
    """Write labels to zarr, extract cells, insert into DB, update seg count.

    This is the shared primitive used by both the napari viewer save-back
    and ``RoiImporter``. Callers are responsible for creating the
    segmentation entity (``store.add_segmentation``) beforehand.

    Args:
        store: An open ExperimentStore.
        labels: 2D int32 label array.
        fov_id: FOV database ID.
        segmentation_id: Segmentation entity ID (already created).
        pixel_size_um: Physical pixel size for area calculations.

    Returns:
        Number of cells extracted and inserted.
    """
    store.write_labels(labels, segmentation_id)

    # Delete old cells for this segmentation before inserting new ones
    store.delete_cells_for_fov(fov_id)

    cells = extract_cells(labels, fov_id, segmentation_id, pixel_size_um)
    if cells:
        store.add_cells(cells)

    store.update_segmentation_cell_count(segmentation_id, len(cells))
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
        fov_id: int,
        channel: str = "manual",
        source: str = "manual",
    ) -> int:
        """Import a pre-computed label image.

        Creates a global segmentation entity, writes labels to zarr,
        extracts cells, and triggers auto-measurement.

        Args:
            labels: 2D integer array where pixel value = cell ID, 0 = background.
            store: Target ExperimentStore.
            fov_id: FOV database ID.
            channel: Channel name for the segmentation.
            source: Source identifier (stored as model_name).

        Returns:
            Segmentation entity ID.

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
        fov_info = store.get_fov_by_id(fov_id)
        h, w = labels_int32.shape

        name = store._generate_segmentation_name(source, channel)
        seg_id = store.add_segmentation(
            name=name, seg_type="cellular",
            width=w, height=h,
            source_fov_id=fov_id, source_channel=channel,
            model_name=source,
            parameters={"source": source, "imported": True},
        )

        store_labels_and_cells(
            store, labels_int32, fov_id, seg_id, fov_info.pixel_size_um,
        )

        # Trigger auto-measurement
        from percell3.measure.auto_measure import on_segmentation_created
        on_segmentation_created(store, seg_id, [fov_id])

        return seg_id

    def import_cellpose_seg(
        self,
        seg_path: Path,
        store: ExperimentStore,
        fov_id: int,
        channel: str = "manual",
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
            fov_id: FOV database ID.
            channel: Channel name for the segmentation.

        Returns:
            Segmentation entity ID.

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
        fov_info = store.get_fov_by_id(fov_id)
        h, w = masks.shape

        params: dict = {"source": "cellpose-gui", "imported": True}
        if "est_diam" in seg_data:
            params["diameter"] = float(seg_data["est_diam"])
        if "model_path" in seg_data:
            params["model_path"] = str(seg_data["model_path"])

        name = store._generate_segmentation_name("cellpose-gui", channel)
        seg_id = store.add_segmentation(
            name=name, seg_type="cellular",
            width=w, height=h,
            source_fov_id=fov_id, source_channel=channel,
            model_name="cellpose-gui", parameters=params,
        )

        store_labels_and_cells(
            store, masks, fov_id, seg_id, fov_info.pixel_size_um,
        )

        # Trigger auto-measurement
        from percell3.measure.auto_measure import on_segmentation_created
        on_segmentation_created(store, seg_id, [fov_id])

        return seg_id
