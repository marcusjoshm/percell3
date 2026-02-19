"""Napari threshold QC viewer — live Otsu preview with ROI and accept/skip buttons."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ThresholdDecision:
    """Result from the napari threshold viewer for one group.

    Attributes:
        accepted: True if user accepted the threshold.
        threshold_value: The Otsu threshold value used.
        roi: List of (x1, y1, x2, y2) rectangles, or None if no ROI drawn.
        skip_remaining: True if user clicked "Skip Remaining".
    """

    accepted: bool
    threshold_value: float
    roi: list[tuple[int, int, int, int]] | None = None
    skip_remaining: bool = False


def compute_masked_otsu(
    image: np.ndarray,
    cell_mask: np.ndarray,
    roi: list[tuple[int, int, int, int]] | None = None,
) -> float:
    """Compute Otsu threshold on non-zero pixels within mask, optionally restricted by ROI.

    Args:
        image: 2D channel image (full FOV).
        cell_mask: Boolean mask of group cells (True = cell pixels).
        roi: Optional list of (x1, y1, x2, y2) rectangles to restrict Otsu computation.

    Returns:
        Otsu threshold value.

    Raises:
        ValueError: If no valid pixels to threshold.
    """
    from skimage.filters import threshold_otsu

    if roi:
        # Create ROI mask from union of rectangles
        roi_mask = np.zeros_like(cell_mask, dtype=bool)
        for x1, y1, x2, y2 in roi:
            roi_mask[y1:y2, x1:x2] = True
        combined_mask = cell_mask & roi_mask
    else:
        combined_mask = cell_mask

    pixels = image[combined_mask]
    if len(pixels) == 0:
        raise ValueError("No valid pixels for Otsu computation")

    return float(threshold_otsu(pixels))


def create_group_image(
    channel_image: np.ndarray,
    labels: np.ndarray,
    cell_label_values: list[int],
) -> tuple[np.ndarray, np.ndarray]:
    """Create a group image with only specified cells visible.

    Args:
        channel_image: 2D channel image (full FOV).
        labels: 2D label image (full FOV).
        cell_label_values: Label values for cells in this group.

    Returns:
        (group_image, cell_mask) — group_image has non-group cells zeroed,
        cell_mask is boolean mask of group cell pixels.
    """
    label_set = set(cell_label_values)
    cell_mask = np.zeros(labels.shape, dtype=bool)
    for lv in label_set:
        cell_mask |= (labels == lv)

    group_image = np.where(cell_mask, channel_image, 0)
    return group_image, cell_mask


def launch_threshold_viewer(
    group_image: np.ndarray,
    cell_mask: np.ndarray,
    group_name: str,
    fov_name: str,
    initial_threshold: float | None = None,
) -> ThresholdDecision:
    """Open napari with live threshold preview for a cell group.

    Shows:
    - Group image (channel data, non-group cells zeroed)
    - Threshold preview overlay (updates live with ROI changes)
    - Dock widget with Accept/Skip/Skip Remaining buttons

    Args:
        group_image: 2D image with non-group cells zeroed.
        cell_mask: Boolean mask of group cell pixels.
        group_name: Display name (e.g., "g1 (mean=52.3)").
        fov_name: FOV name for display.
        initial_threshold: Pre-computed Otsu value (or None to compute).

    Returns:
        ThresholdDecision with accepted=True/False, threshold value, and ROI.
        Returns ThresholdDecision(accepted=False, ...) if window closed without action.
    """
    import napari

    # Pre-flight display check
    if sys.platform not in ("darwin", "win32") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise RuntimeError(
            "napari requires a display server. "
            "Set DISPLAY or WAYLAND_DISPLAY."
        )

    # Compute initial threshold if not provided
    if initial_threshold is None:
        try:
            initial_threshold = compute_masked_otsu(group_image, cell_mask)
        except ValueError:
            initial_threshold = 0.0

    # State shared between widget callbacks
    state = {
        "decision": None,
        "threshold": initial_threshold,
        "roi": None,
    }

    viewer = napari.Viewer(
        title=f"Threshold QC \u2014 {fov_name} / {group_name}",
    )

    # Add image layer
    viewer.add_image(group_image, name="group_image", colormap="gray")

    # Add threshold preview (labels layer)
    preview = (group_image > initial_threshold) & cell_mask
    preview_layer = viewer.add_labels(
        preview.astype(np.int32), name="threshold_preview", opacity=0.4,
    )

    # Add shapes layer for ROI drawing
    shapes_layer = viewer.add_shapes(
        name="ROI",
        shape_type="rectangle",
        edge_color="yellow",
        edge_width=2,
        face_color=[1, 1, 0, 0.1],
    )

    def _update_preview() -> None:
        """Recompute Otsu and update preview layer."""
        roi_rects = _extract_rois(shapes_layer)
        try:
            thresh = compute_masked_otsu(group_image, cell_mask, roi=roi_rects or None)
        except ValueError:
            thresh = state["threshold"]

        state["threshold"] = thresh
        state["roi"] = roi_rects or None
        new_preview = (group_image > thresh) & cell_mask
        preview_layer.data = new_preview.astype(np.int32)

    def _extract_rois(shapes_lyr) -> list[tuple[int, int, int, int]]:
        """Extract rectangle ROIs from shapes layer data."""
        rois = []
        if shapes_lyr.data:
            for shape_data in shapes_lyr.data:
                coords = np.array(shape_data)
                y_min = int(max(0, coords[:, 0].min()))
                x_min = int(max(0, coords[:, 1].min()))
                y_max = int(min(group_image.shape[0], coords[:, 0].max()))
                x_max = int(min(group_image.shape[1], coords[:, 1].max()))
                if y_max > y_min and x_max > x_min:
                    rois.append((x_min, y_min, x_max, y_max))
        return rois

    # Connect shapes changes to preview update
    shapes_layer.events.data.connect(lambda _: _update_preview())

    # --- Dock Widget ---
    from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    widget = QWidget()
    layout = QVBoxLayout()

    info_label = QLabel(f"FOV: {fov_name}\nGroup: {group_name}")
    layout.addWidget(info_label)

    thresh_label = QLabel(f"Threshold: {initial_threshold:.1f}")
    layout.addWidget(thresh_label)

    def _refresh_label() -> None:
        thresh_label.setText(f"Threshold: {state['threshold']:.1f}")
        positive = np.sum((group_image > state["threshold"]) & cell_mask)
        total = np.sum(cell_mask)
        frac = positive / total if total > 0 else 0
        info_label.setText(
            f"FOV: {fov_name}\nGroup: {group_name}\n"
            f"Positive: {positive} / {total} ({frac:.1%})"
        )

    # Update label when shapes change
    shapes_layer.events.data.connect(lambda _: _refresh_label())

    accept_btn = QPushButton("Accept")
    skip_btn = QPushButton("Skip")
    skip_remaining_btn = QPushButton("Skip Remaining")

    def _on_accept():
        state["decision"] = ThresholdDecision(
            accepted=True,
            threshold_value=state["threshold"],
            roi=state["roi"],
        )
        viewer.close()

    def _on_skip():
        state["decision"] = ThresholdDecision(
            accepted=False,
            threshold_value=state["threshold"],
        )
        viewer.close()

    def _on_skip_remaining():
        state["decision"] = ThresholdDecision(
            accepted=False,
            threshold_value=state["threshold"],
            skip_remaining=True,
        )
        viewer.close()

    accept_btn.clicked.connect(_on_accept)
    skip_btn.clicked.connect(_on_skip)
    skip_remaining_btn.clicked.connect(_on_skip_remaining)

    layout.addWidget(accept_btn)
    layout.addWidget(skip_btn)
    layout.addWidget(skip_remaining_btn)
    widget.setLayout(layout)

    viewer.window.add_dock_widget(widget, name="Threshold QC", area="right")

    # Block until viewer closes
    napari.run()

    # If window closed without button click, treat as skip
    if state["decision"] is None:
        return ThresholdDecision(
            accepted=False,
            threshold_value=state["threshold"],
        )

    return state["decision"]
