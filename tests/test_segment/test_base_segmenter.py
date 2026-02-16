"""Tests for SegmentationParams, SegmentationResult, and BaseSegmenter ABC."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.segment.base_segmenter import (
    BaseSegmenter,
    SegmentationParams,
    SegmentationResult,
)


class TestSegmentationParams:
    """Tests for SegmentationParams dataclass and validation."""

    def test_defaults(self) -> None:
        params = SegmentationParams(channel="DAPI")
        assert params.channel == "DAPI"
        assert params.model_name == "cyto3"
        assert params.diameter is None
        assert params.flow_threshold == 0.4
        assert params.cellprob_threshold == 0.0
        assert params.gpu is True
        assert params.min_size == 15
        assert params.normalize is True
        assert params.channels_cellpose is None

    def test_custom_values(self) -> None:
        params = SegmentationParams(
            channel="GFP",
            model_name="nuclei",
            diameter=60.0,
            flow_threshold=0.5,
            cellprob_threshold=-1.0,
            gpu=False,
            min_size=30,
            normalize=False,
            channels_cellpose=[0, 0],
        )
        assert params.channel == "GFP"
        assert params.model_name == "nuclei"
        assert params.diameter == 60.0
        assert params.gpu is False

    def test_frozen(self) -> None:
        params = SegmentationParams(channel="DAPI")
        with pytest.raises(AttributeError):
            params.channel = "GFP"  # type: ignore[misc]

    def test_empty_channel_raises(self) -> None:
        with pytest.raises(ValueError, match="channel must not be empty"):
            SegmentationParams(channel="")

    def test_empty_model_name_raises(self) -> None:
        with pytest.raises(ValueError, match="model_name must not be empty"):
            SegmentationParams(channel="DAPI", model_name="")

    def test_negative_min_size_raises(self) -> None:
        with pytest.raises(ValueError, match="min_size must be >= 0"):
            SegmentationParams(channel="DAPI", min_size=-1)

    def test_zero_min_size_ok(self) -> None:
        params = SegmentationParams(channel="DAPI", min_size=0)
        assert params.min_size == 0

    def test_flow_threshold_too_low_raises(self) -> None:
        with pytest.raises(ValueError, match="flow_threshold must be between 0 and 3"):
            SegmentationParams(channel="DAPI", flow_threshold=-0.1)

    def test_flow_threshold_too_high_raises(self) -> None:
        with pytest.raises(ValueError, match="flow_threshold must be between 0 and 3"):
            SegmentationParams(channel="DAPI", flow_threshold=3.1)

    def test_flow_threshold_boundaries_ok(self) -> None:
        p0 = SegmentationParams(channel="DAPI", flow_threshold=0.0)
        p3 = SegmentationParams(channel="DAPI", flow_threshold=3.0)
        assert p0.flow_threshold == 0.0
        assert p3.flow_threshold == 3.0

    def test_negative_diameter_raises(self) -> None:
        with pytest.raises(ValueError, match="diameter must be > 0 or None"):
            SegmentationParams(channel="DAPI", diameter=-10.0)

    def test_zero_diameter_raises(self) -> None:
        with pytest.raises(ValueError, match="diameter must be > 0 or None"):
            SegmentationParams(channel="DAPI", diameter=0.0)

    def test_none_diameter_ok(self) -> None:
        params = SegmentationParams(channel="DAPI", diameter=None)
        assert params.diameter is None

    def test_to_dict(self) -> None:
        params = SegmentationParams(channel="DAPI", diameter=60.0)
        d = params.to_dict()
        assert d["channel"] == "DAPI"
        assert d["diameter"] == 60.0
        assert d["model_name"] == "cyto3"
        assert d["gpu"] is True
        assert isinstance(d, dict)


class TestSegmentationResult:
    """Tests for SegmentationResult dataclass."""

    def test_defaults(self) -> None:
        result = SegmentationResult(run_id=1, cell_count=100, regions_processed=5)
        assert result.run_id == 1
        assert result.cell_count == 100
        assert result.regions_processed == 5
        assert result.warnings == []
        assert result.elapsed_seconds == 0.0

    def test_with_warnings(self) -> None:
        result = SegmentationResult(
            run_id=1,
            cell_count=0,
            regions_processed=1,
            warnings=["region_1: 0 cells detected"],
        )
        assert len(result.warnings) == 1

    def test_frozen(self) -> None:
        result = SegmentationResult(run_id=1, cell_count=0, regions_processed=0)
        with pytest.raises(AttributeError):
            result.cell_count = 10  # type: ignore[misc]


class TestBaseSegmenter:
    """Tests for BaseSegmenter ABC."""

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseSegmenter()  # type: ignore[abstract]

    def test_concrete_subclass(self) -> None:
        class MockSegmenter(BaseSegmenter):
            def segment(
                self, image: np.ndarray, params: SegmentationParams
            ) -> np.ndarray:
                return np.zeros(image.shape, dtype=np.int32)

            def segment_batch(
                self, images: list[np.ndarray], params: SegmentationParams
            ) -> list[np.ndarray]:
                return [self.segment(img, params) for img in images]

        segmenter = MockSegmenter()
        img = np.zeros((64, 64), dtype=np.uint16)
        params = SegmentationParams(channel="DAPI")
        result = segmenter.segment(img, params)
        assert result.shape == (64, 64)
        assert result.dtype == np.int32

    def test_concrete_subclass_batch(self) -> None:
        class MockSegmenter(BaseSegmenter):
            def segment(
                self, image: np.ndarray, params: SegmentationParams
            ) -> np.ndarray:
                return np.zeros(image.shape, dtype=np.int32)

            def segment_batch(
                self, images: list[np.ndarray], params: SegmentationParams
            ) -> list[np.ndarray]:
                return [self.segment(img, params) for img in images]

        segmenter = MockSegmenter()
        images = [np.zeros((64, 64), dtype=np.uint16) for _ in range(3)]
        params = SegmentationParams(channel="DAPI")
        results = segmenter.segment_batch(images, params)
        assert len(results) == 3
