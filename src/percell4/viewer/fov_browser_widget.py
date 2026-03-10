"""FOV Browser dock widget -- list, select, and inspect FOVs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

# Status -> color mapping for the FOV list
_STATUS_COLORS: dict[str, str] = {
    "measured": "#22c55e",    # green
    "qc_done": "#22c55e",    # green
    "segmented": "#eab308",   # yellow
    "analyzing": "#eab308",   # yellow
    "qc_pending": "#eab308",  # yellow
    "imported": "#9ca3af",    # gray
    "pending": "#9ca3af",     # gray
    "stale": "#f97316",       # orange
    "error": "#ef4444",       # red
    "deleting": "#ef4444",    # red
    "deleted": "#6b7280",     # dim gray
}


def get_fov_list_data(store: "ExperimentStore") -> list[dict]:
    """Build the FOV list data from the experiment database.

    Args:
        store: An open ExperimentStore.

    Returns:
        List of dicts with keys: id, auto_name, status, condition_name,
        channel_count.
    """
    from percell4.core.db_types import uuid_to_str

    exp = store.db.get_experiment()
    if exp is None:
        return []

    fovs = store.db.get_fovs(exp["id"])
    channels = store.db.get_channels(exp["id"])
    channel_count = len(channels)

    # Build condition lookup
    conditions = store.db.get_conditions(exp["id"])
    cond_lookup: dict[bytes, str] = {}
    for c in conditions:
        cond_lookup[c["id"]] = c["name"]

    result = []
    for fov in fovs:
        if fov["status"] in ("deleted", "deleting"):
            continue
        auto_name = fov["auto_name"] or uuid_to_str(fov["id"])[:8]
        cond_id = fov["condition_id"]
        cond_name = cond_lookup.get(cond_id, "") if cond_id else ""
        result.append({
            "id": fov["id"],
            "auto_name": auto_name,
            "status": fov["status"],
            "condition_name": cond_name,
            "channel_count": channel_count,
        })

    return result


class FovBrowserWidget:
    """Dock widget for browsing and selecting FOVs.

    Displays a scrollable list of FOVs with status indicators and
    an info panel showing details about the selected FOV.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        on_fov_selected: Callback invoked with the new fov_id when
            user selects a different FOV.
    """

    def __init__(
        self,
        viewer: "napari.Viewer",
        store: "ExperimentStore",
        on_fov_selected: Callable[[bytes], None],
    ) -> None:
        from qtpy.QtCore import Qt
        from qtpy.QtWidgets import (
            QLabel,
            QListWidget,
            QListWidgetItem,
            QVBoxLayout,
            QWidget,
        )

        self._viewer = viewer
        self._store = store
        self._on_fov_selected = on_fov_selected
        self._fov_ids: list[bytes] = []

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        title = QLabel("FOV Browser")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self._list_widget = QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list_widget)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("font-size: 12px; padding: 4px;")
        layout.addWidget(self._info_label)

        self.widget.setLayout(layout)

        # Populate
        self._populate_list()

    def _populate_list(self) -> None:
        """Fill the list widget with FOV entries."""
        from qtpy.QtGui import QColor
        from qtpy.QtWidgets import QListWidgetItem

        self._list_widget.clear()
        self._fov_ids.clear()

        fov_data = get_fov_list_data(self._store)

        for fov in fov_data:
            label = f"{fov['auto_name']} [{fov['status']}]"
            item = QListWidgetItem(label)

            color_hex = _STATUS_COLORS.get(fov["status"], "#9ca3af")
            item.setForeground(QColor(color_hex))

            self._list_widget.addItem(item)
            self._fov_ids.append(fov["id"])

    def _on_selection_changed(self, row: int) -> None:
        """Handle list selection change."""
        if row < 0 or row >= len(self._fov_ids):
            return

        fov_id = self._fov_ids[row]
        fov_data = get_fov_list_data(self._store)

        if row < len(fov_data):
            d = fov_data[row]
            info_lines = [
                f"Name: {d['auto_name']}",
                f"Status: {d['status']}",
            ]
            if d["condition_name"]:
                info_lines.append(f"Condition: {d['condition_name']}")
            info_lines.append(f"Channels: {d['channel_count']}")
            self._info_label.setText("\n".join(info_lines))

        self._on_fov_selected(fov_id)
