"""Cellpose segmentation dock widget for the napari viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import napari

    from percell3.core import ExperimentStore

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


class CellposeWidget:
    """Cellpose segmentation dock widget for napari.

    Provides model selection, parameter tuning, and async segmentation
    via ``@thread_worker``. Results are persisted to ExperimentStore and
    the viewer Labels layer is updated in-place.

    All store I/O (SQLite) happens on the main thread. Only the cellpose
    computation runs in the background thread, because SQLite connections
    cannot be shared across threads.

    Args:
        viewer: The napari Viewer instance.
        store: An open ExperimentStore.
        fov: FOV name.
        condition: Condition name.
        bio_rep: Biological replicate name (or None).
        channel_names: List of loaded channel names.
    """

    # Models available in the ComboBox
    BUILTIN_MODELS = ["cpsam", "cyto3", "cyto2", "nuclei"]

    def __init__(
        self,
        viewer: napari.Viewer,
        store: ExperimentStore,
        fov: str,
        condition: str,
        bio_rep: str | None,
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
        self._fov = fov
        self._condition = condition
        self._bio_rep = bio_rep
        self._channel_names = channel_names
        self._worker: Any = None  # thread_worker handle

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
        self._model_combo.addItems(self.BUILTIN_MODELS + ["custom..."])
        model_layout.addWidget(self._model_combo)

        # Custom model path (hidden by default)
        self._custom_row = QWidget()
        custom_layout = QHBoxLayout()
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self._custom_path_label = QLabel("No file selected")
        self._custom_path_label.setWordWrap(True)
        self._custom_browse_btn = QPushButton("Browse...")
        self._custom_browse_btn.clicked.connect(self._browse_custom_model)
        custom_layout.addWidget(self._custom_path_label, stretch=1)
        custom_layout.addWidget(self._custom_browse_btn)
        self._custom_row.setLayout(custom_layout)
        self._custom_row.setVisible(False)
        model_layout.addWidget(self._custom_row)

        self._model_combo.currentTextChanged.connect(self._on_model_changed)

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # --- Channel selection ---
        ch_group = QGroupBox("Channels")
        ch_layout = QVBoxLayout()

        ch_layout.addWidget(QLabel("Primary channel:"))
        self._primary_ch_combo = QComboBox()
        self._primary_ch_combo.addItems(channel_names)
        ch_layout.addWidget(self._primary_ch_combo)

        ch_layout.addWidget(QLabel("Nucleus channel:"))
        self._nucleus_ch_combo = QComboBox()
        self._nucleus_ch_combo.addItems(["None"] + channel_names)
        ch_layout.addWidget(self._nucleus_ch_combo)

        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # --- Parameters ---
        param_group = QGroupBox("Parameters")
        param_layout = QVBoxLayout()

        # Diameter
        row = QHBoxLayout()
        row.addWidget(QLabel("Diameter (px):"))
        self._diameter_spin = QSpinBox()
        self._diameter_spin.setRange(1, 500)
        self._diameter_spin.setValue(30)
        row.addWidget(self._diameter_spin)
        param_layout.addLayout(row)

        # Cell probability threshold
        row = QHBoxLayout()
        row.addWidget(QLabel("Cell prob:"))
        self._cellprob_spin = QDoubleSpinBox()
        self._cellprob_spin.setRange(-8.0, 8.0)
        self._cellprob_spin.setSingleStep(0.2)
        self._cellprob_spin.setValue(0.0)
        self._cellprob_spin.setDecimals(1)
        row.addWidget(self._cellprob_spin)
        param_layout.addLayout(row)

        # Flow threshold
        row = QHBoxLayout()
        row.addWidget(QLabel("Flow threshold:"))
        self._flow_spin = QDoubleSpinBox()
        self._flow_spin.setRange(0.0, 3.0)
        self._flow_spin.setSingleStep(0.05)
        self._flow_spin.setValue(0.4)
        self._flow_spin.setDecimals(2)
        row.addWidget(self._flow_spin)
        param_layout.addLayout(row)

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
    # Callbacks
    # ------------------------------------------------------------------

    def _on_model_changed(self, text: str) -> None:
        self._custom_row.setVisible(text == "custom...")

    def _browse_custom_model(self) -> None:
        from qtpy.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self.widget, "Select custom cellpose model",
        )
        if path:
            self._custom_path_label.setText(path)

    def _get_model_name(self) -> str:
        """Return the selected model name or custom path."""
        text = self._model_combo.currentText()
        if text == "custom...":
            path = self._custom_path_label.text()
            if path == "No file selected":
                raise ValueError("Select a custom model file first.")
            return path
        return text

    def _build_params(self) -> dict:
        """Collect widget values into a dict for the worker thread."""
        model_name = self._get_model_name()
        primary_ch = self._primary_ch_combo.currentText()
        nucleus_ch = self._nucleus_ch_combo.currentText()

        # Build cellpose channel config
        if nucleus_ch == "None":
            channels_cellpose = None  # [0, 0] default (grayscale)
        else:
            channels_cellpose = (1, 2)

        return {
            "model_name": model_name,
            "primary_channel": primary_ch,
            "nucleus_channel": nucleus_ch if nucleus_ch != "None" else None,
            "channels_cellpose": channels_cellpose,
            "diameter": float(self._diameter_spin.value()),
            "cellprob_threshold": self._cellprob_spin.value(),
            "flow_threshold": self._flow_spin.value(),
            "gpu": _gpu_available(),
        }

    def _on_run(self) -> None:
        """Launch cellpose segmentation in a background thread.

        Store I/O (SQLite reads) happens here on the main thread.
        Only the cellpose model.eval() call runs in the background.
        Store writes happen back on the main thread in _on_segmentation_done.
        """
        from napari.qt.threading import thread_worker

        try:
            params = self._build_params()
        except ValueError as exc:
            self._status_label.setText(f"Error: {exc}")
            return

        # --- Read images on the main thread (SQLite-safe) ---
        try:
            image = self._store.read_image_numpy(
                self._fov, self._condition, params["primary_channel"],
                bio_rep=self._bio_rep,
            )
            if params["nucleus_channel"] is not None:
                nuc_image = self._store.read_image_numpy(
                    self._fov, self._condition, params["nucleus_channel"],
                    bio_rep=self._bio_rep,
                )
                image = np.stack([image, nuc_image], axis=-1)
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
            from percell3.segment.base_segmenter import SegmentationParams
            from percell3.segment.cellpose_adapter import CellposeAdapter

            seg_params = SegmentationParams(
                channel=params["primary_channel"],
                model_name=params["model_name"],
                diameter=params["diameter"],
                flow_threshold=params["flow_threshold"],
                cellprob_threshold=params["cellprob_threshold"],
                gpu=params["gpu"],
                channels_cellpose=params["channels_cellpose"],
            )

            adapter = CellposeAdapter()
            return adapter.segment(image, seg_params)

        worker = _run_cellpose()
        self._worker = worker

        worker.returned.connect(self._on_segmentation_done)
        worker.errored.connect(self._on_segmentation_error)
        worker.start()

    def _on_segmentation_done(self, labels: np.ndarray) -> None:
        """Persist results and update viewer (runs on main thread)."""
        from percell3.segment.roi_import import store_labels_and_cells

        self._worker = None
        params = self._last_params

        try:
            # All store writes happen here on the main thread
            fov_info, _ = self._store._resolve_fov(
                self._fov, self._condition, self._bio_rep,
            )

            run_params = {
                "method": "napari_cellpose_widget",
                "model_name": params["model_name"],
                "diameter": params["diameter"],
                "flow_threshold": params["flow_threshold"],
                "cellprob_threshold": params["cellprob_threshold"],
                "gpu": params["gpu"],
            }
            if params["nucleus_channel"]:
                run_params["nucleus_channel"] = params["nucleus_channel"]

            run_id = self._store.add_segmentation_run(
                params["primary_channel"], params["model_name"], run_params,
            )

            cell_count = store_labels_and_cells(
                self._store, labels, fov_info, self._fov, self._condition,
                run_id, bio_rep=self._bio_rep,
            )

            # Auto-measure all channels
            try:
                from percell3.measure.measurer import Measurer

                measurer = Measurer()
                measurer.measure_fov(
                    self._store, self._fov, self._condition,
                    self._channel_names, bio_rep=self._bio_rep,
                )
            except Exception as exc:
                logger.warning("Auto-measurement failed: %s", exc)

        except Exception as exc:
            self._run_btn.setEnabled(True)
            self._status_label.setText(f"Error saving: {exc}")
            self._status_label.setStyleSheet("color: red;")
            logger.error("Failed to save segmentation: %s", exc, exc_info=True)
            return

        # Update the "segmentation" Labels layer
        for layer in self._viewer.layers:
            if layer.name == "segmentation":
                layer.data = labels
                break
        else:
            self._viewer.add_labels(labels, name="segmentation", opacity=0.5)

        self._run_btn.setEnabled(True)
        self._status_label.setText(f"Done: {cell_count} cells")
        self._status_label.setStyleSheet("color: green;")

    def _on_segmentation_error(self, exc: Exception) -> None:
        """Handle segmentation errors."""
        self._worker = None
        self._run_btn.setEnabled(True)
        self._status_label.setText(f"Error: {exc}")
        self._status_label.setStyleSheet("color: red;")
        logger.error("Cellpose segmentation failed: %s", exc, exc_info=True)
