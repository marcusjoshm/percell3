"""Label cleanup dock widget -- edge removal and small ROI filtering.

Ported from percell3.segment.viewer.edge_removal_widget with percell4 patterns:
    - Uses percell4.segment.label_processor filter functions
    - Same QWidget-as-attribute pattern as FovBrowserWidget
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


class EdgeRemovalWidget:
    """Dock widget for previewing and applying label cleanup filters.

    Combines edge ROI removal and minimum area filtering into a single
    Preview / Apply workflow.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: FOV UUID.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: bytes,
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
        title = QLabel("Label Cleanup")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Parameters ---
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout()

        # Edge margin
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Edge margin (px):"))
        self._margin_spin = QSpinBox()
        self._margin_spin.setRange(0, 200)
        self._margin_spin.setValue(0)
        row1.addWidget(self._margin_spin)
        param_layout.addLayout(row1)

        # Min area
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Min area (px):"))
        self._min_area_spin = QSpinBox()
        self._min_area_spin.setRange(0, 10000)
        self._min_area_spin.setValue(0)
        row2.addWidget(self._min_area_spin)
        param_layout.addLayout(row2)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # --- Buttons ---
        self._preview_btn = QPushButton("Preview Edge Cells")
        self._preview_btn.setStyleSheet(
            "QPushButton { padding: 6px; }"
        )
        self._preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(self._preview_btn)

        self._apply_btn = QPushButton("Apply Filters")
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
        import napari as _napari

        for layer in self._viewer.layers:
            if isinstance(layer, _napari.layers.Labels) and layer.name == "segmentation":
                return layer
        return None

    def _apply_filters(
        self, labels: np.ndarray,
    ) -> tuple[np.ndarray, int, int]:
        """Apply edge and small-ROI filters, returning filtered labels and counts."""
        from percell4.segment.label_processor import (
            filter_edge_rois,
            filter_small_rois,
        )

        margin = self._margin_spin.value()
        min_area = self._min_area_spin.value()

        filtered = labels
        edge_removed = 0
        small_removed = 0

        if margin > 0:
            filtered, edge_removed = filter_edge_rois(filtered, edge_margin=margin)
        if min_area > 0:
            filtered, small_removed = filter_small_rois(filtered, min_area=min_area)

        return filtered, edge_removed, small_removed

    def _on_preview(self) -> None:
        """Highlight cells that would be removed by current settings."""
        label_layer = self._get_label_layer()
        if label_layer is None:
            self._status_label.setText("No segmentation labels found.")
            self._status_label.setStyleSheet("color: red;")
            return

        labels = np.asarray(label_layer.data, dtype=np.int32)
        filtered, edge_removed, small_removed = self._apply_filters(labels)
        total_removed = edge_removed + small_removed

        if total_removed == 0:
            self._status_label.setText("No cells to remove at these settings.")
            self._status_label.setStyleSheet("color: gray;")
            self._apply_btn.setEnabled(False)
            if self._preview_layer is not None:
                try:
                    self._viewer.layers.remove(self._preview_layer)
                except ValueError:
                    pass
                self._preview_layer = None
            return

        # Create a highlight layer: show only the cells that would be removed
        removal_mask = (labels > 0) & (filtered == 0)
        highlight = np.where(removal_mask, 1, 0).astype(np.int32)

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
                name="cleanup_preview",
                opacity=0.5,
                colormap=red_cmap,
            )

        parts = []
        if edge_removed:
            parts.append(f"{edge_removed} edge")
        if small_removed:
            parts.append(f"{small_removed} small")
        self._status_label.setText(
            f"{total_removed} cells would be removed ({', '.join(parts)})."
        )
        self._status_label.setStyleSheet("color: orange;")
        self._apply_btn.setEnabled(True)

    def _on_apply(self) -> None:
        """Remove cells from the label image."""
        label_layer = self._get_label_layer()
        if label_layer is None:
            self._status_label.setText("No segmentation labels found.")
            self._status_label.setStyleSheet("color: red;")
            return

        labels = np.asarray(label_layer.data, dtype=np.int32)
        filtered, edge_removed, small_removed = self._apply_filters(labels)
        total_removed = edge_removed + small_removed

        if total_removed == 0:
            self._status_label.setText("No cells to remove.")
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
        parts = []
        if edge_removed:
            parts.append(f"{edge_removed} edge")
        if small_removed:
            parts.append(f"{small_removed} small")
        self._status_label.setText(
            f"Removed {total_removed} cells ({', '.join(parts)}). "
            "Close napari to save."
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Removed %d cells (edge=%d, small=%d) from FOV",
            total_removed, edge_removed, small_removed,
        )
