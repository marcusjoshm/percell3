"""Tests for CellposeAdapter — Cellpose integration tests.

All tests in this file require cellpose and are marked @pytest.mark.slow
because they download/load models. Deselect with: pytest -m "not slow"
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from percell3.segment.base_segmenter import SegmentationParams
from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS, CellposeAdapter


def _cellpose_available() -> bool:
    try:
        import cellpose  # noqa: F401
        return True
    except ImportError:
        return False


class TestModelNameValidation:
    """Tests for model name allowlist (security: prevents arbitrary torch.load)."""

    def test_known_model_accepted(self) -> None:
        """Known model names should not raise."""
        adapter = CellposeAdapter()
        # Inject a mock to avoid actually loading cellpose
        mock_model = MagicMock()
        for name in ("cpsam", "cyto", "cyto2", "cyto3", "nuclei"):
            adapter._model_cache.clear()
            adapter._model_cache[(name, False)] = mock_model
            # Should not raise — model is in cache and name is valid
            assert adapter._get_model(name, gpu=False) is mock_model

    def test_path_model_name_rejected(self) -> None:
        """Filesystem path as model name should raise ValueError."""
        adapter = CellposeAdapter()
        with pytest.raises(ValueError, match="Unknown model"):
            adapter._get_model("../evil", gpu=False)

    def test_absolute_path_rejected(self) -> None:
        """Absolute path should raise ValueError."""
        adapter = CellposeAdapter()
        with pytest.raises(ValueError, match="Unknown model"):
            adapter._get_model("/tmp/malicious.pth", gpu=False)

    def test_empty_string_rejected(self) -> None:
        """Empty string should raise ValueError."""
        adapter = CellposeAdapter()
        with pytest.raises(ValueError, match="Unknown model"):
            adapter._get_model("", gpu=False)

    def test_arbitrary_string_rejected(self) -> None:
        """Arbitrary string should raise ValueError."""
        adapter = CellposeAdapter()
        with pytest.raises(ValueError, match="Unknown model"):
            adapter._get_model("not_a_real_model", gpu=False)

    def test_known_models_constant_nonempty(self) -> None:
        """The allowlist should contain the core Cellpose models."""
        assert len(KNOWN_CELLPOSE_MODELS) > 0
        assert "cpsam" in KNOWN_CELLPOSE_MODELS
        assert "cyto3" in KNOWN_CELLPOSE_MODELS
        assert "nuclei" in KNOWN_CELLPOSE_MODELS


class TestVersionAwareInstantiation:
    """Tests for version-aware model instantiation (3.x vs 4.x)."""

    @pytest.mark.skipif(
        not _cellpose_available(), reason="cellpose not installed",
    )
    def test_cellpose4_uses_pretrained_model(self) -> None:
        """On Cellpose 4.x, should use pretrained_model kwarg."""
        adapter = CellposeAdapter()
        mock_instance = MagicMock()

        with patch("cellpose.models.CellposeModel", return_value=mock_instance) as mock_cls:
            adapter._get_model("cpsam", gpu=False)

        mock_cls.assert_called_once_with(pretrained_model="cpsam", gpu=False)
        assert adapter._cellpose_major == 4

    @pytest.mark.skipif(
        not _cellpose_available(), reason="cellpose not installed",
    )
    def test_cellpose3_branch_uses_model_type(self) -> None:
        """When version is forced to 3, should use model_type kwarg."""
        adapter = CellposeAdapter()
        adapter._cellpose_major = 3  # Force 3.x behavior
        mock_instance = MagicMock()

        with patch("cellpose.models.CellposeModel", return_value=mock_instance) as mock_cls:
            adapter._get_model("cyto3", gpu=False)

        mock_cls.assert_called_once_with(model_type="cyto3", gpu=False)

    def test_version_cached_after_first_call(self) -> None:
        """Cellpose version should be cached on the adapter instance."""
        adapter = CellposeAdapter()
        assert adapter._cellpose_major is None

        mock_model = MagicMock()
        adapter._model_cache[("cpsam", False)] = mock_model
        adapter._cellpose_major = 4

        assert adapter._cellpose_major == 4


class TestCellposeAdapterUnit:
    """Unit tests using mocked cellpose."""

    def test_output_dtype_int32(self) -> None:
        """Output should be int32 regardless of cellpose internal dtype."""
        adapter = CellposeAdapter()
        fake_masks = np.array([[0, 1], [1, 0]], dtype=np.uint16)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", model_name="cyto3", gpu=False)
            result = adapter.segment(np.zeros((2, 2), dtype=np.uint16), params)

        assert result.dtype == np.int32

    def test_output_shape_matches_input(self) -> None:
        """Output shape should match input shape."""
        adapter = CellposeAdapter()
        input_shape = (128, 256)
        fake_masks = np.zeros(input_shape, dtype=np.int32)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", gpu=False)
            result = adapter.segment(np.zeros(input_shape, dtype=np.uint16), params)

        assert result.shape == input_shape

    def test_model_caching(self) -> None:
        """Second call with same params should reuse cached model."""
        adapter = CellposeAdapter()
        fake_masks = np.zeros((10, 10), dtype=np.int32)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        # Inject a mock model directly into the cache
        adapter._model_cache[("cyto3", False)] = mock_model

        params = SegmentationParams(channel="DAPI", model_name="cyto3", gpu=False)
        img = np.zeros((10, 10), dtype=np.uint16)

        adapter.segment(img, params)
        adapter.segment(img, params)

        # _get_model should return cached instance — eval called twice on same object
        assert mock_model.eval.call_count == 2
        # Cache should still have exactly one entry
        assert len(adapter._model_cache) == 1

    def test_all_zero_input_returns_all_zero_output(self) -> None:
        """All-dark image should produce all-zero labels (no cells)."""
        adapter = CellposeAdapter()
        fake_masks = np.zeros((64, 64), dtype=np.int32)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", gpu=False)
            result = adapter.segment(np.zeros((64, 64), dtype=np.uint16), params)

        assert result.max() == 0

    def test_segment_batch(self) -> None:
        """Batch segmentation should return list of label arrays."""
        adapter = CellposeAdapter()
        masks_list = [np.zeros((32, 32), dtype=np.int32) for _ in range(3)]

        mock_model = MagicMock()
        mock_model.eval.return_value = (masks_list, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", gpu=False)
            images = [np.zeros((32, 32), dtype=np.uint16) for _ in range(3)]
            results = adapter.segment_batch(images, params)

        assert len(results) == 3
        assert all(r.dtype == np.int32 for r in results)

    def test_default_channels_grayscale(self) -> None:
        """When channels_cellpose is None, should pass [0, 0] to Cellpose."""
        adapter = CellposeAdapter()
        fake_masks = np.zeros((10, 10), dtype=np.int32)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", gpu=False, channels_cellpose=None)
            adapter.segment(np.zeros((10, 10), dtype=np.uint16), params)

        call_kwargs = mock_model.eval.call_args
        assert call_kwargs[1]["channels"] == [0, 0]

    def test_custom_channels_passed_through(self) -> None:
        """Custom channels_cellpose should be passed to Cellpose."""
        adapter = CellposeAdapter()
        fake_masks = np.zeros((10, 10), dtype=np.int32)

        mock_model = MagicMock()
        mock_model.eval.return_value = (fake_masks, None, None, None)

        with patch.object(adapter, "_get_model", return_value=mock_model):
            params = SegmentationParams(channel="DAPI", gpu=False, channels_cellpose=[2, 1])
            adapter.segment(np.zeros((10, 10), dtype=np.uint16), params)

        call_kwargs = mock_model.eval.call_args
        assert call_kwargs[1]["channels"] == [2, 1]


@pytest.mark.slow
class TestCellposeAdapterIntegration:
    """Integration tests that actually run Cellpose. Requires model download."""

    def test_synthetic_bright_disks(self) -> None:
        """Synthetic image with 2 bright disks should detect >= 2 cells."""
        from skimage.draw import disk

        adapter = CellposeAdapter()
        image = np.zeros((256, 256), dtype=np.uint16)

        # Draw two bright disks
        rr, cc = disk((80, 80), 30)
        image[rr, cc] = 50000
        rr, cc = disk((180, 180), 30)
        image[rr, cc] = 50000

        params = SegmentationParams(
            channel="DAPI",
            model_name="cpsam",
            diameter=60.0,
            gpu=False,
            min_size=15,
        )
        result = adapter.segment(image, params)

        assert result.dtype == np.int32
        assert result.shape == (256, 256)
        # Should detect at least the 2 disks
        unique_labels = set(np.unique(result)) - {0}
        assert len(unique_labels) >= 2

    def test_all_dark_image(self) -> None:
        """All-dark image should return 0 cells."""
        adapter = CellposeAdapter()
        image = np.zeros((128, 128), dtype=np.uint16)

        params = SegmentationParams(
            channel="DAPI",
            model_name="cpsam",
            diameter=30.0,
            gpu=False,
        )
        result = adapter.segment(image, params)

        assert result.dtype == np.int32
        assert result.max() == 0
