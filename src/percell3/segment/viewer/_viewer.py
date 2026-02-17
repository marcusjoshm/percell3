"""Internal napari viewer implementation — layer loading and label save-back."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore
    from percell3.core.models import ChannelConfig, FovInfo

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


def _channel_colormap(ch: ChannelConfig) -> str:
    """Determine napari colormap name from ChannelConfig."""
    # Try explicit color hex first
    if ch.color:
        key = ch.color.lstrip("#").lower()
        if key in _COLOR_TO_COLORMAP:
            return _COLOR_TO_COLORMAP[key]

    # Fall back to channel name
    name_lower = ch.name.lower()
    for pattern, cmap in _NAME_TO_COLORMAP.items():
        if pattern in name_lower:
            return cmap

    return "gray"


def _launch(
    store: ExperimentStore,
    fov: str,
    condition: str,
    channels: list[str] | None = None,
    bio_rep: str | None = None,
) -> int | None:
    """Internal launch implementation. Called by launch_viewer()."""
    import napari

    # --- Pre-flight validation ---
    if sys.platform not in ("darwin", "win32") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise RuntimeError(
            "napari requires a display server. "
            "Set DISPLAY (X11) or WAYLAND_DISPLAY, or use X11 forwarding."
        )

    fov_info, _ = store._resolve_fov(fov, condition, bio_rep)

    all_channels = store.get_channels()
    if not all_channels:
        raise ValueError("No channels found. Import images first.")

    if channels is not None:
        ch_names_lower = {c.lower() for c in channels}
        selected_channels = [
            ch for ch in all_channels if ch.name.lower() in ch_names_lower
        ]
    else:
        selected_channels = all_channels

    if not selected_channels:
        raise ValueError(f"No matching channels found for: {channels}")

    # --- Create viewer ---
    viewer = napari.Viewer(title=f"PerCell 3 \u2014 {fov} ({condition})")

    # --- Load channel images ---
    _load_channel_layers(viewer, store, fov, condition, selected_channels, bio_rep=bio_rep)

    # --- Load labels ---
    original_hash, parent_run_id, seg_channel = _load_label_layer(
        viewer, store, fov, condition, selected_channels, bio_rep=bio_rep,
    )

    # --- Block until viewer closes ---
    napari.run()

    # --- Check for edits and save ---
    label_layers = [lyr for lyr in viewer.layers if isinstance(lyr, napari.layers.Labels)]
    if not label_layers:
        return None

    edited_labels = np.asarray(label_layers[0].data, dtype=np.int32)

    if original_hash is not None:
        edited_hash = hashlib.sha256(edited_labels.tobytes()).hexdigest()
        if original_hash == edited_hash:
            logger.info("No label changes detected.")
            return None

    # Labels changed (or created from scratch)
    channel_name = seg_channel or selected_channels[0].name
    run_id = save_edited_labels(
        store, fov_info, fov, condition, edited_labels,
        parent_run_id, channel_name, bio_rep=bio_rep,
    )
    return run_id


def _load_channel_layers(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov: str,
    condition: str,
    channels: list[ChannelConfig],
    bio_rep: str | None = None,
) -> None:
    """Add image layers for each channel."""
    for ch in channels:
        data = store.read_image(fov, condition, ch.name, bio_rep=bio_rep)
        cmap = _channel_colormap(ch)

        viewer.add_image(
            data,
            name=ch.name,
            colormap=cmap,
            blending="additive",
        )


def _load_label_layer(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov: str,
    condition: str,
    channels: list[ChannelConfig],
    bio_rep: str | None = None,
) -> tuple[str | None, int | None, str | None]:
    """Load the most recent label layer, or create an empty one.

    Returns:
        (original_labels_hash, parent_run_id, segmentation_channel_name)
        The hash is a SHA-256 hex digest used for change detection without
        keeping a full copy of the label array in memory.
    """
    runs = store.get_segmentation_runs()

    # Pick the most recent run (highest id)
    parent_run_id: int | None = None
    seg_channel: str | None = None
    if runs:
        latest = max(runs, key=lambda r: r["id"])
        parent_run_id = latest["id"]
        seg_channel = latest.get("channel")

    # Try to read existing labels
    original_hash: str | None = None
    try:
        labels = store.read_labels(fov, condition, bio_rep=bio_rep)
        original_hash = hashlib.sha256(labels.tobytes()).hexdigest()
        viewer.add_labels(labels, name="segmentation", opacity=0.5)
    except KeyError:
        # No labels exist in zarr — create empty layer for painting from scratch
        # Get shape from the first image layer
        if not viewer.layers:
            raise RuntimeError(
                "Cannot create empty label layer: no image layers loaded."
            )
        shape = viewer.layers[0].data.shape[-2:]
        empty = np.zeros(shape, dtype=np.int32)
        viewer.add_labels(empty, name="segmentation", opacity=0.5)

    return original_hash, parent_run_id, seg_channel


def save_edited_labels(
    store: ExperimentStore,
    fov_info: FovInfo,
    fov: str,
    condition: str,
    edited_labels: np.ndarray,
    parent_run_id: int | None,
    channel: str,
    bio_rep: str | None = None,
) -> int:
    """Save edited labels back to ExperimentStore.

    Creates a new segmentation run, writes labels to zarr, extracts cells,
    and updates the run's cell count. This is the public API for saving
    labels — usable from both the napari viewer and headless scripts.

    Args:
        store: An open ExperimentStore.
        fov_info: FOV metadata (used for id and pixel_size_um).
        fov: FOV name.
        condition: Condition name.
        edited_labels: 2D int32 label array.
        parent_run_id: ID of the parent segmentation run (or None).
        channel: Channel name for the segmentation run.
        bio_rep: Optional biological replicate name.

    Returns:
        The new segmentation run ID.

    Raises:
        ValueError: If labels are not 2D or contain negative values.
    """
    from percell3.segment.roi_import import store_labels_and_cells

    # Validate
    if edited_labels.ndim != 2:
        raise ValueError(
            f"Labels must be 2D, got {edited_labels.ndim}D "
            f"with shape {edited_labels.shape}"
        )
    if edited_labels.min() < 0:
        raise ValueError("Labels contain negative values.")

    labels_int32 = np.asarray(edited_labels, dtype=np.int32)

    # Create segmentation run with provenance
    parameters = {
        "method": "napari_manual_edit",
        "parent_run_id": parent_run_id,
        "channel": channel,
    }
    run_id = store.add_segmentation_run(channel, "napari_edit", parameters)

    # Write labels, extract cells, update count
    try:
        cell_count = store_labels_and_cells(
            store, labels_int32, fov_info, fov, condition, run_id,
            bio_rep=bio_rep,
        )
    except Exception as exc:
        logger.warning(
            "Cell extraction failed after label save: %s. "
            "Labels are preserved; re-extract manually.",
            exc,
        )
        cell_count = 0

    if cell_count == 0:
        logger.warning("All labels erased — saved empty label image with 0 cells.")

    logger.info(
        "Saved %d cells from napari edit (run_id=%d, parent=%s)",
        cell_count, run_id, parent_run_id,
    )
    return run_id
