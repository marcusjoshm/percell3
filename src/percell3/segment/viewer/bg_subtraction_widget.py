"""Background subtraction dock widget for the napari viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class BGSubtractionWidget:
    """Dock widget for subtracting a user-specified background value from image channels.

    Creates a derived FOV (``bg_sub_{fov_name}``) with the subtracted images.
    The original image data is preserved.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: FOV database ID.
        channel_names: List of channel names available for this FOV.
    """

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: int,
        channel_names: list[str],
    ) -> None:
        from qtpy.QtWidgets import (
            QCheckBox,
            QDoubleSpinBox,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = channel_names

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Background Subtraction")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- BG value input ---
        bg_group = QGroupBox("Background Value")
        bg_layout = QHBoxLayout()
        bg_layout.addWidget(QLabel("Value:"))
        self._bg_spin = QDoubleSpinBox()
        self._bg_spin.setRange(0.0, 65535.0)
        self._bg_spin.setSingleStep(1.0)
        self._bg_spin.setValue(0.0)
        self._bg_spin.setDecimals(1)
        bg_layout.addWidget(self._bg_spin)
        bg_group.setLayout(bg_layout)
        layout.addWidget(bg_group)

        # --- Channel checkboxes ---
        ch_group = QGroupBox("Channels to Subtract")
        ch_layout = QVBoxLayout()
        self._channel_checks: dict[str, QCheckBox] = {}
        for name in channel_names:
            cb = QCheckBox(name)
            cb.setChecked(True)
            self._channel_checks[name] = cb
            ch_layout.addWidget(cb)
        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Apply button ---
        self._apply_btn = QPushButton("Apply Background Subtraction")
        self._apply_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        # --- Status label ---
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    def _on_apply(self) -> None:
        """Subtract the background value and create/overwrite a derived FOV."""
        bg_value = self._bg_spin.value()
        selected = [
            name for name, cb in self._channel_checks.items() if cb.isChecked()
        ]

        if not selected:
            self._status_label.setText("No channels selected.")
            self._status_label.setStyleSheet("color: red;")
            return

        if bg_value == 0.0:
            self._status_label.setText("Background value is 0 — nothing to subtract.")
            self._status_label.setStyleSheet("color: gray;")
            return

        try:
            derived_fov_id, n_channels = subtract_background_to_derived_fov(
                self._store,
                self._fov_id,
                bg_value,
                selected,
            )
        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("BG subtraction failed for FOV %d: %s", self._fov_id, exc)
            return

        fov_info = self._store.get_fov_by_id(self._fov_id)
        derived_name = f"bg_sub_{fov_info.display_name}"
        self._status_label.setText(
            f"Created {derived_name} — {n_channels} channels (BG={bg_value:.1f})"
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "BG subtraction: created derived FOV '%s' (id=%d) with BG=%.1f for %d channels",
            derived_name, derived_fov_id, bg_value, n_channels,
        )


def subtract_background_to_derived_fov(
    store: ExperimentStore,
    fov_id: int,
    bg_value: float,
    selected_channels: list[str],
) -> tuple[int, int]:
    """Subtract a flat background value from selected channels and write to a derived FOV.

    Creates or overwrites a derived FOV named ``bg_sub_{fov_display_name}``.
    Selected channels have *bg_value* subtracted (clipped to 0). Unselected
    channels are copied unchanged.

    Args:
        store: An open ExperimentStore.
        fov_id: Source FOV database ID.
        bg_value: Background value to subtract from each pixel.
        selected_channels: Channel names to apply subtraction to.

    Returns:
        Tuple of (derived_fov_id, number_of_channels_written).
    """
    fov_info = store.get_fov_by_id(fov_id)
    all_channels = store.get_channels()
    derived_name = f"bg_sub_{fov_info.display_name}"

    # Find or create derived FOV
    existing_fovs = {f.display_name: f.id for f in store.get_fovs()}
    if derived_name in existing_fovs:
        derived_fov_id = existing_fovs[derived_name]
    else:
        derived_fov_id = store.add_fov(
            condition=fov_info.condition,
            bio_rep=fov_info.bio_rep,
            display_name=derived_name,
            width=fov_info.width,
            height=fov_info.height,
            pixel_size_um=fov_info.pixel_size_um,
        )

    selected_set = set(selected_channels)
    n_written = 0

    for ch in all_channels:
        try:
            image = store.read_image_numpy(fov_id, ch.name)
        except KeyError:
            logger.warning(
                "Channel '%s' has no image data for FOV %d, skipping.",
                ch.name, fov_id,
            )
            continue

        if ch.name in selected_set:
            # Subtract and clip: cast to float64, subtract, clip, cast back
            result = np.clip(
                image.astype(np.float64) - bg_value, 0, None,
            ).astype(image.dtype)
        else:
            result = image

        store.write_image(derived_fov_id, ch.name, result)
        n_written += 1

    return derived_fov_id, n_written
