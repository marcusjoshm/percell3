"""Zarr I/O layer for PerCell 4.

LayerStore handles all Zarr read/write operations with staging-based atomic
writes, path validation, and OME-NGFF 0.4 metadata. It knows nothing about
SQLite, UUIDs, or FOV domain objects — it operates purely on hex string IDs
and numpy/dask arrays.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Callable

import dask.array as da
import numpy as np
import zarr
from numcodecs import Blosc, Zstd

from percell4.core.exceptions import PathTraversalError

logger = logging.getLogger(__name__)


class LayerStore:
    """Zarr I/O layer. Knows nothing about SQLite, UUIDs, or FOVs."""

    # Compression presets
    IMAGE_COMPRESSOR = Blosc(cname="lz4", clevel=5, shuffle=Blosc.BITSHUFFLE)
    LABEL_COMPRESSOR = Blosc(cname="lz4", clevel=5, shuffle=Blosc.BITSHUFFLE)
    MASK_COMPRESSOR = Zstd(level=3)

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._zarr_root = self._root / "zarr"

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def init_store(cls, root: Path) -> LayerStore:
        """Create .percell directory structure and return LayerStore."""
        root = Path(root)
        zarr_root = root / "zarr"
        for subdir in ("images", "segmentations", "masks", ".pending"):
            (zarr_root / subdir).mkdir(parents=True, exist_ok=True)
        # Same-volume validation
        pending = zarr_root / ".pending"
        images = zarr_root / "images"
        assert pending.stat().st_dev == images.stat().st_dev, (
            "Staging and final directories must be on the same filesystem volume"
        )
        return cls(root)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _staging_path(self, hex_id: str) -> Path:
        """Return staging path for an in-progress write."""
        return self._zarr_root / ".pending" / hex_id

    def _validate_path(self, rel_path: str) -> Path:
        """Resolve full path and ensure it does not escape the root.

        Args:
            rel_path: A relative path within the experiment directory.

        Returns:
            The resolved absolute Path.

        Raises:
            PathTraversalError: If the resolved path is outside self._root.
        """
        full = (self._root / rel_path).resolve()
        try:
            full.relative_to(self._root)
        except ValueError:
            raise PathTraversalError(
                f"Path '{rel_path}' resolves outside experiment root"
            )
        return full

    def _commit_staging(self, hex_id: str, final_path: Path) -> None:
        """Atomically move a staging directory to its final location.

        Args:
            hex_id: The hex identifier used as the staging directory name.
            final_path: The target path for the committed data.
        """
        staging = self._staging_path(hex_id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(final_path)
        assert final_path.exists(), "Atomic rename failed"

    def _retry_io(
        self,
        fn: Callable[[], None],
        max_attempts: int = 3,
        delay: float = 0.1,
    ) -> None:
        """Retry an I/O operation with exponential back-off.

        Args:
            fn: A callable to execute (should take no arguments).
            max_attempts: Maximum number of attempts.
            delay: Initial delay between retries in seconds.
        """
        for attempt in range(max_attempts):
            try:
                fn()
                return
            except OSError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(delay * (2 ** attempt))

    # ------------------------------------------------------------------
    # Image I/O
    # ------------------------------------------------------------------

    def write_image_channels(
        self,
        fov_hex: str,
        channel_arrays: dict[int, np.ndarray],
        chunks: tuple[int, ...] | None = None,
        pixel_size_um: float | None = None,
    ) -> str:
        """Write image channels to Zarr with OME-NGFF 0.4 metadata.

        When *pixel_size_um* is provided, the multiscales metadata includes
        physical scale transforms and axis units in micrometers.

        Args:
            fov_hex: Hex string identifier for the FOV.
            channel_arrays: Mapping of channel index to 2D numpy array.
            chunks: Chunk shape for storage. Defaults to array shape.
            pixel_size_um: Optional pixel size in micrometers for
                OME-NGFF coordinate transforms.

        Returns:
            Relative path to the image group (e.g. ``"zarr/images/{fov_hex}"``).
        """
        staging = self._staging_path(fov_hex)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        group = zarr.open_group(str(staging), mode="w")

        for channel_index, array in channel_arrays.items():
            ch_chunks = chunks if chunks is not None else array.shape
            group.array(
                str(channel_index),
                data=array,
                chunks=ch_chunks,
                compressor=self.IMAGE_COMPRESSOR,
                overwrite=True,
            )

        # Write OME-NGFF 0.4 multiscales metadata
        if pixel_size_um:
            axes = [
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ]
            transforms = [
                [{"type": "scale", "scale": [pixel_size_um, pixel_size_um]}]
            ]
            datasets = [
                {"path": str(idx), "coordinateTransformations": transforms[0]}
                for idx in sorted(channel_arrays.keys())
            ]
        else:
            axes = [
                {"name": "y", "type": "space"},
                {"name": "x", "type": "space"},
            ]
            datasets = [
                {"path": str(idx)}
                for idx in sorted(channel_arrays.keys())
            ]

        multiscales = [
            {
                "version": "0.4",
                "axes": axes,
                "datasets": datasets,
                "name": fov_hex,
            }
        ]
        group.attrs["multiscales"] = multiscales

        final_path = self._zarr_root / "images" / fov_hex
        self._commit_staging(fov_hex, final_path)

        return f"zarr/images/{fov_hex}"

    def read_image_channel(self, fov_hex: str, channel_index: int) -> da.Array:
        """Read a single channel as a lazy dask array.

        Args:
            fov_hex: Hex string identifier for the FOV.
            channel_index: Index of the channel to read.

        Returns:
            Lazy dask array for the channel.
        """
        path = self._zarr_root / "images" / fov_hex / str(channel_index)
        arr = zarr.open(str(path), mode="r")
        return da.from_zarr(arr)

    def read_image_channel_numpy(
        self, fov_hex: str, channel_index: int
    ) -> np.ndarray:
        """Read a single channel fully into memory.

        Args:
            fov_hex: Hex string identifier for the FOV.
            channel_index: Index of the channel to read.

        Returns:
            2D numpy array.
        """
        path = self._zarr_root / "images" / fov_hex / str(channel_index)
        zarr_array = zarr.open(str(path), mode="r")
        return zarr_array[:]

    # ------------------------------------------------------------------
    # Label I/O
    # ------------------------------------------------------------------

    def write_labels(
        self, seg_set_hex: str, fov_hex: str, labels: np.ndarray
    ) -> str:
        """Write a label image for a segmentation set and FOV.

        Args:
            seg_set_hex: Hex identifier for the segmentation set.
            fov_hex: Hex identifier for the FOV.
            labels: 2D integer label array.

        Returns:
            Relative path to the label group.
        """
        path = self._zarr_root / "segmentations" / seg_set_hex / fov_hex
        path.mkdir(parents=True, exist_ok=True)
        zarr.save_array(
            str(path / "labels"),
            np.asarray(labels, dtype=np.int32),
            compressor=self.LABEL_COMPRESSOR,
        )
        return f"zarr/segmentations/{seg_set_hex}/{fov_hex}"

    def read_labels(self, seg_set_hex: str, fov_hex: str) -> np.ndarray:
        """Read a label image from a segmentation set and FOV.

        Args:
            seg_set_hex: Hex identifier for the segmentation set.
            fov_hex: Hex identifier for the FOV.

        Returns:
            2D integer label array.
        """
        path = self._zarr_root / "segmentations" / seg_set_hex / fov_hex / "labels"
        return zarr.open(str(path), mode="r")[:]

    # ------------------------------------------------------------------
    # Mask I/O
    # ------------------------------------------------------------------

    def write_mask(self, mask_hex: str, mask: np.ndarray) -> str:
        """Write a binary mask.

        Args:
            mask_hex: Hex identifier for the mask.
            mask: 2D boolean or integer mask array.

        Returns:
            Relative path to the mask group.
        """
        path = self._zarr_root / "masks" / mask_hex
        path.mkdir(parents=True, exist_ok=True)
        zarr.save_array(
            str(path / "mask"),
            np.asarray(mask),
            compressor=self.MASK_COMPRESSOR,
        )
        return f"zarr/masks/{mask_hex}"

    def read_mask(self, mask_hex: str) -> np.ndarray:
        """Read a binary mask.

        Args:
            mask_hex: Hex identifier for the mask.

        Returns:
            2D mask array.
        """
        path = self._zarr_root / "masks" / mask_hex / "mask"
        return zarr.open(str(path), mode="r")[:]

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def delete_path(self, rel_path: str) -> None:
        """Delete a directory within the experiment root.

        Args:
            rel_path: Relative path to delete.

        Raises:
            PathTraversalError: If the path escapes the experiment root.
        """
        full_path = self._validate_path(rel_path)
        self._retry_io(lambda: shutil.rmtree(full_path))

    def validate_zarr_group(self, rel_path: str) -> bool:
        """Check whether a relative path contains a valid Zarr group or array.

        Args:
            rel_path: Relative path within the experiment root.

        Returns:
            True if the path is a valid Zarr group/array, False otherwise.
        """
        full_path = self._root / rel_path
        if not full_path.exists():
            return False
        # Check for zarr metadata files
        has_meta = (full_path / ".zarray").exists() or (
            full_path / ".zgroup"
        ).exists()
        if not has_meta:
            return False
        try:
            zarr.open(str(full_path), mode="r")
            return True
        except Exception:
            return False

    def cleanup_pending(self, max_age_seconds: float = 300.0) -> list[str]:
        """Remove stale entries from the staging directory.

        Args:
            max_age_seconds: Maximum age in seconds before an entry is removed.

        Returns:
            List of removed entry names.
        """
        pending_dir = self._zarr_root / ".pending"
        if not pending_dir.exists():
            return []
        removed: list[str] = []
        now = time.time()
        for entry in pending_dir.iterdir():
            mtime = entry.stat().st_mtime
            if now - mtime > max_age_seconds:
                shutil.rmtree(entry)
                removed.append(entry.name)
        return removed
