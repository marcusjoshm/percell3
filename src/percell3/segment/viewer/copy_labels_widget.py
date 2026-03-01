"""Copy segmentation labels dock widget for the napari viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class CopyLabelsWidget:
    """Dock widget for copying segmentation labels from one FOV to another.

    Provides source/target FOV dropdowns, a channel selector, and an Apply
    button. Useful for applying an existing segmentation to derived FOVs
    (``bg_sub_*``, ``condensed_phase_*``) that share the same geometry.

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

        # Build FOV list: {display_name: fov_id}
        fovs = store.get_fovs()
        self._fov_map: dict[str, int] = {f.display_name: f.id for f in fovs}

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Copy Labels")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Source FOV ---
        src_group = QGroupBox("Source FOV")
        src_layout = QVBoxLayout()
        self._source_combo = QComboBox()
        for name in self._fov_map:
            self._source_combo.addItem(name)
        # Default to current FOV
        current_fov = store.get_fov_by_id(fov_id)
        idx = self._source_combo.findText(current_fov.display_name)
        if idx >= 0:
            self._source_combo.setCurrentIndex(idx)
        src_layout.addWidget(self._source_combo)
        src_group.setLayout(src_layout)
        layout.addWidget(src_group)

        # --- Target FOV ---
        tgt_group = QGroupBox("Target FOV")
        tgt_layout = QVBoxLayout()
        self._target_combo = QComboBox()
        for name in self._fov_map:
            self._target_combo.addItem(name)
        tgt_layout.addWidget(self._target_combo)
        tgt_group.setLayout(tgt_layout)
        layout.addWidget(tgt_group)

        # --- Channel ---
        ch_group = QGroupBox("Segmentation Channel")
        ch_layout = QVBoxLayout()
        self._channel_combo = QComboBox()
        for ch_name in channel_names:
            self._channel_combo.addItem(ch_name)
        ch_layout.addWidget(self._channel_combo)
        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Apply button ---
        self._apply_btn = QPushButton("Copy Labels")
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
        """Copy labels from source FOV to target FOV."""
        source_name = self._source_combo.currentText()
        target_name = self._target_combo.currentText()
        channel = self._channel_combo.currentText()

        source_fov_id = self._fov_map.get(source_name)
        target_fov_id = self._fov_map.get(target_name)

        if source_fov_id is None or target_fov_id is None:
            self._status_label.setText("Invalid FOV selection.")
            self._status_label.setStyleSheet("color: red;")
            return

        if source_fov_id == target_fov_id:
            self._status_label.setText("Source and target must be different FOVs.")
            self._status_label.setStyleSheet("color: red;")
            return

        try:
            run_id, cell_count = copy_labels_to_fov(
                self._store, source_fov_id, target_fov_id, channel,
            )
        except KeyError as exc:
            self._status_label.setText(f"No labels found: {exc}")
            self._status_label.setStyleSheet("color: red;")
            return
        except ValueError as exc:
            self._status_label.setText(str(exc))
            self._status_label.setStyleSheet("color: red;")
            return
        except Exception as exc:
            self._status_label.setText(f"Error: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error(
                "Label copy failed %s → %s: %s", source_name, target_name, exc,
            )
            return

        self._status_label.setText(
            f"Copied {cell_count} cells from {source_name} to {target_name}"
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Copied %d cells from FOV %d (%s) to FOV %d (%s), run_id=%d",
            cell_count, source_fov_id, source_name,
            target_fov_id, target_name, run_id,
        )


def copy_labels_to_fov(
    store: ExperimentStore,
    source_fov_id: int,
    target_fov_id: int,
    channel: str,
) -> tuple[int, int]:
    """Copy segmentation labels from one FOV to another.

    Delegates to ``store.copy_segmentation_to_fov()``.

    Args:
        store: An open ExperimentStore.
        source_fov_id: Source FOV database ID (must have labels).
        target_fov_id: Target FOV database ID.
        channel: Channel name (used to resolve the source run).

    Returns:
        Tuple of (segmentation_run_id, cell_count).

    Raises:
        KeyError: If the source FOV has no segmentation runs.
        ValueError: If source label dimensions don't match target FOV.
    """
    # Resolve latest segmentation run for source FOV
    src_seg_runs = store.list_segmentation_runs(source_fov_id)
    if not src_seg_runs:
        raise KeyError(f"No segmentation runs for source FOV {source_fov_id}")
    src_seg_run_id = src_seg_runs[-1].id

    run_id, cell_count = store.copy_segmentation_to_fov(
        src_seg_run_id, target_fov_id,
    )

    logger.info(
        "Copied %d cells from FOV %d to FOV %d (run_id=%d)",
        cell_count, source_fov_id, target_fov_id, run_id,
    )
    return run_id, cell_count
