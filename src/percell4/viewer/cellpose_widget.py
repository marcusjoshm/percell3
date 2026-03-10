"""Cellpose segmentation dock widget for the napari viewer.

Ported from percell3.segment.viewer.cellpose_widget with percell4 patterns:
    - Uses percell4.segment.cellpose_adapter.CellposeSegmenter
    - UUID-based IDs
    - Same QWidget-as-attribute pattern as FovBrowserWidget
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell4.core.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)


def _detect_gpu() -> str:
    """Detect available GPU backend for cellpose.

    Returns:
        Human-readable string: "GPU: CUDA", "GPU: MPS", or "CPU only".
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "GPU: CUDA"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "GPU: MPS"
    except ImportError:
        pass
    return "CPU only"


def _gpu_available() -> bool:
    """Return True if any GPU backend is available."""
    return _detect_gpu() != "CPU only"


# ---------------------------------------------------------------------------
# Parameter dataclass (testable without Qt)
# ---------------------------------------------------------------------------


@dataclass
class CellposeParams:
    """Collected parameters for a cellpose segmentation run."""

    model_name: str = "cyto3"
    channel_name: str = ""
    diameter: float = 30.0
    flow_threshold: float = 0.4
    cellprob_threshold: float = 0.0
    gpu: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Qt widget
# ---------------------------------------------------------------------------


