"""Internal napari viewer implementation — layer loading and label save-back."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from percell3.core import ExperimentStore
    from percell3.core.models import ChannelConfig

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
    "hoechst": "blue",
    "gfp": "green",
    "fitc": "green",
    "rfp": "red",
    "cy3": "red",
    "cy5": "magenta",
    "tritc": "red",
    "brightfield": "gray",
    "bf": "gray",
    "dic": "gray",
    "phase": "gray",
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


def _default_contrast_limits(dtype: np.dtype) -> tuple[float, float] | None:
    """Return sensible contrast limits for a given dtype, or None for auto."""
    if dtype == np.uint16:
        return (0.0, 65535.0)
    if dtype == np.uint8:
        return (0.0, 255.0)
    return None


def _launch(
    store: ExperimentStore,
    region: str,
    condition: str,
    channels: list[str] | None = None,
) -> int | None:
    """Internal launch implementation. Called by launch_viewer()."""
    import napari

    # --- Pre-flight validation ---
    if sys.platform != "darwin" and not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "napari requires a display server. "
            "Set DISPLAY or use X11 forwarding."
        )

    all_regions = store.get_regions(condition=condition)
    region_info = None
    for r in all_regions:
        if r.name == region:
            region_info = r
            break
    if region_info is None:
        raise ValueError(
            f"Region {region!r} not found in condition {condition!r}. "
            f"Available: {[r.name for r in all_regions]}"
        )

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
    viewer = napari.Viewer(title=f"PerCell 3 \u2014 {region} ({condition})")

    # --- Load channel images ---
    _load_channel_layers(viewer, store, region, condition, selected_channels)

    # --- Load labels ---
    original_labels, parent_run_id, seg_channel = _load_label_layer(
        viewer, store, region, condition, selected_channels,
    )

    # --- Block until viewer closes ---
    napari.run()

    # --- Check for edits and save ---
    label_layers = [lyr for lyr in viewer.layers if isinstance(lyr, napari.layers.Labels)]
    if not label_layers:
        return None

    edited_labels = np.asarray(label_layers[0].data, dtype=np.int32)

    if original_labels is not None and np.array_equal(original_labels, edited_labels):
        logger.info("No label changes detected.")
        return None

    # Labels changed (or created from scratch)
    channel_name = seg_channel or selected_channels[0].name
    run_id = save_edited_labels(
        store, region, condition, edited_labels,
        parent_run_id, channel_name, region_info.pixel_size_um,
        region_info.id,
    )
    return run_id


def _load_channel_layers(
    viewer: object,
    store: ExperimentStore,
    region: str,
    condition: str,
    channels: list[ChannelConfig],
) -> None:
    """Add image layers for each channel."""
    for ch in channels:
        data = store.read_image(region, condition, ch.name)
        cmap = _channel_colormap(ch)
        limits = _default_contrast_limits(data.dtype)

        kwargs: dict = {
            "name": ch.name,
            "colormap": cmap,
            "blending": "additive",
        }
        if limits is not None:
            kwargs["contrast_limits"] = limits

        viewer.add_image(data, **kwargs)  # type: ignore[union-attr]


def _load_label_layer(
    viewer: object,
    store: ExperimentStore,
    region: str,
    condition: str,
    channels: list[ChannelConfig],
) -> tuple[np.ndarray | None, int | None, str | None]:
    """Load the most recent label layer, or create an empty one.

    Returns:
        (original_labels_copy, parent_run_id, segmentation_channel_name)
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
    original_labels: np.ndarray | None = None
    try:
        labels = store.read_labels(region, condition)
        original_labels = labels.copy()
        viewer.add_labels(labels, name="segmentation", opacity=0.5)  # type: ignore[union-attr]
    except KeyError:
        # No labels exist in zarr — create empty layer for painting from scratch
        # Get shape from the first image layer
        image_layers = [
            lyr for lyr in viewer.layers  # type: ignore[union-attr]
            if hasattr(lyr, "data") and not isinstance(lyr, type)
        ]
        if image_layers:
            shape = image_layers[0].data.shape
            # Handle dask arrays
            if hasattr(shape, '__len__') and len(shape) >= 2:
                label_shape = shape[-2:]
            else:
                label_shape = shape
        else:
            label_shape = (512, 512)

        empty = np.zeros(label_shape, dtype=np.int32)
        original_labels = None  # No original — any paint is a change
        viewer.add_labels(empty, name="segmentation", opacity=0.5)  # type: ignore[union-attr]

    return original_labels, parent_run_id, seg_channel


def save_edited_labels(
    store: ExperimentStore,
    region: str,
    condition: str,
    edited_labels: np.ndarray,
    parent_run_id: int | None,
    channel: str,
    pixel_size_um: float | None,
    region_id: int,
) -> int:
    """Save edited labels back to ExperimentStore.

    Creates a new segmentation run, writes labels to zarr, extracts cells,
    and updates the run's cell count. This is the public API for saving
    labels — usable from both the napari viewer and headless scripts.

    Args:
        store: An open ExperimentStore.
        region: Region name.
        condition: Condition name.
        edited_labels: 2D int32 label array.
        parent_run_id: ID of the parent segmentation run (or None).
        channel: Channel name for the segmentation run.
        pixel_size_um: Physical pixel size in micrometers (or None).
        region_id: Database ID of the region.

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
            store, labels_int32, region, condition, run_id,
            region_id, pixel_size_um,
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
