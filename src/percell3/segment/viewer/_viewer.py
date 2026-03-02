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


_EXTRA_COLORMAPS = (
    "nipy_spectral", "Spectral", "rainbow", "coolwarm",
    "gnuplot", "jet", "cividis",
)


def _register_extra_colormaps() -> None:
    """Register matplotlib colormaps with napari's colormap registry."""
    try:
        from napari.utils.colormaps import AVAILABLE_COLORMAPS, ensure_colormap
    except ImportError:
        return

    for name in _EXTRA_COLORMAPS:
        if name not in AVAILABLE_COLORMAPS:
            try:
                AVAILABLE_COLORMAPS[name] = ensure_colormap(name)
            except (KeyError, ValueError):
                pass


def _launch(
    store: ExperimentStore,
    fov_id: int,
    channels: list[str] | None = None,
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

    fov_info = store.get_fov_by_id(fov_id)

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

    # Register extra matplotlib colormaps with napari so they appear
    # in the layer control dropdown for all layers.
    _register_extra_colormaps()

    # --- Create viewer ---
    viewer = napari.Viewer(
        title=f"PerCell 3 \u2014 {fov_info.display_name} ({fov_info.condition})"
    )

    # --- Load channel images ---
    _load_channel_layers(viewer, store, fov_id, selected_channels)

    # --- Load labels ---
    original_hash, active_seg_id, seg_channel = _load_label_layer(
        viewer, store, fov_id, selected_channels,
    )

    # --- Load threshold masks (if any) ---
    _load_mask_layers(viewer, store, fov_id)

    # --- Add dock widgets ---
    channel_names = [ch.name for ch in selected_channels]
    window_menu = viewer.window.window_menu

    from percell3.segment.viewer.bg_subtraction_widget import BGSubtractionWidget
    from percell3.segment.viewer.cellpose_widget import CellposeWidget
    from percell3.segment.viewer.copy_labels_widget import CopyLabelsWidget
    from percell3.segment.viewer.copy_mask_widget import CopyMaskWidget
    from percell3.segment.viewer.edge_removal_widget import EdgeRemovalWidget
    from percell3.segment.viewer.edit_widget import EditWidget

    cellpose_w = CellposeWidget(viewer, store, fov_id, channel_names)
    viewer.window.add_dock_widget(
        cellpose_w.widget, name="Cellpose", area="right",
        menu=window_menu,
    )

    cleanup_w = EdgeRemovalWidget(viewer, store, fov_id)
    viewer.window.add_dock_widget(
        cleanup_w.widget, name="Label Cleanup", area="right",
        menu=window_menu,
    )

    edit_w = EditWidget(viewer)
    viewer.window.add_dock_widget(
        edit_w.widget, name="Edit Labels", area="right",
        menu=window_menu,
    )

    bg_sub_w = BGSubtractionWidget(viewer, store, fov_id, channel_names)
    viewer.window.add_dock_widget(
        bg_sub_w.widget, name="BG Subtraction", area="right",
        menu=window_menu,
    )

    copy_w = CopyLabelsWidget(viewer, store, fov_id, channel_names)
    viewer.window.add_dock_widget(
        copy_w.widget, name="Copy Labels", area="right",
        menu=window_menu,
    )

    copy_mask_w = CopyMaskWidget(viewer, store, fov_id, channel_names)
    viewer.window.add_dock_widget(
        copy_mask_w.widget, name="Copy Mask", area="right",
        menu=window_menu,
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
    seg_id = save_edited_labels(
        store, fov_info, edited_labels, active_seg_id, channel_name,
    )
    return seg_id


def _load_channel_layers(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov_id: int,
    channels: list[ChannelConfig],
) -> None:
    """Add image layers for each channel."""
    for ch in channels:
        data = store.read_image(fov_id, ch.name)
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
    fov_id: int,
    channels: list[ChannelConfig],
) -> tuple[str | None, int | None, str | None]:
    """Load the active segmentation label layer from fov_config.

    Looks up the fov_config for the most recent cellular segmentation
    assigned to this FOV. If none exists, creates an empty labels layer
    for painting from scratch.

    Returns:
        (original_labels_hash, segmentation_id, segmentation_channel_name)
        The hash is a SHA-256 hex digest used for change detection without
        keeping a full copy of the label array in memory.
    """
    # Find active cellular segmentation from fov_config
    active_seg_id: int | None = None
    seg_channel: str | None = None

    config_entries = store.get_fov_config(fov_id)
    for entry in config_entries:
        try:
            seg = store.get_segmentation(entry.segmentation_id)
            if seg.seg_type == "cellular":
                active_seg_id = seg.id
                seg_channel = seg.source_channel
                break
        except Exception:
            continue

    # Try to read existing labels
    original_hash: str | None = None
    if active_seg_id is not None:
        try:
            labels = store.read_labels(active_seg_id)
            original_hash = hashlib.sha256(labels.tobytes()).hexdigest()
            viewer.add_labels(labels, name="segmentation", opacity=0.5)
        except KeyError:
            active_seg_id = None  # Fall through to empty layer

    if active_seg_id is None:
        # No labels exist — create empty layer for painting from scratch
        if not viewer.layers:
            raise RuntimeError(
                "Cannot create empty label layer: no image layers loaded."
            )
        shape = viewer.layers[0].data.shape[-2:]
        empty = np.zeros(shape, dtype=np.int32)
        viewer.add_labels(empty, name="segmentation", opacity=0.5)

    return original_hash, active_seg_id, seg_channel


def _load_mask_layers(
    viewer: napari.Viewer,
    store: ExperimentStore,
    fov_id: int,
) -> None:
    """Load threshold mask layers from fov_config entries."""
    config_entries = store.get_fov_config(fov_id)
    if not config_entries:
        return

    # Collect unique threshold IDs from config
    loaded_thresholds: set[int] = set()
    for entry in config_entries:
        if entry.threshold_id is None:
            continue
        if entry.threshold_id in loaded_thresholds:
            continue

        try:
            thr = store.get_threshold(entry.threshold_id)
            mask = store.read_mask(entry.threshold_id)
        except (KeyError, Exception):
            continue

        viewer.add_image(
            mask,
            name=f"{thr.name} mask",
            colormap="magenta",
            blending="additive",
            opacity=0.4,
            visible=False,
        )
        loaded_thresholds.add(entry.threshold_id)
        logger.info("Loaded threshold mask '%s'", thr.name)


def save_edited_labels(
    store: ExperimentStore,
    fov_info: FovInfo,
    edited_labels: np.ndarray,
    segmentation_id: int | None,
    channel: str,
) -> int:
    """Save edited labels back to ExperimentStore.

    If a segmentation entity exists (segmentation_id is not None), overwrites
    it in place and triggers ``on_labels_edited()`` which propagates
    measurement updates to all FOVs referencing this segmentation.

    If no segmentation entity exists (painting from scratch), creates a new
    global segmentation entity.

    Args:
        store: An open ExperimentStore.
        fov_info: FOV metadata (used for id and pixel_size_um).
        edited_labels: 2D int32 label array.
        segmentation_id: Existing segmentation to overwrite (or None).
        channel: Channel name for the segmentation.

    Returns:
        The segmentation entity ID.

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
    h, w = labels_int32.shape

    if segmentation_id is not None:
        # Overwrite existing segmentation in place
        try:
            old_labels = store.read_labels(segmentation_id)
        except KeyError:
            old_labels = None

        try:
            cell_count = store_labels_and_cells(
                store, labels_int32, fov_info.id, segmentation_id,
                fov_info.pixel_size_um,
            )
        except Exception as exc:
            logger.warning(
                "Cell extraction failed after label save: %s. "
                "Labels are preserved; re-extract manually.",
                exc,
            )
            cell_count = 0

        # Trigger measurement propagation
        if old_labels is not None:
            try:
                from percell3.measure.auto_measure import on_labels_edited
                on_labels_edited(store, segmentation_id, old_labels, labels_int32)
            except Exception as exc:
                logger.warning("Auto-measurement after edit failed: %s", exc)

    else:
        # Create new segmentation entity (painting from scratch)
        name = store._generate_segmentation_name("napari_edit", channel)
        segmentation_id = store.add_segmentation(
            name=name, seg_type="cellular",
            width=w, height=h,
            source_fov_id=fov_info.id, source_channel=channel,
            model_name="napari_edit",
            parameters={"method": "napari_manual_edit"},
        )

        try:
            cell_count = store_labels_and_cells(
                store, labels_int32, fov_info.id, segmentation_id,
                fov_info.pixel_size_um,
            )
        except Exception as exc:
            logger.warning(
                "Cell extraction failed after label save: %s. "
                "Labels are preserved; re-extract manually.",
                exc,
            )
            cell_count = 0

        # Trigger auto-measurement for the new segmentation
        try:
            from percell3.measure.auto_measure import on_segmentation_created
            on_segmentation_created(store, segmentation_id, [fov_info.id])
        except Exception as exc:
            logger.warning("Auto-measurement for new seg failed: %s", exc)

    if cell_count == 0:
        logger.warning("All labels erased — saved empty label image with 0 cells.")

    logger.info(
        "Saved %d cells from napari edit (segmentation_id=%d)",
        cell_count, segmentation_id,
    )
    return segmentation_id
