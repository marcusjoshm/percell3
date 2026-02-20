"""Tests for CellposeWidget — parameter validation, model selection, GPU detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestDetectGpu:
    """Tests for the GPU detection helper."""

    def test_cuda_detected(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _detect_gpu

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert _detect_gpu() == "GPU: CUDA"

    def test_mps_detected(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _detect_gpu

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert _detect_gpu() == "GPU: MPS"

    def test_cpu_fallback(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _detect_gpu

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert _detect_gpu() == "CPU only"

    def test_no_torch(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _detect_gpu

        with patch.dict("sys.modules", {"torch": None}):
            assert _detect_gpu() == "CPU only"


class TestGpuAvailable:
    def test_true_when_cuda(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _gpu_available

        with patch(
            "percell3.segment.viewer.cellpose_widget._detect_gpu",
            return_value="GPU: CUDA",
        ):
            assert _gpu_available() is True

    def test_false_when_cpu(self) -> None:
        from percell3.segment.viewer.cellpose_widget import _gpu_available

        with patch(
            "percell3.segment.viewer.cellpose_widget._detect_gpu",
            return_value="CPU only",
        ):
            assert _gpu_available() is False


class TestCellposeWidgetBuiltinModels:
    """Verify the model list constant."""

    def test_builtin_models_nonempty(self) -> None:
        from percell3.segment.viewer.cellpose_widget import CellposeWidget

        assert len(CellposeWidget.BUILTIN_MODELS) > 0

    def test_cpsam_is_first(self) -> None:
        from percell3.segment.viewer.cellpose_widget import CellposeWidget

        assert CellposeWidget.BUILTIN_MODELS[0] == "cpsam"

    def test_all_models_are_known(self) -> None:
        from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS
        from percell3.segment.viewer.cellpose_widget import CellposeWidget

        for model in CellposeWidget.BUILTIN_MODELS:
            assert model in KNOWN_CELLPOSE_MODELS, f"{model} not in KNOWN_CELLPOSE_MODELS"
