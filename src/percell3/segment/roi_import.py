"""Import pre-existing label images and Cellpose _seg.npy files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, FovInfo
from percell3.segment.label_processor import LabelProcessor


def _validate_fov(
    store: ExperimentStore, fov: str, condition: str,
) -> FovInfo:
    """Look up a FOV by name, raising ValueError if not found."""
    fov_list = store.get_fovs(condition=condition)
    for f in fov_list:
        if f.name == fov:
            return f
    raise ValueError(f"FOV {fov!r} not found in condition {condition!r}")


def _store_labels_and_cells(
    store: ExperimentStore,
    labels: np.ndarray,
    fov_info: FovInfo,
    fov: str,
    condition: str,
    run_id: int,
    timepoint: str | None,
) -> None:
    """Write labels to zarr, extract cells, insert into DB, update run count."""
    store.write_labels(fov, condition, labels, run_id, timepoint)

    processor = LabelProcessor()
    cells = processor.extract_cells(
        labels, fov_info.id, run_id, fov_info.pixel_size_um,
    )
    if cells:
        store.add_cells(cells)

    store.update_segmentation_run_cell_count(run_id, len(cells))


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
        fov: str,
        condition: str,
        channel: str = "manual",
        source: str = "manual",
        timepoint: str | None = None,
    ) -> int:
        """Import a pre-computed label image.

        Args:
            labels: 2D integer array where pixel value = cell ID, 0 = background.
            store: Target ExperimentStore.
            fov: FOV name.
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

        target_fov = _validate_fov(store, fov, condition)

        run_id = store.add_segmentation_run(
            channel, source, {"source": source, "imported": True}
        )

        _store_labels_and_cells(
            store, labels_int32, target_fov, fov, condition, run_id, timepoint,
        )
        return run_id

    def import_cellpose_seg(
        self,
        seg_path: Path,
        store: ExperimentStore,
        fov: str,
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
            fov: FOV name.
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

        target_fov = _validate_fov(store, fov, condition)

        params: dict = {"source": "cellpose-gui", "imported": True}
        if "est_diam" in seg_data:
            params["diameter"] = float(seg_data["est_diam"])
        if "model_path" in seg_data:
            params["model_path"] = str(seg_data["model_path"])

        run_id = store.add_segmentation_run(channel, "cellpose-gui", params)

        _store_labels_and_cells(
            store, masks, target_fov, fov, condition, run_id, timepoint,
        )
        return run_id