class CellposeWidget:
    """Cellpose segmentation dock widget for napari.

    Provides model selection, parameter tuning, and async segmentation
    via ``@thread_worker``. Results update the viewer Labels layer.

    All store I/O (SQLite) happens on the main thread. Only the cellpose
    computation runs in the background thread.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov_id: FOV UUID.
        channel_names: List of loaded channel names.
    """

    BUILTIN_MODELS = ["cpsam", "cyto3", "cyto2", "nuclei"]

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov_id: bytes,
        channel_names: list[str],
    ) -> None:
        from qtpy.QtWidgets import (
            QComboBox,
            QDoubleSpinBox,
            QGroupBox,
            QHBoxLayout,
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
        self._worker: Any = None

        # --- Build the QWidget ---
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("Cellpose Segmentation")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # --- Model selection ---
        model_group = QGroupBox("Model")
        model_layout = QVBoxLayout()

        self._model_combo = QComboBox()
        self._model_combo.addItems(self.BUILTIN_MODELS)
        model_layout.addWidget(self._model_combo)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # --- Channel selection ---
        ch_group = QGroupBox("Channel")
        ch_layout = QVBoxLayout()

        ch_layout.addWidget(QLabel("Segment on:"))
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(channel_names)
        ch_layout.addWidget(self._channel_combo)

        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Parameters ---
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout()

        # Diameter
        row = QHBoxLayout()
        row.addWidget(QLabel("Diameter (px):"))
        self._diameter_spin = QDoubleSpinBox()
        self._diameter_spin.setRange(1.0, 500.0)
        self._diameter_spin.setValue(30.0)
        self._diameter_spin.setDecimals(1)
        row.addWidget(self._diameter_spin)
        param_layout.addLayout(row)

        # Flow threshold
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Flow threshold:"))
        self._flow_spin = QDoubleSpinBox()
        self._flow_spin.setRange(0.0, 3.0)
        self._flow_spin.setSingleStep(0.05)
        self._flow_spin.setValue(0.4)
        self._flow_spin.setDecimals(2)
        row2.addWidget(self._flow_spin)
        param_layout.addLayout(row2)

        # Cell probability threshold
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Cell prob:"))
        self._cellprob_spin = QDoubleSpinBox()
        self._cellprob_spin.setRange(-8.0, 8.0)
        self._cellprob_spin.setSingleStep(0.2)
        self._cellprob_spin.setValue(0.0)
        self._cellprob_spin.setDecimals(1)
        row3.addWidget(self._cellprob_spin)
        param_layout.addLayout(row3)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # --- GPU status ---
        gpu_text = _detect_gpu()
        self._gpu_label = QLabel(gpu_text)
        self._gpu_label.setStyleSheet(
            "color: green;" if "GPU" in gpu_text else "color: gray;"
        )
        layout.addWidget(self._gpu_label)

        # --- Run button ---
        self._run_btn = QPushButton("Run Segmentation")
        self._run_btn.setStyleSheet(
            "QPushButton { padding: 8px; font-weight: bold; }"
        )
        self._run_btn.clicked.connect(self._on_run)
        layout.addWidget(self._run_btn)

        # --- Status label ---
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()
        self.widget.setLayout(layout)

    # ------------------------------------------------------------------
    # Parameter collection
    # ------------------------------------------------------------------

    def _build_params(self) -> CellposeParams:
        """Collect widget values into a CellposeParams dataclass."""
        return CellposeParams(
            model_name=self._model_combo.currentText(),
            channel_name=self._channel_combo.currentText(),
            diameter=self._diameter_spin.value(),
            flow_threshold=self._flow_spin.value(),
            cellprob_threshold=self._cellprob_spin.value(),
            gpu=_gpu_available(),
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_run(self) -> None:
        """Launch cellpose segmentation in a background thread.

        Store I/O (SQLite reads) happens here on the main thread.
        Only the cellpose model.eval() call runs in the background.
        Store writes happen back on the main thread in _on_segmentation_done.
        """
        from napari.qt.threading import thread_worker

        from percell4.core.db_types import uuid_to_hex

        params = self._build_params()

        # --- Read image on the main thread (SQLite-safe) ---
        try:
            exp = self._store.db.get_experiment()
            channels = self._store.db.get_channels(exp["id"])
            channel_index = None
            for ch in channels:
                if ch["name"] == params.channel_name:
                    channel_index = ch["display_order"]
                    break
            if channel_index is None:
                self._status_label.setText(
                    f"Channel '{params.channel_name}' not found."
                )
                self._status_label.setStyleSheet("color: red;")
                return

            fov_hex = uuid_to_hex(self._fov_id)
            image = self._store.layers.read_image_channel_numpy(
                fov_hex, channel_index,
            )
        except Exception as exc:
            self._status_label.setText(f"Error reading image: {exc}")
            self._status_label.setStyleSheet("color: red;")
            return

        self._run_btn.setEnabled(False)
        self._status_label.setText("Running...")
        self._status_label.setStyleSheet("")

        # Stash params for use in _on_segmentation_done
        self._last_params = params

        @thread_worker
        def _run_cellpose() -> np.ndarray:
            """Run only the cellpose computation in a background thread."""
            from percell4.segment.cellpose_adapter import CellposeSegmenter

            segmenter = CellposeSegmenter()
            return segmenter.segment(
                image,
                model_name=params.model_name,
                diameter=params.diameter,
                gpu=params.gpu,
                flow_threshold=params.flow_threshold,
                cellprob_threshold=params.cellprob_threshold,
            )

        worker = _run_cellpose()
        self._worker = worker

        worker.returned.connect(self._on_segmentation_done)
        worker.errored.connect(self._on_segmentation_error)
        worker.start()

    def _on_segmentation_done(self, labels: np.ndarray) -> None:
        """Update viewer labels (runs on main thread)."""
        self._worker = None
        n_cells = len(np.unique(labels)) - (1 if 0 in labels else 0)

        # Update the "segmentation" Labels layer
        for layer in self._viewer.layers:
            if layer.name == "segmentation":
                layer.data = labels
                break
        else:
            self._viewer.add_labels(labels, name="segmentation", opacity=0.5)

        self._run_btn.setEnabled(True)
        self._status_label.setText(f"Done: {n_cells} cells")
        self._status_label.setStyleSheet("color: green;")
        logger.info("Cellpose segmentation complete: %d cells", n_cells)

    def _on_segmentation_error(self, exc: Exception) -> None:
        """Handle segmentation errors."""
        self._worker = None
        self._run_btn.setEnabled(True)
        self._status_label.setText(f"Error: {exc}")
        self._status_label.setStyleSheet("color: red;")
        logger.error("Cellpose segmentation failed: %s", exc, exc_info=True)
