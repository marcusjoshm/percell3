"""Group Threshold dock widget -- apply thresholds across intensity groups.

A thin wrapper that lets users select an intensity group and apply the
current threshold value to all FOVs in that group.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-logic helpers (testable without Qt)
# ---------------------------------------------------------------------------


def get_group_fov_ids(
    store: "ExperimentStore",
    group_id: bytes,
) -> list[bytes]:
    """Return the FOV IDs whose ROIs belong to the given intensity group.

    Args:
        store: An open ExperimentStore.
        group_id: UUID of the intensity group.

    Returns:
        Deduplicated list of FOV IDs.
    """
    assignments = store.db.get_cell_group_assignments(group_id)
    fov_ids: list[bytes] = []
    seen: set[bytes] = set()

    for a in assignments:
        roi = store.db.get_roi(a["roi_id"])
        if roi is not None and roi["fov_id"] not in seen:
            fov_ids.append(roi["fov_id"])
            seen.add(roi["fov_id"])

    return fov_ids


# ---------------------------------------------------------------------------
# Qt widget
# ---------------------------------------------------------------------------


class GroupThresholdWidget:
    """Dock widget for applying a threshold across an intensity group.

    Displays a list of available intensity groups with their FOV counts
    and provides an "Apply to Group" button.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: Current FOV UUID (used for context).
        channel_names: Available channel names.
        threshold_widget: Reference to the ThresholdWidget for reading
            the current threshold value and channel selection.
    """

    def __init__(
        self,
        viewer: "napari.Viewer",
        store: "ExperimentStore",
        fov_id: bytes,
        channel_names: list[str],
        threshold_widget: "ThresholdWidget | None" = None,
    ) -> None:
        from qtpy.QtWidgets import (
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._fov_id = fov_id
        self._channel_names = list(channel_names)
        self._threshold_widget = threshold_widget
        self._group_ids: list[bytes] = []

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("Group Threshold")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        instructions = QLabel(
            "Select an intensity group to apply the current\n"
            "threshold value to all FOVs in that group."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: gray;")
        layout.addWidget(instructions)

        self._list_widget = QListWidget()
        layout.addWidget(self._list_widget)

        self._apply_btn = QPushButton("Apply to Group")
        self._apply_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

        self._populate_groups()

    def _populate_groups(self) -> None:
        """Fill the list widget with intensity groups."""
        from percell4.core.db_types import uuid_to_str

        self._list_widget.clear()
        self._group_ids.clear()

        exp = self._store.db.get_experiment()
        if exp is None:
            return

        groups = self._store.db.get_intensity_groups(exp["id"])
        if not groups:
            from qtpy.QtWidgets import QListWidgetItem

            item = QListWidgetItem("(no intensity groups)")
            item.setFlags(item.flags() & ~0x20)  # not selectable
            self._list_widget.addItem(item)
            return

        for g in groups:
            from qtpy.QtWidgets import QListWidgetItem

            # Count FOVs in group
            fov_ids = get_group_fov_ids(self._store, g["id"])
            label = f"{g['name']} ({len(fov_ids)} FOVs)"
            item = QListWidgetItem(label)
            self._list_widget.addItem(item)
            self._group_ids.append(g["id"])

    def _on_apply(self) -> None:
        """Apply threshold to all FOVs in the selected group."""
        row = self._list_widget.currentRow()
        if row < 0 or row >= len(self._group_ids):
            self._status_label.setText("Select a group first.")
            self._status_label.setStyleSheet("color: orange;")
            return

        # Get threshold value and channel from the threshold widget
        if self._threshold_widget is None:
            self._status_label.setText("No threshold widget linked.")
            self._status_label.setStyleSheet("color: red;")
            return

        channel_name = self._threshold_widget._channel_combo.currentText()
        threshold_value = self._threshold_widget._spin.value()
        group_id = self._group_ids[row]

        fov_ids = get_group_fov_ids(self._store, group_id)
        if not fov_ids:
            self._status_label.setText("No FOVs in this group.")
            self._status_label.setStyleSheet("color: orange;")
            return

        try:
            from percell4.measure.thresholding import create_threshold_mask

            applied = 0
            for fov_id in fov_ids:
                create_threshold_mask(
                    self._store,
                    fov_id,
                    source_channel_name=channel_name,
                    method="manual",
                    manual_value=threshold_value,
                )
                applied += 1

            self._status_label.setText(
                f"Applied threshold {threshold_value:.1f} "
                f"to {applied} FOVs in group."
            )
            self._status_label.setStyleSheet("color: green;")
            logger.info(
                "Applied group threshold %.1f on %s to %d FOVs",
                threshold_value,
                channel_name,
                applied,
            )

        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("Group threshold apply failed: %s", exc)
