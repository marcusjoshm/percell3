"""Edge cell removal dock widget for the napari viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class EdgeRemovalWidget:
    """Dock widget for previewing and applying edge cell removal.

    Shows which cells would be removed at a given edge margin, then
    applies the removal and updates the label layer when confirmed.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: FOV database ID.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: int,
    ) -> None:
        from qtpy.QtWidgets import (
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._preview_layer: napari.layers.Labels | None = None

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Edge Cell Removal")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Parameters ---
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("Edge margin (px):"))
        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(0, 200)
        self._margin_spin.setValue(0)
        row.addWidget(self._margin_spin)
        param_layout.addLayout(row)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # --- Buttons ---
        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setStyleSheet(
            "QPushButton { padding: 6px; }"
        )
        self._preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(self._preview_btn)

        self._apply_btn = QPushButton("Apply Removal")
        self._apply_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # --- Status ---
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    def _get_label_layer(self) -> napari.layers.Labels | None:
        """Find the segmentation labels layer."""
        import napari

        for layer in self._viewer.layers:
            if isinstance(layer, napari.layers.Labels) and layer.name == "segmentation":
                return layer
        return None

    def _on_preview(self) -> None:
        """Highlight cells that would be removed at the current margin."""
        from percell3.segment.label_processor import filter_edge_cells

        label_layer = self._get_label_layer()
        if label_layer is None:
            self._status_label.setText("No segmentation labels found.")
            self._status_label.setStyleSheet("color: red;")
            return

        labels = np.asarray(label_layer.data, dtype=np.int32)
        margin = self._margin_spin.value()

        filtered, removed_count = filter_edge_cells(labels, edge_margin=margin)

        if removed_count == 0:
            self._status_label.setText("No edge cells found at this margin.")
            self._status_label.setStyleSheet("color: gray;")
            self._apply_btn.setEnabled(False)
            # Remove preview layer if it exists
            if self._preview_layer is not None:
                try:
                    self._viewer.layers.remove(self._preview_layer)
                except ValueError:
                    pass
                self._preview_layer = None
            return

        # Create a highlight layer: show only the cells that would be removed
        edge_mask = (labels > 0) & (filtered == 0)
        highlight = np.where(edge_mask, 1, 0).astype(np.int32)

        # Update or create the preview layer
        from napari.utils.colormaps import DirectLabelColormap

        red_cmap = DirectLabelColormap(
            color_dict={0: "transparent", 1: "red", None: "transparent"},
        )
        if self._preview_layer is not None:
            self._preview_layer.data = highlight
        else:
            self._preview_layer = self._viewer.add_labels(
                highlight,
                name="edge_cells_preview",
                opacity=0.5,
                colormap=red_cmap,
            )

        self._status_label.setText(f"{removed_count} cells would be removed.")
        self._status_label.setStyleSheet("color: orange;")
        self._apply_btn.setEnabled(True)

    def _on_apply(self) -> None:
        """Remove edge cells from the label image and save."""
        from percell3.segment.label_processor import filter_edge_cells

        label_layer = self._get_label_layer()
        if label_layer is None:
            self._status_label.setText("No segmentation labels found.")
            self._status_label.setStyleSheet("color: red;")
            return

        labels = np.asarray(label_layer.data, dtype=np.int32)
        margin = self._margin_spin.value()

        filtered, removed_count = filter_edge_cells(labels, edge_margin=margin)

        if removed_count == 0:
            self._status_label.setText("No edge cells to remove.")
            self._status_label.setStyleSheet("color: gray;")
            return

        # Update the label layer in-place
        label_layer.data = filtered

        # Remove the preview layer
        if self._preview_layer is not None:
            try:
                self._viewer.layers.remove(self._preview_layer)
            except ValueError:
                pass
            self._preview_layer = None

        self._apply_btn.setEnabled(False)
        self._status_label.setText(
            f"Removed {removed_count} edge cells. "
            "Close napari to save."
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Removed %d edge cells (margin=%d) from FOV %d",
            removed_count, margin, self._fov_id,
        )
