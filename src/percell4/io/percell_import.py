"""Cross-project FOV import for PerCell 4.

Copies selected FOVs (and their channel images) from a source experiment
into a target experiment, generating fresh UUIDs for all entities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Summary of a cross-project import operation."""

    fovs_imported: int = 0
    channels_copied: int = 0
    rois_copied: int = 0
    warnings: list[str] = field(default_factory=list)


def import_fov_from_experiment(
    target: "ExperimentStore",  # noqa: F821
    source: "ExperimentStore",  # noqa: F821
    source_fov_id: bytes,
    target_condition_id: bytes | None = None,
) -> bytes:
    """Import an FOV from one experiment to another with new UUIDs.

    All IDs are remapped (new UUIDs generated). Channel images are copied
    from the source LayerStore to the target LayerStore.

    Args:
        target: Destination ExperimentStore (read-write).
        source: Source ExperimentStore (read-only usage).
        source_fov_id: UUID of the FOV in the source experiment.
        target_condition_id: Optional condition UUID in the target
            experiment to assign the new FOV to.

    Returns:
        The UUID of the newly created FOV in the target experiment.

    Raises:
        ValueError: If source and target are the same experiment directory.
        KeyError: If *source_fov_id* does not exist in the source.
    """
    from percell4.core.experiment_store import ExperimentStore  # local import

    # Guard: same-project import
    if source.root.resolve() == target.root.resolve():
        raise ValueError("Cannot import from the same experiment directory.")

    # Read source FOV record
    source_fov = source.db.get_fov(source_fov_id)
    if source_fov is None:
        raise KeyError(
            f"FOV {uuid_to_str(source_fov_id)} not found in source experiment"
        )

    # Get source experiment channels
    source_exp = source.get_experiment()
    target_exp = target.get_experiment()
    source_channels = source.db.get_channels(source_exp["id"])

    # Copy channel images from source to target
    new_fov_id = new_uuid()
    new_fov_hex = uuid_to_hex(new_fov_id)
    source_fov_hex = uuid_to_hex(source_fov_id)

    channel_arrays: dict[int, "np.ndarray"] = {}
    for idx in range(len(source_channels)):
        try:
            arr = source.layers.read_image_channel_numpy(source_fov_hex, idx)
            channel_arrays[idx] = arr
        except Exception:
            # Channel may not exist in zarr for this FOV
            continue

    # Write images to target LayerStore
    zarr_path = target.layers.write_image_channels(new_fov_hex, channel_arrays)

    # Build auto_name
    source_name = source_fov["auto_name"] or uuid_to_str(source_fov_id)[:8]

    # Insert FOV record in target DB
    with target.transaction():
        target.db.insert_fov(
            id=new_fov_id,
            experiment_id=target_exp["id"],
            condition_id=target_condition_id,
            auto_name=f"{source_name}_imported",
            zarr_path=zarr_path,
            status="pending",
        )
        target.db.set_fov_status(
            new_fov_id,
            FovStatus.imported,
            f"Imported from {source.root.name}",
        )

    # Copy top-level ROIs with new UUIDs
    source_cells = source.db.get_cells(source_fov_id)
    for cell in source_cells:
        new_roi_id = new_uuid()
        new_cell_identity_id = new_uuid()

        # Create cell identity in target
        target.db.insert_cell_identity(
            id=new_cell_identity_id,
            origin_fov_id=new_fov_id,
            roi_type_id=cell["roi_type_id"],
        )

        target.db.insert_roi(
            id=new_roi_id,
            fov_id=new_fov_id,
            roi_type_id=cell["roi_type_id"],
            cell_identity_id=new_cell_identity_id,
            parent_roi_id=None,
            label_id=cell["label_id"],
            bbox_y=cell["bbox_y"],
            bbox_x=cell["bbox_x"],
            bbox_h=cell["bbox_h"],
            bbox_w=cell["bbox_w"],
            area_px=cell["area_px"],
        )

    return new_fov_id
