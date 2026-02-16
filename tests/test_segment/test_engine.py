"""Tests for SegmentationEngine — end-to-end pipeline tests with mock segmenter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.exceptions import ChannelNotFoundError
from percell3.segment._engine import SegmentationEngine
from percell3.segment.base_segmenter import SegmentationResult
from tests.test_segment.conftest import EmptySegmenter, MockSegmenter

# --- Error-raising segmenters for exception handling tests ---


class ErrorSegmenter(MockSegmenter):
    """A segmenter that raises a specific exception on every call."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def segment(self, image: np.ndarray, params) -> np.ndarray:
        raise self._error


class ErrorOnceSegmenter(MockSegmenter):
    """A segmenter that raises on the first call, succeeds on subsequent calls."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self._call_count = 0

    def segment(self, image: np.ndarray, params) -> np.ndarray:
        self._call_count += 1
        if self._call_count == 1:
            raise self._error
        return super().segment(image, params)


@pytest.fixture
def experiment_with_regions(tmp_path: Path) -> ExperimentStore:
    """Create an experiment with 2 regions, each with DAPI channel data."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_condition("control")

    for name in ("region_1", "region_2"):
        image = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
        store.add_region(name, "control", width=128, height=128, pixel_size_um=0.65)
        store.write_image(name, "control", "DAPI", image)

    yield store
    store.close()


@pytest.fixture
def experiment_multi_condition(tmp_path: Path) -> ExperimentStore:
    """Create an experiment with 2 conditions, 1 region each."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation")

    for cond in ("control", "treated"):
        store.add_condition(cond)
        image = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        store.add_region("region_1", cond, width=64, height=64, pixel_size_um=0.65)
        store.write_image("region_1", cond, "DAPI", image)

    yield store
    store.close()


class TestSegmentationEngine:
    """Tests for the SegmentationEngine pipeline."""

    def test_end_to_end_with_mock_segmenter(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Labels stored in zarr, cells in SQLite."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI", model="cyto3")

        assert isinstance(result, SegmentationResult)
        assert result.run_id >= 1
        assert result.regions_processed == 2
        assert result.cell_count > 0

        # Verify labels in zarr
        labels_1 = store.read_labels("region_1", "control")
        assert labels_1.shape == (128, 128)
        assert labels_1.dtype == np.int32

        labels_2 = store.read_labels("region_2", "control")
        assert labels_2.shape == (128, 128)

        # Verify cells in SQLite
        cell_count = store.get_cell_count()
        assert cell_count == result.cell_count

    def test_progress_callback(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Progress callback should be called once per region."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())
        calls: list[tuple[int, int, str]] = []

        def callback(current: int, total: int, name: str) -> None:
            calls.append((current, total, name))

        engine.run(store, channel="DAPI", progress_callback=callback)

        assert len(calls) == 2
        assert calls[0] == (1, 2, "region_1")
        assert calls[1] == (2, 2, "region_2")

    def test_missing_channel_raises(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Missing channel should raise ChannelNotFoundError."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        with pytest.raises(ChannelNotFoundError):
            engine.run(store, channel="GFP")

    def test_region_filtering_by_name(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Only specified regions should be processed."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI", regions=["region_1"])

        assert result.regions_processed == 1
        # Only region_1 should have labels
        labels = store.read_labels("region_1", "control")
        assert labels.max() > 0

    def test_condition_filtering(
        self, experiment_multi_condition: ExperimentStore
    ) -> None:
        """Only regions with matching condition should be processed."""
        store = experiment_multi_condition
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI", condition="treated")

        assert result.regions_processed == 1

    def test_empty_segmentation_warning(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Zero cells detected: warning in result, labels stored as zeros."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=EmptySegmenter())

        result = engine.run(store, channel="DAPI")

        assert result.cell_count == 0
        assert result.regions_processed == 2
        assert len(result.warnings) == 2
        assert "0 cells detected" in result.warnings[0]

        # Labels should still be stored (all zeros)
        labels = store.read_labels("region_1", "control")
        assert labels.max() == 0

    def test_resegmentation_new_run_id(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Re-segmentation should create a new run_id, old cells preserved."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result1 = engine.run(store, channel="DAPI")
        result2 = engine.run(store, channel="DAPI")

        assert result2.run_id > result1.run_id
        # Both runs' cells should be in DB
        total_cells = store.get_cell_count()
        assert total_cells == result1.cell_count + result2.cell_count

    def test_cell_count_matches_db(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """SegmentationResult.cell_count should match cells in DB."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI")

        db_count = store.get_cell_count()
        assert result.cell_count == db_count

    def test_multiple_regions_correct_region_ids(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Cells should have correct region_ids."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        engine.run(store, channel="DAPI")

        cells_df = store.get_cells(condition="control", region="region_1")
        assert not cells_df.empty

        cells_df2 = store.get_cells(condition="control", region="region_2")
        assert not cells_df2.empty

    def test_no_regions_match_raises(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """ValueError when no regions match the filter."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        with pytest.raises(ValueError, match="No regions match"):
            engine.run(store, channel="DAPI", regions=["nonexistent"])

    def test_segmentation_run_recorded(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Segmentation run should be recorded in DB with parameters."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI", model="cyto3", diameter=60)

        runs = store.get_segmentation_runs()
        assert len(runs) >= 1
        run = [r for r in runs if r["id"] == result.run_id][0]
        assert run["model_name"] == "cyto3"
        assert run["channel"] == "DAPI"
        assert run["parameters"]["diameter"] == 60.0

    def test_elapsed_seconds_positive(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Elapsed time should be positive."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI")

        assert result.elapsed_seconds > 0

    def test_cell_count_updated_in_run(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """Segmentation run cell_count should be updated after processing."""
        store = experiment_with_regions
        engine = SegmentationEngine(segmenter=MockSegmenter())

        result = engine.run(store, channel="DAPI")

        runs = store.get_segmentation_runs()
        run = [r for r in runs if r["id"] == result.run_id][0]
        assert run["cell_count"] == result.cell_count

    def test_memory_error_propagates(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """MemoryError should not be caught by per-region handler."""
        store = experiment_with_regions
        engine = SegmentationEngine(
            segmenter=ErrorSegmenter(MemoryError("out of memory"))
        )

        with pytest.raises(MemoryError, match="out of memory"):
            engine.run(store, channel="DAPI")

    def test_keyboard_interrupt_propagates(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """KeyboardInterrupt should propagate immediately."""
        store = experiment_with_regions
        engine = SegmentationEngine(
            segmenter=ErrorSegmenter(KeyboardInterrupt())
        )

        with pytest.raises(KeyboardInterrupt):
            engine.run(store, channel="DAPI")

    def test_region_value_error_continues(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """ValueError on one region should not stop other regions."""
        store = experiment_with_regions
        engine = SegmentationEngine(
            segmenter=ErrorOnceSegmenter(ValueError("bad region"))
        )

        result = engine.run(store, channel="DAPI")

        # First region failed, second succeeded
        assert result.regions_processed == 1
        assert len(result.warnings) == 1
        assert "segmentation failed" in result.warnings[0]
        assert result.cell_count > 0

    def test_region_runtime_error_continues(
        self, experiment_with_regions: ExperimentStore
    ) -> None:
        """RuntimeError on one region should not stop other regions."""
        store = experiment_with_regions
        engine = SegmentationEngine(
            segmenter=ErrorOnceSegmenter(RuntimeError("cellpose crash"))
        )

        result = engine.run(store, channel="DAPI")

        assert result.regions_processed == 1
        assert len(result.warnings) == 1
        assert "cellpose crash" in result.warnings[0]
