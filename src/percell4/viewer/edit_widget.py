"""Edit Labels dock widget -- Delete Cell and Draw Cell (polygon).

Ported from percell3.segment.viewer.edit_widget with percell4 patterns:
    - Reference to store and fov_id for future persistence
    - Same QWidget-as-attribute pattern as FovBrowserWidget
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from skimage.draw import polygon as sk_polygon

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

OUTLINE_LAYER_NAME = "cell_outline"


# ---------------------------------------------------------------------------
# Pure-logic helpers (testable without Qt)
# ---------------------------------------------------------------------------


def delete_label_from_array(
    labels: np.ndarray,
    label_id: int,
) -> bool:
    """Set all pixels with *label_id* to 0 in-place.

    Args:
        labels: 2D label image (modified in-place).
        label_id: The label value to erase.

    Returns:
        True if any pixels were changed, False otherwise.
    """
    mask = labels == label_id
    if not mask.any():
        return False
    labels[mask] = 0
    return True


def rasterize_polygon(
    labels: np.ndarray,
    row_coords: np.ndarray,
    col_coords: np.ndarray,
    new_label: int | None = None,
) -> int:
    """Rasterize a polygon into the label image.

    Fills the interior of the polygon defined by *row_coords* and
    *col_coords* with *new_label* (defaults to ``labels.max() + 1``).

    Args:
        labels: 2D label image (modified in-place).
        row_coords: Y (row) coordinates of polygon vertices.
        col_coords: X (col) coordinates of polygon vertices.
        new_label: Label value to assign. If None, uses ``labels.max() + 1``.

    Returns:
        The label ID assigned to the new polygon.

    Raises:
        ValueError: If the polygon produces no valid pixels.
    """
    if new_label is None:
        new_label = int(labels.max()) + 1

    rr, cc = sk_polygon(row_coords, col_coords, shape=labels.shape[-2:])

    if len(rr) == 0:
        raise ValueError(
            "Polygon produced no pixels (too small or out of bounds)."
        )

    labels[rr, cc] = new_label
    return new_label


# ---------------------------------------------------------------------------
# Qt widget
# ---------------------------------------------------------------------------


class EditWidget:
    """Dock widget for editing segmented cells.

    Provides two operations:

    * **Delete Cell** -- pick a cell and erase it (fill with 0).
    * **Draw Cell (Polygon)** -- click vertices around a cell, then
      *Confirm Cell* to rasterize the polygon as a new label.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: Current FOV UUID.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: bytes,
    ) -> None:
        from qtpy.QtWidgets import (
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("Edit Labels")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "Delete: pick mode (5) -> click cell -> Delete Cell\n"
            "Polygon: Draw Cell -> click vertices -> Confirm Cell"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: gray;")
        layout.addWidget(instructions)

        # Delete button
        self._delete_btn = QPushButton("Delete Cell")
        self._delete_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; color: red; }"
        )
        self._delete_btn.clicked.connect(self._on_delete)
        layout.addWidget(self._delete_btn)

        # Draw Cell (polygon) button
        self._draw_btn = QPushButton("Draw Cell (Polygon)")
        self._draw_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._draw_btn.clicked.connect(self._on_draw_polygon)
        layout.addWidget(self._draw_btn)

        # Confirm Cell button
        self._confirm_btn = QPushButton("Confirm Cell")
        self._confirm_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; color: green; }"
        )
        self._confirm_btn.clicked.connect(self._on_confirm_polygon)
        layout.addWidget(self._confirm_btn)

        # Status
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    def _find_labels_layer(self) -> Any:
        """Find the 'segmentation' Labels layer."""
        import napari.layers

        for layer in self._viewer.layers:
            if isinstance(layer, napari.layers.Labels) and layer.name == "segmentation":
                return layer
        return None

    def _on_delete(self) -> None:
        """Delete the currently selected cell label."""
        labels_layer = self._find_labels_layer()
        if labels_layer is None:
            self._status_label.setText("No segmentation layer found.")
            self._status_label.setStyleSheet("color: red;")
            return

        selected = labels_layer.selected_label
        if selected == 0:
            self._status_label.setText("No cell selected (label=0 is background).")
            self._status_label.setStyleSheet("color: orange;")
            return

        # Find a coordinate belonging to this label for fill()
        coords = np.argwhere(labels_layer.data == selected)
        if len(coords) == 0:
            self._status_label.setText(f"Cell #{selected} not found in labels.")
            self._status_label.setStyleSheet("color: orange;")
            return

        # Use fill() for undo-compatible deletion (sets all connected
        # pixels with this label value to 0)
        coord = tuple(coords[0])
        labels_layer.fill(coord, 0)

        self._status_label.setText(f"Deleted cell #{selected}")
        self._status_label.setStyleSheet("color: green;")
        logger.info("Deleted cell #%d via EditWidget", selected)

    # ------------------------------------------------------------------
    # Draw Cell (Polygon)
    # ------------------------------------------------------------------

    def _find_or_create_shapes_layer(self) -> Any:
        """Return the ``cell_outline`` Shapes layer, creating it if needed."""
        import napari.layers

        for layer in self._viewer.layers:
            if isinstance(layer, napari.layers.Shapes) and layer.name == OUTLINE_LAYER_NAME:
                layer.data = []  # clear previous polygons
                return layer

        shapes = self._viewer.add_shapes(
            name=OUTLINE_LAYER_NAME,
            shape_type="polygon",
            edge_color="yellow",
            edge_width=2,
            face_color="transparent",
        )
        return shapes

    def _on_draw_polygon(self) -> None:
        """Activate polygon drawing on a Shapes layer."""
        labels_layer = self._find_labels_layer()
        if labels_layer is None:
            self._status_label.setText("No segmentation layer found.")
            self._status_label.setStyleSheet("color: red;")
            return

        shapes = self._find_or_create_shapes_layer()
        shapes.mode = "add_polygon"
        self._viewer.layers.selection.active = shapes

        self._status_label.setText("Draw polygon, then click Confirm Cell")
        self._status_label.setStyleSheet("color: cyan;")

    def _on_confirm_polygon(self) -> None:
        """Rasterize the last polygon into the Labels layer as a new cell."""
        import napari.layers

        labels_layer = self._find_labels_layer()
        if labels_layer is None:
            self._status_label.setText("No segmentation layer found.")
            self._status_label.setStyleSheet("color: red;")
            return

        # Find the shapes layer
        shapes_layer = None
        for layer in self._viewer.layers:
            if isinstance(layer, napari.layers.Shapes) and layer.name == OUTLINE_LAYER_NAME:
                shapes_layer = layer
                break

        if shapes_layer is None or len(shapes_layer.data) == 0:
            self._status_label.setText("No polygon drawn. Draw one first.")
            self._status_label.setStyleSheet("color: orange;")
            return

        # Take the last polygon
        polygon = np.asarray(shapes_layer.data[-1])
        rows = polygon[:, -2]
        cols = polygon[:, -1]

        try:
            new_label = rasterize_polygon(labels_layer.data, rows, cols)
        except ValueError as exc:
            self._status_label.setText(str(exc))
            self._status_label.setStyleSheet("color: orange;")
            return

        labels_layer.refresh()

        # Clear the shapes layer
        shapes_layer.data = []

        self._status_label.setText(f"Added cell #{new_label}")
        self._status_label.setStyleSheet("color: green;")
        logger.info("Added cell #%d via polygon draw", new_label)
