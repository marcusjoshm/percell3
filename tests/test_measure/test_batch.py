"""Tests for BatchMeasurer — experiment-wide measurement."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.measure.batch import BatchMeasurer, BatchResult


class TestBatchMeasurer:

    def test_measure_all_regions_all_channels(self, measure_experiment: ExperimentStore):
        """Batch measure all regions x all channels should produce correct totals."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(measure_experiment)

        assert isinstance(result, BatchResult)
        assert result.regions_processed == 2
        assert result.channels_measured == 2  # DAPI + GFP
        # 2 regions x 2 cells x 2 channels x 7 metrics = 56
        assert result.total_measurements == 56
        assert result.elapsed_seconds > 0

    def test_measure_specific_channels(self, measure_experiment: ExperimentStore):
        """Only specified channels should be measured."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(
            measure_experiment, channels=["GFP"],
        )
        assert result.channels_measured == 1
        # 2 regions x 2 cells x 1 channel x 7 metrics = 28
        assert result.total_measurements == 28

    def test_measure_specific_metrics(self, measure_experiment: ExperimentStore):
        """Only specified metrics should be computed."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(
            measure_experiment,
            channels=["GFP"],
            metrics=["mean_intensity", "area"],
        )
        # 2 regions x 2 cells x 1 channel x 2 metrics = 8
        assert result.total_measurements == 8

    def test_progress_callback(self, measure_experiment: ExperimentStore):
        """Progress callback should be called once per region."""
        batch = BatchMeasurer()
        calls: list[tuple[int, int, str]] = []

        def callback(current: int, total: int, name: str) -> None:
            calls.append((current, total, name))

        batch.measure_experiment(
            measure_experiment, channels=["GFP"], progress_callback=callback,
        )
        assert len(calls) == 2
        assert calls[0][0] == 1
        assert calls[0][1] == 2
        assert calls[1][0] == 2

    def test_no_channels_raises(self, tmp_path):
        """Empty channel list should raise ValueError."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_condition("control")
        store.add_region("region_1", "control", width=32, height=32)

        batch = BatchMeasurer()
        with pytest.raises(ValueError, match="No channels"):
            batch.measure_experiment(store, channels=[])
        store.close()

    def test_no_regions_raises(self, tmp_path):
        """No regions should raise ValueError."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("control")

        batch = BatchMeasurer()
        with pytest.raises(ValueError, match="No regions found"):
            batch.measure_experiment(store)
        store.close()

    def test_condition_filter(self, tmp_path):
        """Condition filter should only process matching regions."""
        store = ExperimentStore.create(tmp_path / "multi.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        store.add_condition("treated")

        for cond in ("control", "treated"):
            store.add_region("region_1", cond, width=32, height=32)
            image = np.full((32, 32), 100, dtype=np.uint16)
            store.write_image("region_1", cond, "GFP", image)

        batch = BatchMeasurer()
        # No cells exist, so we expect 0 measurements but no error
        # regions_processed counts regions that ran successfully (even with 0 cells)
        result = batch.measure_experiment(store, condition="control")
        assert result.regions_processed == 1
        assert result.total_measurements == 0
        assert len(result.warnings) == 1  # 1 region with 0 measurements
        store.close()

    def test_warnings_for_empty_regions(self, tmp_path):
        """Regions with 0 cells should generate warnings."""
        store = ExperimentStore.create(tmp_path / "warn.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        store.add_region("region_1", "control", width=32, height=32)
        image = np.zeros((32, 32), dtype=np.uint16)
        store.write_image("region_1", "control", "GFP", image)

        batch = BatchMeasurer()
        result = batch.measure_experiment(store)
        assert result.total_measurements == 0
        assert len(result.warnings) == 1
        assert "0 measurements" in result.warnings[0]
        store.close()

    def test_batch_result_frozen(self):
        """BatchResult should be immutable (frozen dataclass)."""
        result = BatchResult(
            total_measurements=10,
            regions_processed=2,
            channels_measured=1,
            elapsed_seconds=1.5,
        )
        with pytest.raises(AttributeError):
            result.total_measurements = 20
