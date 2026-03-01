"""Copy threshold mask dock widget for the napari viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)


class CopyMaskWidget:
    """Dock widget for copying a threshold mask from one FOV to another.

    Provides source/target FOV dropdowns, a channel selector, and an Apply
    button. Useful for applying an existing threshold mask to derived FOVs
    that share the same geometry.

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
            QSpinBox,
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
        title = QLabel("Copy Mask")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Source FOV ---
        src_group = QGroupBox("Source FOV")
        src_layout = QVBoxLayout()
        self._source_combo = QComboBox()
        for name in self._fov_map:
            self._source_combo.addItem(name)
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
        ch_group = QGroupBox("Mask Channel")
        ch_layout = QVBoxLayout()
        self._channel_combo = QComboBox()
        for ch_name in channel_names:
            self._channel_combo.addItem(ch_name)
        ch_layout.addWidget(self._channel_combo)
        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Min particle area ---
        area_group = QGroupBox("Min Particle Area (px)")
        area_layout = QVBoxLayout()
        self._min_area_spin = QSpinBox()
        self._min_area_spin.setRange(1, 1000)
        self._min_area_spin.setValue(5)
        area_layout.addWidget(self._min_area_spin)
        area_group.setLayout(area_layout)
        layout.addWidget(area_group)

        # --- Apply button ---
        self._apply_btn = QPushButton("Copy Mask")
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
        """Copy mask from source FOV to target FOV."""
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

        min_area = self._min_area_spin.value()

        try:
            run_id, particle_count = copy_mask_to_fov(
                self._store, source_fov_id, target_fov_id, channel,
                min_particle_area=min_area,
            )
        except KeyError as exc:
            self._status_label.setText(f"No mask found: {exc}")
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
                "Mask copy failed %s → %s (%s): %s",
                source_name, target_name, channel, exc,
            )
            return

        self._status_label.setText(
            f"Copied {channel} mask from {source_name} to {target_name} "
            f"({particle_count} particles)"
        )
        self._status_label.setStyleSheet("color: green;")
        logger.info(
            "Copied %s mask from FOV %d (%s) to FOV %d (%s), %d particles",
            channel, source_fov_id, source_name,
            target_fov_id, target_name, particle_count,
        )


def copy_mask_to_fov(
    store: ExperimentStore,
    source_fov_id: int,
    target_fov_id: int,
    channel: str,
    min_particle_area: int = 5,
) -> tuple[int, int]:
    """Copy a threshold mask from one FOV to another and extract particles.

    Reads the source mask, creates a new threshold run on the target FOV,
    writes the mask, then runs particle analysis on the target so that
    measurements can be performed. The ``write_mask`` method handles cleanup
    of any stale particles on the target.

    Args:
        store: An open ExperimentStore.
        source_fov_id: Source FOV database ID (must have a mask for this channel).
        target_fov_id: Target FOV database ID (must have labels and cells).
        channel: Channel name whose mask to copy.
        min_particle_area: Minimum particle area in pixels (default: 5).

    Returns:
        Tuple of (threshold_run_id, particle_count).

    Raises:
        KeyError: If the source FOV has no mask for the given channel.
        ValueError: If source mask dimensions don't match target FOV.
    """
    from percell3.measure.particle_analyzer import ParticleAnalyzer

    # Resolve latest threshold run for source FOV + channel
    all_thr_runs = store.get_threshold_runs()
    source_thr_runs = [
        tr for tr in all_thr_runs
        if tr.channel == channel and tr.fov_id == source_fov_id
    ]
    if not source_thr_runs:
        raise KeyError(
            f"No threshold run for channel '{channel}' on FOV {source_fov_id}"
        )
    source_thr_id = source_thr_runs[-1].id

    # Read source mask (raises KeyError if none exists)
    source_mask = store.read_mask(source_fov_id, channel, source_thr_id)

    # Validate dimensions match target FOV
    target_info = store.get_fov_by_id(target_fov_id)
    expected_shape = (target_info.height, target_info.width)
    if source_mask.shape != expected_shape:
        raise ValueError(
            f"Dimension mismatch: source mask is {source_mask.shape} "
            f"but target FOV is {expected_shape}"
        )

    # Create threshold run with provenance
    parameters = {
        "method": "mask_copy",
        "source_fov_id": source_fov_id,
    }
    run_id = store.add_threshold_run(
        fov_id=target_fov_id, channel=channel,
        method="mask_copy", parameters=parameters,
    )

    # Write mask (handles stale particle cleanup automatically)
    store.write_mask(target_fov_id, channel, source_mask, run_id)

    # Extract particles from the copied mask so measurements work.
    # This mirrors what the thresholding pipeline does after writing a mask.
    particle_count = 0
    cells_df = store.get_cells(fov_id=target_fov_id)
    if not cells_df.empty:
        cell_ids = cells_df["id"].tolist()
        analyzer = ParticleAnalyzer(min_particle_area=min_particle_area)
        result = analyzer.analyze_fov(
            store, target_fov_id, channel, run_id, cell_ids,
        )
        if result.particles:
            store.add_particles(result.particles)
        if result.summary_measurements:
            store.add_measurements(result.summary_measurements)
        store.write_particle_labels(
            target_fov_id, channel, result.particle_label_image, run_id,
        )
        particle_count = result.total_particles

    logger.info(
        "Copied %s mask from FOV %d to FOV %d (run_id=%d, %d particles)",
        channel, source_fov_id, target_fov_id, run_id, particle_count,
    )
    return run_id, particle_count
