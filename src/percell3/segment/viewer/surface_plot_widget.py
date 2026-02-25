"""3D Surface Plot dock widget for napari."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)

# Curated colormap list — kept minimal per institutional learnings.
_COLORMAPS = ["viridis", "plasma", "magma", "inferno", "turbo", "hot", "gray"]

# Slider defaults
_Z_SCALE_DEFAULT = 50
_Z_SCALE_MIN = 1
_Z_SCALE_MAX = 200
_SIGMA_DEFAULT = 10  # represents 1.0 (slider uses int * 0.1)
_SIGMA_MIN = 0
_SIGMA_MAX = 100  # represents 10.0
_ROI_WARN_SIZE = 512


class SurfacePlotWidget:
    """Dock widget for 3D surface plot visualization.

    Provides channel selection, colormap, Z-scale, smoothing controls,
    a "Generate Surface" button, and a "Save Screenshot" button.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: FOV database ID.
        channel_names: List of channel names available.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: int,
        channel_names: list[str],
    ) -> None:
        from qtpy.QtWidgets import (
            QComboBox,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSlider,
            QVBoxLayout,
            QWidget,
        )
        from qtpy.QtCore import Qt

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = channel_names
        self._surface_layer: napari.layers.Surface | None = None
        self._cached_vertices: np.ndarray | None = None
        self._cached_faces: np.ndarray | None = None

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("3D Surface Plot")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Channel selection ---
        ch_group = QGroupBox("Channels")
        ch_layout = QVBoxLayout()

        ch_layout.addWidget(QLabel("Height channel:"))
        self._height_combo = QComboBox()
        self._height_combo.addItems(channel_names)
        ch_layout.addWidget(self._height_combo)

        ch_layout.addWidget(QLabel("Color channel:"))
        self._color_combo = QComboBox()
        self._color_combo.addItems(channel_names)
        if len(channel_names) > 1:
            self._color_combo.setCurrentIndex(1)
        ch_layout.addWidget(self._color_combo)

        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Parameters ---
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout()

        # Colormap
        row = QHBoxLayout()
        row.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(_COLORMAPS)
        self._cmap_combo.currentTextChanged.connect(self._on_colormap_changed)
        row.addWidget(self._cmap_combo)
        param_layout.addLayout(row)

        # Z-scale slider
        row = QHBoxLayout()
        row.addWidget(QLabel("Z-scale:"))
        self._z_slider = QSlider(Qt.Horizontal)
        self._z_slider.setRange(_Z_SCALE_MIN, _Z_SCALE_MAX)
        self._z_slider.setValue(_Z_SCALE_DEFAULT)
        self._z_label = QLabel(str(_Z_SCALE_DEFAULT))
        self._z_slider.valueChanged.connect(
            lambda v: self._z_label.setText(str(v))
        )
        self._z_slider.sliderReleased.connect(self._on_z_scale_changed)
        row.addWidget(self._z_slider)
        row.addWidget(self._z_label)
        param_layout.addLayout(row)

        # Smoothing sigma slider (int * 0.1 = actual sigma)
        row = QHBoxLayout()
        row.addWidget(QLabel("Smoothing:"))
        self._sigma_slider = QSlider(Qt.Horizontal)
        self._sigma_slider.setRange(_SIGMA_MIN, _SIGMA_MAX)
        self._sigma_slider.setValue(_SIGMA_DEFAULT)
        self._sigma_label = QLabel(f"{_SIGMA_DEFAULT * 0.1:.1f}")
        self._sigma_slider.valueChanged.connect(
            lambda v: self._sigma_label.setText(f"{v * 0.1:.1f}")
        )
        self._sigma_slider.sliderReleased.connect(self._on_sigma_changed)
        row.addWidget(self._sigma_slider)
        row.addWidget(self._sigma_label)
        param_layout.addLayout(row)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # --- Generate button ---
        self._generate_btn = QPushButton("Generate Surface")
        self._generate_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._generate_btn.clicked.connect(self._on_generate)
        layout.addWidget(self._generate_btn)

        # --- Screenshot button ---
        self._screenshot_btn = QPushButton("Save Screenshot")
        self._screenshot_btn.clicked.connect(self._on_save_screenshot)
        layout.addWidget(self._screenshot_btn)

        # --- Status label ---
        self._status_label = QLabel("Draw a rectangle ROI, then click Generate Surface.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    # ------------------------------------------------------------------
    # ROI extraction
    # ------------------------------------------------------------------

    def _get_roi_bounds(self) -> tuple[int, int, int, int] | None:
        """Extract ROI bounding box from the Shapes layer.

        Returns:
            (row_min, col_min, row_max, col_max) or None if no ROI drawn.
        """
        try:
            roi_layer = self._viewer.layers["ROI"]
        except KeyError:
            return None

        if len(roi_layer.data) == 0:
            return None

        # Use the last drawn shape
        shape = roi_layer.data[-1]
        rows = shape[:, 0]
        cols = shape[:, 1]

        row_min = int(np.floor(rows.min()))
        row_max = int(np.ceil(rows.max()))
        col_min = int(np.floor(cols.min()))
        col_max = int(np.ceil(cols.max()))

        # Clip to image bounds
        first_image = None
        for layer in self._viewer.layers:
            if hasattr(layer, "data") and hasattr(layer.data, "shape"):
                shape_2d = layer.data.shape
                if len(shape_2d) >= 2:
                    first_image = shape_2d
                    break

        if first_image is not None:
            H, W = first_image[-2], first_image[-1]
            row_min = max(0, row_min)
            col_min = max(0, col_min)
            row_max = min(H, row_max)
            col_max = min(W, col_max)

        return row_min, col_min, row_max, col_max

    # ------------------------------------------------------------------
    # Surface generation
    # ------------------------------------------------------------------

    def _on_generate(self) -> None:
        """Generate the 3D surface from the ROI and selected channels."""
        from percell3.plugins.builtin._surface_mesh import build_surface

        bounds = self._get_roi_bounds()
        if bounds is None:
            self._status_label.setText("Draw a rectangle ROI first.")
            self._status_label.setStyleSheet("color: orange;")
            return

        row_min, col_min, row_max, col_max = bounds
        roi_h = row_max - row_min
        roi_w = col_max - col_min

        if roi_h < 2 or roi_w < 2:
            self._status_label.setText("ROI too small (need at least 2x2 pixels).")
            self._status_label.setStyleSheet("color: red;")
            return

        if roi_h > _ROI_WARN_SIZE or roi_w > _ROI_WARN_SIZE:
            self._status_label.setText(
                f"Large ROI ({roi_h}x{roi_w}) — rendering may be slow."
            )
            self._status_label.setStyleSheet("color: orange;")

        height_ch = self._height_combo.currentText()
        color_ch = self._color_combo.currentText()

        try:
            height_img = self._store.read_image_numpy(self._fov_id, height_ch)
            color_img = self._store.read_image_numpy(self._fov_id, color_ch)
        except (KeyError, OSError) as exc:
            self._status_label.setText(f"Error reading image: {exc}")
            self._status_label.setStyleSheet("color: red;")
            return

        # Crop to ROI
        height_roi = height_img[row_min:row_max, col_min:col_max]
        color_roi = color_img[row_min:row_max, col_min:col_max]

        z_scale = float(self._z_slider.value())
        sigma = self._sigma_slider.value() * 0.1

        try:
            vertices, faces, values = build_surface(
                height_roi, color_roi, z_scale=z_scale, sigma=sigma,
            )
        except ValueError as exc:
            self._status_label.setText(f"Mesh error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            return

        # Offset vertices to ROI position in the full image
        vertices[:, 0] += row_min
        vertices[:, 1] += col_min

        # Cache for parameter updates
        self._cached_height_roi = height_roi
        self._cached_color_roi = color_roi
        self._cached_roi_offset = (row_min, col_min)

        cmap = self._cmap_combo.currentText()

        # Remove existing surface layer if present
        if self._surface_layer is not None:
            try:
                self._viewer.layers.remove(self._surface_layer)
            except ValueError:
                pass

        self._surface_layer = self._viewer.add_surface(
            (vertices, faces, values),
            colormap=cmap,
            shading="smooth",
            name="3D Surface",
        )

        # Switch to 3D mode
        self._viewer.dims.ndisplay = 3

        n_verts = len(vertices)
        n_faces = len(faces)
        self._status_label.setText(
            f"Surface: {n_verts:,} vertices, {n_faces:,} faces"
        )
        self._status_label.setStyleSheet("color: green;")

    # ------------------------------------------------------------------
    # Parameter update callbacks
    # ------------------------------------------------------------------

    def _on_colormap_changed(self, cmap_name: str) -> None:
        """Update surface colormap without re-meshing."""
        if self._surface_layer is not None:
            self._surface_layer.colormap = cmap_name

    def _on_z_scale_changed(self) -> None:
        """Rebuild mesh with new Z-scale on slider release."""
        if self._surface_layer is None:
            return
        self._rebuild_surface()

    def _on_sigma_changed(self) -> None:
        """Rebuild mesh with new smoothing sigma on slider release."""
        if self._surface_layer is None:
            return
        self._rebuild_surface()

    def _rebuild_surface(self) -> None:
        """Rebuild the mesh from cached ROI data with current parameters."""
        from percell3.plugins.builtin._surface_mesh import build_surface

        if not hasattr(self, "_cached_height_roi"):
            return

        z_scale = float(self._z_slider.value())
        sigma = self._sigma_slider.value() * 0.1

        try:
            vertices, faces, values = build_surface(
                self._cached_height_roi,
                self._cached_color_roi,
                z_scale=z_scale,
                sigma=sigma,
            )
        except ValueError:
            return

        row_min, col_min = self._cached_roi_offset
        vertices[:, 0] += row_min
        vertices[:, 1] += col_min

        self._surface_layer.data = (vertices, faces, values)

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def _on_save_screenshot(self) -> None:
        """Save the current napari canvas to the experiment exports directory."""
        try:
            fov_info = self._store.get_fov_by_id(self._fov_id)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            exports_dir = Path(self._store.path) / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            path = exports_dir / f"surface_plot_{fov_info.display_name}_{timestamp}.png"

            self._viewer.screenshot(path=str(path), canvas_only=True, flash=True)

            self._status_label.setText(f"Screenshot saved: {path.name}")
            self._status_label.setStyleSheet("color: green;")
            logger.info("Screenshot saved: %s", path)
        except OSError as exc:
            self._status_label.setText(f"Screenshot error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("Failed to save screenshot: %s", exc)
