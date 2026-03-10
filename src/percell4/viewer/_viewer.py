"""Internal napari viewer implementation -- layer loading, FOV browsing,
and label save-back for PerCell 4.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

# Default colormaps for common channel names/colors.
_COLOR_TO_COLORMAP: dict[str, str] = {
    "0000ff": "blue",
    "00ff00": "green",
    "ff0000": "red",
    "ff00ff": "magenta",
    "ffff00": "yellow",
    "00ffff": "cyan",
}

_NAME_TO_COLORMAP: dict[str, str] = {
    "dapi": "blue",
    "gfp": "green",
    "rfp": "red",
    "brightfield": "gray",
}


def _channel_colormap(ch: dict) -> str:
    """Determine napari colormap name from a channel dict."""
    color = ch.get("color")
    if color:
        key = color.lstrip("#").lower()
        if key in _COLOR_TO_COLORMAP:
            return _COLOR_TO_COLORMAP[key]

    name_lower = ch["name"].lower()
    for pattern, cmap in _NAME_TO_COLORMAP.items():
        if pattern in name_lower:
            return cmap

    return "gray"


# ---------------------------------------------------------------------------
# State container for the currently loaded FOV
# ---------------------------------------------------------------------------


class _ViewerState:
    """Holds mutable state for the current viewer session."""

    def __init__(self) -> None:
        self.current_fov_id: bytes | None = None
        self.original_labels_hash: str | None = None
        self.active_seg_set_id: bytes | None = None


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


def _launch(
    store: ExperimentStore,
    fov_id: bytes | None = None,
) -> None:
    """Internal launch implementation. Called by launch_viewer()."""
    import napari

    from percell4.core.db_types import uuid_to_hex, uuid_to_str

    # --- Pre-flight validation ---
    if sys.platform not in ("darwin", "win32") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise RuntimeError(
            "napari requires a display server. "
            "Set DISPLAY (X11) or WAYLAND_DISPLAY, or use X11 forwarding."
        )

    exp = store.db.get_experiment()
    if exp is None:
        raise ValueError("No experiment found in database.")

    exp_name = exp["name"]
    fovs = store.db.get_fovs(exp["id"])
    if not fovs:
        raise ValueError("No FOVs found. Import images first.")

    # Pick initial FOV
    if fov_id is not None:
        fov = store.db.get_fov(fov_id)
        if fov is None:
            raise ValueError(
                f"FOV {uuid_to_str(fov_id)} not found."
            )
    else:
        fov = fovs[0]
        fov_id = fov["id"]

    # --- Create viewer ---
    viewer = napari.Viewer(title=f"PerCell 4 -- {exp_name}")

    state = _ViewerState()

    # --- Load initial FOV ---
    _load_fov(viewer, store, fov_id, state)

    # --- Add dock widgets ---
    from percell4.viewer.cellpose_widget import CellposeWidget
    from percell4.viewer.edge_removal_widget import EdgeRemovalWidget
    from percell4.viewer.edit_widget import EditWidget
    from percell4.viewer.fov_browser_widget import FovBrowserWidget

    def _on_fov_selected(new_fov_id: bytes) -> None:
        """Callback when user selects a different FOV in the browser."""
        _save_if_changed(viewer, store, state)
        _load_fov(viewer, store, new_fov_id, state)

    browser = FovBrowserWidget(viewer, store, _on_fov_selected)
    viewer.window.add_dock_widget(
        browser.widget, name="FOV Browser", area="right",
    )

    # Edit ROIs widget
    edit_widget = EditWidget(viewer, store, fov_id)
    viewer.window.add_dock_widget(
        edit_widget.widget, name="Edit ROIs", area="right",
    )

    # Cellpose re-segmentation widget
    channels = store.db.get_channels(exp["id"])
    channel_names = [ch["name"] for ch in channels]
    cellpose_widget = CellposeWidget(viewer, store, fov_id, channel_names)
    viewer.window.add_dock_widget(
        cellpose_widget.widget, name="Cellpose", area="right",
    )

    # Label cleanup widget
    edge_removal_widget = EdgeRemovalWidget(viewer, store, fov_id)
    viewer.window.add_dock_widget(
        edge_removal_widget.widget, name="Cleanup", area="right",
    )

    # --- Block until viewer closes ---
    napari.run()

    # --- Save-on-close ---
    _save_if_changed(viewer, store, state)


# ---------------------------------------------------------------------------
# FOV loading
# ---------------------------------------------------------------------------


def _load_fov(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov_id: bytes,
    state: _ViewerState,
) -> None:
    """Clear the viewer and load all layers for the given FOV."""
    from percell4.core.db_types import uuid_to_hex, uuid_to_str

    fov = store.db.get_fov(fov_id)
    if fov is None:
        logger.error("FOV %s not found", uuid_to_str(fov_id))
        return

    # Clear existing layers
    viewer.layers.clear()

    state.current_fov_id = fov_id
    state.original_labels_hash = None
    state.active_seg_set_id = None

    fov_name = fov["auto_name"] or uuid_to_str(fov_id)[:8]

    # Load layers
    _load_channel_layers(viewer, store, fov)
    _load_label_layer(viewer, store, fov, state)
    _load_mask_layers(viewer, store, fov)

    # Update title
    exp = store.db.get_experiment()
    exp_name = exp["name"] if exp else "Experiment"
    viewer.title = f"PerCell 4 -- {exp_name} -- {fov_name}"


def _load_channel_layers(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov: dict,
) -> None:
    """Add image layers for each channel."""
    from percell4.core.db_types import uuid_to_hex

    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    fov_hex = uuid_to_hex(fov["id"])

    # Check for pixel_size_um
    pixel_size = fov["pixel_size_um"]
    scale = (pixel_size, pixel_size) if pixel_size else None

    for idx, ch in enumerate(channels):
        try:
            data = store.layers.read_image_channel(fov_hex, idx)
        except Exception:
            logger.warning("Could not read channel %d (%s)", idx, ch["name"])
            continue

        cmap = _channel_colormap(ch)
        kwargs: dict = {
            "name": ch["name"],
            "colormap": cmap,
            "blending": "additive",
        }
        if scale is not None:
            kwargs["scale"] = scale

        viewer.add_image(data, **kwargs)


def _load_label_layer(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov: dict,
    state: _ViewerState,
) -> None:
    """Load the active segmentation label layer."""
    from percell4.core.db_types import uuid_to_hex

    fov_id = fov["id"]
    fov_hex = uuid_to_hex(fov_id)

    # Check for pixel_size_um
    pixel_size = fov["pixel_size_um"]
    scale = (pixel_size, pixel_size) if pixel_size else None

    # Find active segmentation assignment
    assignments = store.db.get_active_assignments(fov_id)
    seg_assignments = assignments["segmentation"]

    if seg_assignments:
        seg_set_id = seg_assignments[0]["segmentation_set_id"]
        seg_set_hex = uuid_to_hex(seg_set_id)

        try:
            labels = store.layers.read_labels(seg_set_hex, fov_hex)
            state.original_labels_hash = hashlib.sha256(
                labels.tobytes()
            ).hexdigest()
            state.active_seg_set_id = seg_set_id

            kwargs: dict = {
                "name": "segmentation",
                "opacity": 0.5,
            }
            if scale is not None:
                kwargs["scale"] = scale

            viewer.add_labels(labels, **kwargs)
            return
        except Exception:
            logger.warning("Could not read labels for seg set %s", seg_set_hex)

    # No labels exist -- create empty layer for painting
    if viewer.layers:
        shape = viewer.layers[0].data.shape[-2:]
        empty = np.zeros(shape, dtype=np.int32)
        kwargs_empty: dict = {"name": "segmentation", "opacity": 0.5}
        if scale is not None:
            kwargs_empty["scale"] = scale
        viewer.add_labels(empty, **kwargs_empty)


def _load_mask_layers(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov: dict,
) -> None:
    """Load threshold mask layers from active mask assignments."""
    from percell4.core.db_types import uuid_to_hex

    fov_id = fov["id"]

    # Check for pixel_size_um
    pixel_size = fov["pixel_size_um"]
    scale = (pixel_size, pixel_size) if pixel_size else None

    assignments = store.db.get_active_assignments(fov_id)
    mask_assignments = assignments["mask"]

    loaded_masks: set[bytes] = set()
    for ma in mask_assignments:
        mask_id = ma["threshold_mask_id"]
        if mask_id in loaded_masks:
            continue

        mask_hex = uuid_to_hex(mask_id)
        try:
            mask = store.layers.read_mask(mask_hex)
        except Exception:
            logger.warning("Could not read mask %s", mask_hex)
            continue

        try:
            purpose = ma["purpose"] or "mask"
        except (IndexError, KeyError):
            purpose = "mask"
        kwargs: dict = {
            "name": f"{purpose} mask",
            "colormap": "magenta",
            "blending": "additive",
            "opacity": 0.4,
            "visible": False,
        }
        if scale is not None:
            kwargs["scale"] = scale

        viewer.add_image(mask, **kwargs)
        loaded_masks.add(mask_id)
        logger.info("Loaded mask '%s'", purpose)


# ---------------------------------------------------------------------------
# Save-on-close
# ---------------------------------------------------------------------------


def compute_labels_hash(labels: np.ndarray) -> str:
    """Compute SHA-256 hash of a labels array."""
    return hashlib.sha256(np.asarray(labels).tobytes()).hexdigest()


def _save_if_changed(
    viewer: "napari.Viewer",
    store: ExperimentStore,
    state: _ViewerState,
) -> None:
    """Check if labels were edited and save if changed."""
    import napari as _napari

    if state.current_fov_id is None:
        return

    label_layers = [
        lyr for lyr in viewer.layers
        if isinstance(lyr, _napari.layers.Labels)
    ]
    if not label_layers:
        return

    edited_labels = np.asarray(label_layers[0].data, dtype=np.int32)
    edited_hash = compute_labels_hash(edited_labels)

    if state.original_labels_hash is not None:
        if edited_hash == state.original_labels_hash:
            logger.info("No label changes detected.")
            return

    # Labels changed (or were created from scratch with no original)
    if state.original_labels_hash is None and edited_labels.max() == 0:
        # Empty labels painted with nothing -- no need to save
        return

    _save_edited_labels(store, state.current_fov_id, edited_labels)


def _save_edited_labels(
    store: ExperimentStore,
    fov_id: bytes,
    edited_labels: np.ndarray,
) -> None:
    """Save edited labels back to the experiment.

    Creates a new segmentation set record with model_name='napari_edit',
    writes labels to LayerStore, and logs the action.

    Args:
        store: An open ExperimentStore.
        fov_id: FOV UUID.
        edited_labels: 2D int32 label array.
    """
    from percell4.core.db_types import new_uuid, uuid_to_hex, uuid_to_str

    if edited_labels.ndim != 2:
        raise ValueError(
            f"Labels must be 2D, got {edited_labels.ndim}D "
            f"with shape {edited_labels.shape}"
        )

    labels_int32 = np.asarray(edited_labels, dtype=np.int32)
    fov_hex = uuid_to_hex(fov_id)

    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    first_channel = channels[0]["name"] if channels else "unknown"

    # Find the top-level ROI type (cell)
    roi_types = store.db.get_roi_type_definitions(exp["id"])
    cell_rt = None
    for rt in roi_types:
        if rt["parent_type_id"] is None:
            cell_rt = rt
            break

    if cell_rt is None:
        logger.warning("No top-level ROI type found; cannot save labels.")
        return

    # Create new segmentation set
    seg_set_id = new_uuid()
    seg_set_hex = uuid_to_hex(seg_set_id)
    run_id = new_uuid()

    # Write labels to zarr
    store.layers.write_labels(seg_set_hex, fov_hex, labels_int32)

    # Insert segmentation set record and assign
    with store.db.transaction():
        store.db.insert_pipeline_run(
            id=run_id,
            operation_name="napari_edit",
            config_snapshot='{"method": "napari_manual_edit"}',
        )
        store.db.complete_pipeline_run(run_id, status="completed")

        store.db.insert_segmentation_set(
            id=seg_set_id,
            experiment_id=exp["id"],
            produces_roi_type_id=cell_rt["id"],
            seg_type="cellular",
            source_channel=first_channel,
            model_name="napari_edit",
            parameters='{"method": "napari_manual_edit"}',
        )

        store.db.assign_segmentation(
            [fov_id],
            seg_set_id,
            cell_rt["id"],
            pipeline_run_id=run_id,
            assigned_by="napari_edit",
        )

    n_cells = len(np.unique(labels_int32)) - (1 if 0 in labels_int32 else 0)
    logger.info(
        "Saved %d cells from napari edit (seg_set=%s, fov=%s)",
        n_cells,
        uuid_to_str(seg_set_id)[:8],
        uuid_to_str(fov_id)[:8],
    )
