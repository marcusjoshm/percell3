"""Assign threshold mask dock widget for the napari viewer.

In the layer-based architecture, "copying" a mask to another FOV is
actually a fov_config assignment — the same global threshold entity
is shared by pointing the target FOV's config at it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class CopyMaskWidget:
    """Dock widget for assigning a threshold to another FOV.

    In the layer-based architecture, thresholds are global entities.
    "Copying" a mask means pointing the target FOV's config at the same
    threshold entity (with dimension validation).

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: The currently open FOV ID (used as default source).
        channel_names: List of channel names available in the experiment.
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
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = channel_names

        # Build FOV and threshold lists
        fovs = store.get_fovs()
        self._fov_map: dict[str, int] = {f.display_name: f.id for f in fovs}

        thresholds = store.get_thresholds()
        self._thr_map: dict[str, int] = {
            f"{t.name} ({t.width}x{t.height})": t.id
            for t in thresholds
        }

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Assign Threshold")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Threshold selector ---
        thr_group = QGroupBox("Threshold")
        thr_layout = QVBoxLayout()
        self._thr_combo = QComboBox()
        for label in self._thr_map:
            self._thr_combo.addItem(label)
        thr_layout.addWidget(self._thr_combo)
        thr_group.setLayout(thr_layout)
        layout.addWidget(thr_group)

        # --- Segmentation selector ---
        segs = store.get_segmentations(seg_type="cellular")
        self._seg_map: dict[str, int] = {
            f"{s.name} ({s.cell_count or 0} cells)": s.id
            for s in segs
        }
        seg_group = QGroupBox("Active Segmentation")
        seg_layout = QVBoxLayout()
        self._seg_combo = QComboBox()
        for label in self._seg_map:
            self._seg_combo.addItem(label)
        seg_layout.addWidget(self._seg_combo)
        seg_group.setLayout(seg_layout)
        layout.addWidget(seg_group)

        # --- Target FOV ---
        tgt_group = QGroupBox("Target FOV")
        tgt_layout = QVBoxLayout()
        self._target_combo = QComboBox()
        for name in self._fov_map:
            self._target_combo.addItem(name)
        tgt_layout.addWidget(self._target_combo)
        tgt_group.setLayout(tgt_layout)
        layout.addWidget(tgt_group)

        # --- Apply button ---
        self._apply_btn = QPushButton("Assign Threshold")
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
        """Assign the selected threshold to the target FOV via config."""
        thr_label = self._thr_combo.currentText()
        seg_label = self._seg_combo.currentText()
        target_name = self._target_combo.currentText()

        thr_id = self._thr_map.get(thr_label)
        seg_id = self._seg_map.get(seg_label)
        target_fov_id = self._fov_map.get(target_name)

        if thr_id is None or seg_id is None or target_fov_id is None:
            self._status_label.setText("Invalid selection.")
            self._status_label.setStyleSheet("color: red;")
            return

        try:
            assign_threshold_to_fov(
                self._store, thr_id, seg_id, target_fov_id,
            )
        except ValueError as exc:
            self._status_label.setText(str(exc))
            self._status_label.setStyleSheet("color: red;")
            return
        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("Threshold assign failed: %s", exc)
            return

        self._status_label.setText(
            f"Assigned threshold to {target_name}"
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Assigned threshold %d to FOV %d (%s)",
            thr_id, target_fov_id, target_name,
        )


def assign_threshold_to_fov(
    store: ExperimentStore,
    threshold_id: int,
    segmentation_id: int,
    target_fov_id: int,
) -> None:
    """Assign a global threshold to a FOV via fov_config.

    Validates that dimensions match, then creates a config entry
    linking the threshold to the segmentation on this FOV.
    Triggers auto-measurement.

    Args:
        store: An open ExperimentStore.
        threshold_id: Global threshold entity ID.
        segmentation_id: Segmentation to pair with.
        target_fov_id: Target FOV database ID.

    Raises:
        ValueError: If threshold dimensions don't match FOV.
    """
    thr = store.get_threshold(threshold_id)
    fov = store.get_fov_by_id(target_fov_id)

    if thr.width != fov.width or thr.height != fov.height:
        raise ValueError(
            f"Dimension mismatch: threshold is {thr.width}x{thr.height} "
            f"but FOV '{fov.display_name}' is {fov.width}x{fov.height}"
        )

    store.set_fov_config_entry(
        target_fov_id, segmentation_id,
        threshold_id=threshold_id,
        scopes=["mask_inside", "mask_outside"],
    )

    # Trigger auto-measurement for the new config
    from percell3.measure.auto_measure import on_config_changed
    on_config_changed(store, target_fov_id)

    logger.info(
        "Assigned threshold '%s' (%d) to FOV '%s' (%d) with seg %d",
        thr.name, threshold_id, fov.display_name, target_fov_id, segmentation_id,
    )
