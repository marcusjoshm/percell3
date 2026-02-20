"""Edit Labels dock widget for the napari viewer — Delete Cell button."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import napari

logger = logging.getLogger(__name__)


class EditWidget:
    """Dock widget with a Delete Cell button for removing segmented cells.

    Uses napari's Labels layer ``fill()`` API so that deletions are
    undo-compatible (Ctrl+Z works). The user selects a cell by clicking
    on it in pick mode, then clicks "Delete Cell" to erase all its pixels.

    Args:
        viewer: The napari Viewer instance.
    """

    def __init__(self, viewer: napari.Viewer) -> None:
        from qtpy.QtWidgets import (
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("Edit Labels")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Instructions
        instructions = QLabel(
            "1. Select the segmentation layer\n"
            "2. Switch to pick mode (press 5)\n"
            "3. Click on a cell to select it\n"
            "4. Click 'Delete Cell' to remove it"
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
