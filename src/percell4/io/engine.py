"""ImportEngine — reads image files and writes them into an ExperimentStore.

Handles TIFF import with multi-channel support. Uses UUID-based IDs for
all FOV records and writes pixel data through the LayerStore.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex

logger = logging.getLogger(__name__)


class ImportEngine:
    """Import images into a PerCell 4 experiment.

    All images are read via ``percell4.io.tiff.read_tiff`` and written
    to the experiment's LayerStore with a new UUID-keyed FOV record in
    the database.
    """

    def import_images(
        self,
        store: "ExperimentStore",  # noqa: F821 — forward ref avoids circular import
        source_paths: list[Path],
        channel_mapping: dict[int, bytes],
        condition_id: bytes | None = None,
        bio_rep_id: bytes | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[bytes]:
        """Import image files as FOVs.

        Each source path becomes one FOV. Multi-channel TIFFs are split
        according to *channel_mapping* (channel index in file -> channel
        UUID in DB). Single-channel files use index 0.

        Args:
            store: Open ExperimentStore instance.
            source_paths: Paths to TIFF image files.
            channel_mapping: Maps channel index in the file to the
                channel UUID already registered in the database.
            condition_id: Optional condition UUID to assign to each FOV.
            bio_rep_id: Optional biological replicate UUID.
            on_progress: Optional callback ``(current, total, fov_name)``.

        Returns:
            List of created FOV IDs (16-byte UUIDs).

        Raises:
            FileNotFoundError: If a source path does not exist.
        """
        from percell4.core.experiment_store import ExperimentStore  # local import
        from percell4.io.tiff import read_tiff

        fov_ids: list[bytes] = []
        exp = store.get_experiment()
        total = len(source_paths)

        for i, path in enumerate(source_paths):
            fov_name = path.stem

            if on_progress:
                on_progress(i, total, fov_name)

            # Read image data
            image = read_tiff(path)

            # Build per-channel arrays
            if image.ndim == 3 and len(channel_mapping) > 1:
                # Multi-channel: first axis is channel
                channels: dict[int, np.ndarray] = {
                    idx: image[idx] for idx in channel_mapping if idx < image.shape[0]
                }
            else:
                # Single channel
                if image.ndim == 3:
                    channels = {0: image[0]}
                else:
                    channels = {0: image}

            # Create a UUID for the new FOV
            fov_id = new_uuid()
            fov_hex = uuid_to_hex(fov_id)

            # Write pixel data to LayerStore
            zarr_path = store.layers.write_image_channels(fov_hex, channels)

            # Insert FOV record in DB
            with store.transaction():
                store.db.insert_fov(
                    id=fov_id,
                    experiment_id=exp["id"],
                    condition_id=condition_id,
                    bio_rep_id=bio_rep_id,
                    auto_name=fov_name,
                    zarr_path=zarr_path,
                    status="pending",
                )
                store.db.set_fov_status(
                    fov_id,
                    FovStatus.imported,
                    f"Imported from {path.name}",
                )

            fov_ids.append(fov_id)

        return fov_ids
