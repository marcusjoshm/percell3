"""Import pre-existing label images and Cellpose _seg.npy files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from percell3.core import ExperimentStore
from percell3.segment.label_processor import LabelProcessor


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
        # Validate dtype
        if not np.issubdtype(labels.dtype, np.integer):
            raise ValueError(
                f"Labels must have integer dtype, got {labels.dtype}. "
                "Cast to int32 before importing."
            )

        # Validate shape
        if labels.ndim != 2:
            raise ValueError(
                f"Labels must be 2D, got {labels.ndim}D with shape {labels.shape}"
            )

        # Cast to int32 if needed
        labels_int32 = labels.astype(np.int32)

        # Validate region exists BEFORE any DB/Zarr writes
        region_info = store.get_regions(condition=condition)
        target_region = None
        for r in region_info:
            if r.name == region:
                target_region = r
                break

        if target_region is None:
            raise ValueError(f"Region {region!r} not found in condition {condition!r}")

        # Create segmentation run
        run_id = store.add_segmentation_run(
            channel, source, {"source": source, "imported": True}
        )

        # Write labels to zarr
        store.write_labels(region, condition, labels_int32, run_id, timepoint)

        # Extract cells and insert
        processor = LabelProcessor()

        cells = processor.extract_cells(
            labels_int32,
            target_region.id,
            run_id,
            target_region.pixel_size_um,
        )

        if cells:
            store.add_cells(cells)

        # Update cell count
        store.update_segmentation_run_cell_count(run_id, len(cells))

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

        # Load _seg.npy (allow_pickle required for Cellpose format)
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

        masks = seg_data["masks"]

        # Validate region exists BEFORE any DB/Zarr writes
        region_info = store.get_regions(condition=condition)
        target_region = None
        for r in region_info:
            if r.name == region:
                target_region = r
                break

        if target_region is None:
            raise ValueError(f"Region {region!r} not found in condition {condition!r}")

        # Build parameters from seg_data metadata
        params: dict = {"source": "cellpose-gui", "imported": True}
        if "est_diam" in seg_data:
            params["diameter"] = float(seg_data["est_diam"])
        if "model_path" in seg_data:
            params["model_path"] = str(seg_data["model_path"])

        # Create segmentation run with captured parameters
        run_id = store.add_segmentation_run(
            channel, "cellpose-gui", params
        )

        # Validate and cast masks
        if not np.issubdtype(masks.dtype, np.integer):
            masks = masks.astype(np.int32)
        else:
            masks = masks.astype(np.int32)

        # Write labels
        store.write_labels(region, condition, masks, run_id, timepoint)

        # Extract cells
        processor = LabelProcessor()

        cells = processor.extract_cells(
            masks,
            target_region.id,
            run_id,
            target_region.pixel_size_um,
        )

        if cells:
            store.add_cells(cells)

        store.update_segmentation_run_cell_count(run_id, len(cells))

        return run_id
