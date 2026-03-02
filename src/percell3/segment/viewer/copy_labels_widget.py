"""Assign segmentation dock widget for the napari viewer.

In the layer-based architecture, "copying" labels to another FOV is
actually a fov_config assignment — the same global segmentation entity
is shared by pointing the target FOV's config at it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class CopyLabelsWidget:
    """Dock widget for assigning a segmentation to another FOV.

    In the layer-based architecture, segmentations are global entities.
    "Copying" labels means pointing the target FOV's config at the same
    segmentation entity (with dimension validation).

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

        # Build FOV list and segmentation list
        fovs = store.get_fovs()
        self._fov_map: dict[str, int] = {f.display_name: f.id for f in fovs}

        segs = store.get_segmentations(seg_type="cellular")
        self._seg_map: dict[str, int] = {
            f"{s.name} ({s.cell_count or 0} cells, {s.width}x{s.height})": s.id
            for s in segs
        }

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Assign Segmentation")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Segmentation selector ---
        seg_group = QGroupBox("Segmentation")
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
        self._apply_btn = QPushButton("Assign Segmentation")
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
        """Assign the selected segmentation to the target FOV via config."""
        seg_label = self._seg_combo.currentText()
        target_name = self._target_combo.currentText()

        seg_id = self._seg_map.get(seg_label)
        target_fov_id = self._fov_map.get(target_name)

        if seg_id is None or target_fov_id is None:
            self._status_label.setText("Invalid selection.")
            self._status_label.setStyleSheet("color: red;")
            return

        try:
            assign_segmentation_to_fov(self._store, seg_id, target_fov_id)
        except ValueError as exc:
            self._status_label.setText(str(exc))
            self._status_label.setStyleSheet("color: red;")
            return
        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error(
                "Segmentation assign failed: %s", exc,
            )
            return

        self._status_label.setText(
            f"Assigned segmentation to {target_name}"
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Assigned segmentation %d to FOV %d (%s)",
            seg_id, target_fov_id, target_name,
        )


def assign_segmentation_to_fov(
    store: ExperimentStore,
    segmentation_id: int,
    target_fov_id: int,
) -> None:
    """Assign a global segmentation to a FOV via fov_config.

    Validates that dimensions match, then creates a config entry.
    Triggers auto-measurement for the new config.

    Args:
        store: An open ExperimentStore.
        segmentation_id: Global segmentation entity ID.
        target_fov_id: Target FOV database ID.

    Raises:
        ValueError: If segmentation dimensions don't match FOV.
    """
    seg = store.get_segmentation(segmentation_id)
    fov = store.get_fov_by_id(target_fov_id)

    if seg.width != fov.width or seg.height != fov.height:
        raise ValueError(
            f"Dimension mismatch: segmentation is {seg.width}x{seg.height} "
            f"but FOV '{fov.display_name}' is {fov.width}x{fov.height}"
        )

    store.set_fov_config_entry(target_fov_id, segmentation_id)

    # Trigger auto-measurement for the new config
    from percell3.measure.auto_measure import on_config_changed
    on_config_changed(store, target_fov_id)

    logger.info(
        "Assigned segmentation '%s' (%d) to FOV '%s' (%d)",
        seg.name, segmentation_id, fov.display_name, target_fov_id,
    )
