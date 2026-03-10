"""Threshold dock widget -- interactive thresholding with live preview.

Provides a QWidget for adjusting threshold values on image channels with
real-time preview of the binary mask and particle count.

Pure-logic helpers (compute_preview_mask, count_particles) are testable
without Qt or napari.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

PREVIEW_LAYER_NAME = "threshold_preview"


# ---------------------------------------------------------------------------
# Pure-logic helpers (testable without Qt)
# ---------------------------------------------------------------------------


def compute_preview_mask(image: np.ndarray, threshold: float) -> np.ndarray:
    """Compute a binary mask where pixels exceed the threshold.

    Args:
        image: 2D image array (any numeric dtype).
        threshold: Threshold value. Pixels strictly above this are True.

    Returns:
        Boolean 2D array with True where ``image > threshold``.
    """
    return (image > threshold).astype(np.uint8)


def count_particles(mask: np.ndarray) -> int:
    """Count connected components in a binary mask.

    Uses ``scipy.ndimage.label`` for fast labelling.

    Args:
        mask: 2D binary array (0/1 or bool).

    Returns:
        Number of connected components (particles). Returns 0 for
        an all-zero mask.
    """
    from scipy.ndimage import label as scipy_label

    if not np.any(mask):
        return 0

    _, n_components = scipy_label(mask)
    return int(n_components)


# ---------------------------------------------------------------------------
# Qt widget
# ---------------------------------------------------------------------------


class ThresholdWidget:
    """Dock widget for interactive thresholding with live preview.

    Features:
    * Channel selector (QComboBox) populated from experiment channels.
    * Threshold slider + spin box for fine control.
    * Live binary mask preview overlaid on the image.
    * Live particle count display.
    * Apply button to persist the threshold to the database.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: Current FOV UUID.
        channel_names: List of available channel names.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: bytes,
        channel_names: list[str],
    ) -> None:
        from qtpy.QtCore import QTimer, Qt
        from qtpy.QtWidgets import (
            QComboBox,
            QDoubleSpinBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSlider,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = list(channel_names)
        self._current_image: np.ndarray | None = None

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("Threshold")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Channel selector
        ch_label = QLabel("Channel:")
        layout.addWidget(ch_label)
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(self._channel_names)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        layout.addWidget(self._channel_combo)

        # Threshold slider + spin box
        thresh_label = QLabel("Threshold value:")
        layout.addWidget(thresh_label)

        slider_row = QHBoxLayout()
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(10000)
        self._slider.setValue(5000)
        self._slider.valueChanged.connect(self._on_slider_moved)
        slider_row.addWidget(self._slider)

        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(1)
        self._spin.setMinimum(0.0)
        self._spin.setMaximum(65535.0)
        self._spin.setSingleStep(0.1)
        self._spin.setValue(0.0)
        self._spin.valueChanged.connect(self._on_spin_changed)
        slider_row.addWidget(self._spin)
        layout.addLayout(slider_row)

        # Method selector (manual only for v1)
        method_label = QLabel("Method:")
        layout.addWidget(method_label)
        self._method_combo = QComboBox()
        self._method_combo.addItems(["manual"])
        layout.addWidget(self._method_combo)

        # Particle count display
        self._particle_label = QLabel("Particles: --")
        self._particle_label.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(self._particle_label)

        # Apply button
        self._apply_btn = QPushButton("Apply Threshold")
        self._apply_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; color: green; }"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # Status
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

        # Debounce timer (100 ms)
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(100)
        self._debounce_timer.timeout.connect(self._update_preview)

        # Internal state for slider <-> spin synchronisation
        self._image_min: float = 0.0
        self._image_max: float = 65535.0
        self._updating_controls = False

        # Load initial channel image
        if self._channel_names:
            self._load_channel_image(0)

    # ------------------------------------------------------------------
    # Channel loading
    # ------------------------------------------------------------------

    def _load_channel_image(self, channel_index: int) -> None:
        """Load a channel image from the experiment store."""
        from percell4.core.db_types import uuid_to_hex

        fov_hex = uuid_to_hex(self._fov_id)
        try:
            data = self._store.layers.read_image_channel_numpy(
                fov_hex, channel_index
            )
            self._current_image = data.astype(np.float32)
        except Exception:
            logger.warning(
                "Could not read channel %d for threshold widget",
                channel_index,
            )
            self._current_image = None
            return

        # Update slider/spin ranges
        self._image_min = float(np.nanmin(self._current_image))
        self._image_max = float(np.nanmax(self._current_image))

        self._updating_controls = True
        self._spin.setMinimum(self._image_min)
        self._spin.setMaximum(self._image_max)

        # Set default threshold to midpoint
        mid = (self._image_min + self._image_max) / 2.0
        self._spin.setValue(mid)
        self._slider.setValue(self._value_to_slider(mid))
        self._updating_controls = False

        self._update_preview()

    def _on_channel_changed(self, index: int) -> None:
        """Reload image when channel selection changes."""
        if index < 0:
            return
        self._load_channel_image(index)

    # ------------------------------------------------------------------
    # Slider <-> spin box synchronisation
    # ------------------------------------------------------------------

    def _value_to_slider(self, value: float) -> int:
        """Map a threshold value to slider position (0-10000)."""
        rng = self._image_max - self._image_min
        if rng <= 0:
            return 0
        frac = (value - self._image_min) / rng
        return int(frac * 10000)

    def _slider_to_value(self, pos: int) -> float:
        """Map a slider position (0-10000) to threshold value."""
        frac = pos / 10000.0
        return self._image_min + frac * (self._image_max - self._image_min)

    def _on_slider_moved(self, pos: int) -> None:
        """Slider changed -> update spin box, debounce preview."""
        if self._updating_controls:
            return
        value = self._slider_to_value(pos)
        self._updating_controls = True
        self._spin.setValue(value)
        self._updating_controls = False
        self._debounce_timer.start()

    def _on_spin_changed(self, value: float) -> None:
        """Spin box changed -> update slider, debounce preview."""
        if self._updating_controls:
            return
        self._updating_controls = True
        self._slider.setValue(self._value_to_slider(value))
        self._updating_controls = False
        self._debounce_timer.start()

    # ------------------------------------------------------------------
    # Live preview
    # ------------------------------------------------------------------

    def _update_preview(self) -> None:
        """Recompute the preview mask and update the napari layer."""
        if self._current_image is None:
            return

        threshold_value = self._spin.value()
        mask = compute_preview_mask(self._current_image, threshold_value)
        n_particles = count_particles(mask)

        self._particle_label.setText(f"Particles: {n_particles}")

        # Update or create the preview layer
        try:
            preview_layer = self._viewer.layers[PREVIEW_LAYER_NAME]
            preview_layer.data = mask
        except KeyError:
            # Get scale from the first image layer (if available)
            kwargs: dict = {
                "name": PREVIEW_LAYER_NAME,
                "colormap": "magenta",
                "blending": "additive",
                "opacity": 0.4,
            }
            # Match scale to existing image layers
            for lyr in self._viewer.layers:
                if hasattr(lyr, "scale") and lyr.name != PREVIEW_LAYER_NAME:
                    kwargs["scale"] = lyr.scale
                    break
            self._viewer.add_image(mask, **kwargs)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Create threshold mask and assign to the current FOV."""
        if self._current_image is None:
            self._status_label.setText("No channel image loaded.")
            self._status_label.setStyleSheet("color: red;")
            return

        channel_name = self._channel_combo.currentText()
        threshold_value = self._spin.value()

        try:
            from percell4.measure.thresholding import create_threshold_mask

            result = create_threshold_mask(
                self._store,
                self._fov_id,
                source_channel_name=channel_name,
                method="manual",
                manual_value=threshold_value,
            )

            # Remove preview layer
            try:
                self._viewer.layers.remove(PREVIEW_LAYER_NAME)
            except (KeyError, ValueError):
                pass

            # Add permanent mask layer
            from percell4.core.db_types import uuid_to_hex

            mask_hex = uuid_to_hex(result.threshold_mask_id)
            mask_data = self._store.layers.read_mask(mask_hex)

            kwargs: dict = {
                "name": f"{channel_name} mask",
                "colormap": "magenta",
                "blending": "additive",
                "opacity": 0.4,
            }
            for lyr in self._viewer.layers:
                if hasattr(lyr, "scale") and lyr.name not in (
                    PREVIEW_LAYER_NAME, f"{channel_name} mask",
                ):
                    kwargs["scale"] = lyr.scale
                    break
            self._viewer.add_image(mask_data, **kwargs)

            self._status_label.setText(
                f"Threshold applied: {threshold_value:.1f}\n"
                f"Positive: {result.positive_fraction:.1%} "
                f"({result.positive_pixels}/{result.total_pixels} px)"
            )
            self._status_label.setStyleSheet("color: green;")
            logger.info(
                "Applied threshold %.1f on channel %s (fov=%s)",
                threshold_value,
                channel_name,
                self._fov_id.hex()[:8],
            )

        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("Threshold apply failed: %s", exc)
