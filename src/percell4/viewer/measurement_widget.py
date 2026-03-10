"""Measurement overlay widget -- color-code labels and annotate centroids.

Provides QWidget dock widget for visualizing measurements on the labels
layer, plus testable pure functions for building measurement lookups,
computing ROI centroids, and mapping values to RGBA colors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

# Metrics available for overlay selection
METRICS: list[str] = [
    "mean", "max", "min", "integrated", "std", "median", "area", "area_um2",
]

# Scopes available for overlay selection
SCOPES: list[str] = ["whole_roi", "mask_inside", "mask_outside"]


# ---------------------------------------------------------------------------
# Pure functions (testable without Qt or napari)
# ---------------------------------------------------------------------------


def build_measurement_lookup(
    measurements: list[dict],
    rois: list[dict],
) -> dict[int, float]:
    """Map label values to measurement values.

    Args:
        measurements: List of measurement dicts, each with at least
            ``roi_id`` and ``value`` keys.
        rois: List of ROI dicts, each with at least ``id`` and ``label_id``
            keys.

    Returns:
        Dict mapping label_id (int) -> measurement value (float).
        If an ROI has multiple measurements matching, the last one wins.
    """
    roi_id_to_label: dict[bytes, int] = {}
    for roi in rois:
        roi_id_to_label[roi["id"]] = roi["label_id"]

    lookup: dict[int, float] = {}
    for m in measurements:
        roi_id = m["roi_id"]
        label_id = roi_id_to_label.get(roi_id)
        if label_id is not None and label_id != 0:
            lookup[label_id] = m["value"]

    return lookup


def compute_roi_centroids(
    labels: np.ndarray,
) -> dict[int, tuple[float, float]]:
    """Compute centroids for each labeled region.

    Args:
        labels: 2D integer label array where pixel value == ROI label ID.

    Returns:
        Dict mapping label_id -> (y, x) centroid coordinates.
        Background (label 0) is excluded.
    """
    from scipy.ndimage import center_of_mass

    unique_labels = np.unique(labels)
    # Exclude background
    unique_labels = unique_labels[unique_labels != 0]

    if len(unique_labels) == 0:
        return {}

    # Compute centroids for all labels at once
    centroids_list = center_of_mass(
        labels, labels, unique_labels.tolist(),
    )

    result: dict[int, tuple[float, float]] = {}
    for label_val, centroid in zip(unique_labels, centroids_list):
        result[int(label_val)] = (float(centroid[0]), float(centroid[1]))

    return result


def map_values_to_colors(
    lookup: dict[int, float],
    labels: np.ndarray,
    colormap: str = "viridis",
) -> np.ndarray:
    """Create an RGBA overlay image by mapping measurement values to colors.

    Args:
        lookup: Dict mapping label_id -> measurement value.
        labels: 2D integer label array.
        colormap: Matplotlib colormap name.

    Returns:
        RGBA float32 array with shape ``(H, W, 4)`` where H and W match
        the labels shape.  Background pixels are fully transparent.
    """
    from matplotlib import colormaps

    h, w = labels.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.float32)

    if not lookup:
        return rgba

    cmap = colormaps[colormap]

    values = np.array(list(lookup.values()), dtype=np.float64)
    vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))

    # Avoid division by zero
    if vmax == vmin:
        vmax = vmin + 1.0

    for label_id, value in lookup.items():
        mask = labels == label_id
        if not np.any(mask):
            continue
        norm_val = (value - vmin) / (vmax - vmin)
        color = cmap(norm_val)
        rgba[mask] = color

    return rgba


# ---------------------------------------------------------------------------
# Qt Widget
# ---------------------------------------------------------------------------


class MeasurementWidget:
    """Dock widget for visualizing measurements on the labels layer.

    Provides combo-boxes for metric, channel, and scope selection,
    a checkbox for text annotations at ROI centroids, and a button
    to apply measurement-based coloring.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: Current FOV UUID.
        channel_names: List of channel names in display order.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: bytes,
        channel_names: list[str],
    ) -> None:
        from qtpy.QtWidgets import (
            QCheckBox,
            QComboBox,
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = channel_names

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("Measurements")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Metric selector
        layout.addWidget(QLabel("Metric:"))
        self._metric_combo = QComboBox()
        self._metric_combo.addItems(METRICS)
        layout.addWidget(self._metric_combo)

        # Channel selector
        layout.addWidget(QLabel("Channel:"))
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(channel_names)
        layout.addWidget(self._channel_combo)

        # Scope selector
        layout.addWidget(QLabel("Scope:"))
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(SCOPES)
        layout.addWidget(self._scope_combo)

        # Show labels checkbox
        self._show_labels_cb = QCheckBox("Show Labels")
        self._show_labels_cb.setChecked(False)
        layout.addWidget(self._show_labels_cb)

        # Apply button
        self._apply_btn = QPushButton("Color by Measurement")
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # Clear button
        self._clear_btn = QPushButton("Clear Overlay")
        self._clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(self._clear_btn)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("font-size: 11px; color: #aaa;")
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    @property
    def fov_id(self) -> bytes:
        return self._fov_id

    @fov_id.setter
    def fov_id(self, value: bytes) -> None:
        self._fov_id = value

    def _on_apply(self) -> None:
        """Apply measurement coloring to the viewer."""
        try:
            self._apply_overlay()
        except Exception as exc:
            logger.exception("Failed to apply measurement overlay")
            self._status_label.setText(f"Error: {exc}")

    def _on_clear(self) -> None:
        """Remove measurement overlay and annotation layers."""
        self._remove_layer("measurement_overlay")
        self._remove_layer("measurements")
        self._status_label.setText("Overlay cleared.")

    def _remove_layer(self, name: str) -> None:
        """Remove a layer by name, if it exists."""
        try:
            layer = self._viewer.layers[name]
            self._viewer.layers.remove(layer)
        except (KeyError, ValueError):
            pass

    def _apply_overlay(self) -> None:
        """Core overlay logic: fetch measurements, build lookup, color."""
        import napari as _napari

        metric = self._metric_combo.currentText()
        channel_name = self._channel_combo.currentText()
        scope = self._scope_combo.currentText()
        show_labels = self._show_labels_cb.isChecked()

        # Get channel ID from name
        exp = self._store.db.get_experiment()
        channels = self._store.db.get_channels(exp["id"])
        channel_id: bytes | None = None
        for ch in channels:
            if ch["name"] == channel_name:
                channel_id = ch["id"]
                break

        if channel_id is None:
            self._status_label.setText(f"Channel '{channel_name}' not found.")
            return

        # Get ROIs for this FOV
        rois = self._store.db.get_rois(self._fov_id)
        if not rois:
            self._status_label.setText("No ROIs found for this FOV.")
            return

        # Get active measurements and filter
        all_measurements = self._store.db.get_active_measurements(self._fov_id)
        filtered = [
            m for m in all_measurements
            if m["metric"] == metric
            and m["channel_id"] == channel_id
            and m["scope"] == scope
        ]

        if not filtered:
            self._status_label.setText(
                f"No measurements found for {metric}/{channel_name}/{scope}."
            )
            return

        # Build lookup
        roi_dicts = [{"id": r["id"], "label_id": r["label_id"]} for r in rois]
        meas_dicts = [{"roi_id": m["roi_id"], "value": m["value"]} for m in filtered]
        lookup = build_measurement_lookup(meas_dicts, roi_dicts)

        if not lookup:
            self._status_label.setText("No label-matched measurements found.")
            return

        # Get labels array from viewer
        label_layers = [
            lyr for lyr in self._viewer.layers
            if isinstance(lyr, _napari.layers.Labels)
        ]
        if not label_layers:
            self._status_label.setText("No labels layer found.")
            return

        labels = np.asarray(label_layers[0].data, dtype=np.int32)

        # Determine scale from the labels layer
        scale = label_layers[0].scale

        # Create color overlay
        rgba = map_values_to_colors(lookup, labels, colormap="viridis")

        # Remove old overlay if present
        self._remove_layer("measurement_overlay")

        # Add as Image layer
        self._viewer.add_image(
            rgba,
            name="measurement_overlay",
            rgb=True,
            blending="translucent",
            opacity=0.7,
            scale=scale,
        )

        n_rois = len(lookup)
        vals = list(lookup.values())
        vmin, vmax = min(vals), max(vals)
        self._status_label.setText(
            f"{n_rois} ROIs colored | {metric} range: "
            f"{vmin:.2f} - {vmax:.2f}"
        )

        # Optionally add text annotations at centroids
        self._remove_layer("measurements")
        if show_labels:
            centroids = compute_roi_centroids(labels)
            points = []
            texts = []
            for label_id, (cy, cx) in centroids.items():
                if label_id in lookup:
                    points.append([cy, cx])
                    texts.append(f"{lookup[label_id]:.2f}")

            if points:
                self._viewer.add_points(
                    np.array(points),
                    text=texts,
                    size=1,
                    name="measurements",
                    face_color="transparent",
                    edge_color="white",
                    scale=scale,
                )
