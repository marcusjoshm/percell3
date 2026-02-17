"""Tests for Measurer — per-FOV measurement engine."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.measure.measurer import Measurer
from percell3.measure.metrics import MetricRegistry


class TestMeasureFov:
    """Tests for Measurer.measure_fov()."""

    def test_measure_single_channel(self, measure_experiment: ExperimentStore):
        """Measure GFP on fov_1: should produce measurements for 2 cells x 7 metrics."""
        measurer = Measurer()
        count = measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
        )
        # 2 cells x 7 metrics = 14
        assert count == 14

    def test_measurements_stored_in_db(self, measure_experiment: ExperimentStore):
        """Measurements should be queryable from the store."""
        measurer = Measurer()
        measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
        )
        df = measure_experiment.get_measurements(channels=["GFP"])
        assert not df.empty
        assert len(df) == 14  # 2 cells x 7 metrics

    def test_mean_intensity_values_correct(self, measure_experiment: ExperimentStore):
        """Cell 1 (GFP=100) and Cell 2 (GFP=200) should have correct mean intensities."""
        measurer = Measurer()
        measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
        )
        df = measure_experiment.get_measurements(channels=["GFP"], metrics=["mean_intensity"])
        assert len(df) == 2
        values = sorted(df["value"].tolist())
        assert values[0] == pytest.approx(100.0)
        assert values[1] == pytest.approx(200.0)

    def test_measure_multiple_channels(self, measure_experiment: ExperimentStore):
        """Measuring 2 channels should produce 2x measurements."""
        measurer = Measurer()
        count = measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["DAPI", "GFP"],
        )
        # 2 cells x 2 channels x 7 metrics = 28
        assert count == 28

    def test_measure_specific_metrics(self, measure_experiment: ExperimentStore):
        """Only requested metrics should be computed."""
        measurer = Measurer()
        count = measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            metrics=["mean_intensity", "area"],
        )
        # 2 cells x 1 channel x 2 metrics = 4
        assert count == 4

    def test_unknown_metric_raises(self, measure_experiment: ExperimentStore):
        """Requesting an unknown metric should raise KeyError."""
        measurer = Measurer()
        with pytest.raises(KeyError, match="Unknown metric"):
            measurer.measure_fov(
                measure_experiment,
                fov="fov_1",
                condition="control",
                channels=["GFP"],
                metrics=["nonexistent"],
            )

    def test_no_cells_returns_zero(self, tmp_path):
        """FOV with no cells should return 0 measurements."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        store.add_fov("fov_1", "control", width=32, height=32)
        image = np.zeros((32, 32), dtype=np.uint16)
        store.write_image("fov_1", "control", "GFP", image)

        # No segmentation → no cells
        measurer = Measurer()
        count = measurer.measure_fov(
            store, fov="fov_1", condition="control", channels=["GFP"],
        )
        assert count == 0
        store.close()

    def test_area_metric_correct(self, measure_experiment: ExperimentStore):
        """Area should equal the number of pixels in the cell mask (400 = 20x20)."""
        measurer = Measurer()
        measurer.measure_fov(
            measure_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            metrics=["area"],
        )
        df = measure_experiment.get_measurements(metrics=["area"])
        values = df["value"].tolist()
        assert all(v == pytest.approx(400.0) for v in values)

    def test_custom_metric_registry(self, single_fov_experiment: ExperimentStore):
        """Custom MetricRegistry should be used for computation."""
        reg = MetricRegistry()
        reg.register("always_42", lambda img, mask: 42.0)

        measurer = Measurer(metrics=reg)
        count = measurer.measure_fov(
            single_fov_experiment,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            metrics=["always_42"],
        )
        assert count == 1  # 1 cell x 1 metric
        df = single_fov_experiment.get_measurements(metrics=["always_42"])
        assert df["value"].iloc[0] == 42.0


class TestMeasureCells:
    """Tests for Measurer.measure_cells() — preview mode, no DB write."""

    def test_returns_records_without_db_write(self, measure_experiment: ExperimentStore):
        """measure_cells returns records but does not write to DB."""
        measurer = Measurer()

        # Get cell IDs
        cells_df = measure_experiment.get_cells(condition="control", fov="fov_1")
        cell_ids = cells_df["id"].tolist()

        records = measurer.measure_cells(
            measure_experiment,
            cell_ids=cell_ids,
            fov="fov_1",
            condition="control",
            channel="GFP",
            metrics=["mean_intensity"],
        )
        assert len(records) == 2  # 2 cells x 1 metric

        # DB should still be empty
        df = measure_experiment.get_measurements()
        assert df.empty

    def test_subset_of_cells(self, measure_experiment: ExperimentStore):
        """Only requested cell IDs should be measured."""
        measurer = Measurer()
        cells_df = measure_experiment.get_cells(condition="control", fov="fov_1")
        first_cell_id = cells_df["id"].iloc[0]

        records = measurer.measure_cells(
            measure_experiment,
            cell_ids=[first_cell_id],
            fov="fov_1",
            condition="control",
            channel="GFP",
            metrics=["mean_intensity"],
        )
        assert len(records) == 1
        assert records[0].cell_id == first_cell_id

    def test_nonexistent_cell_ids_returns_empty(self, measure_experiment: ExperimentStore):
        """Non-existent cell IDs should produce no records."""
        measurer = Measurer()
        records = measurer.measure_cells(
            measure_experiment,
            cell_ids=[999999],
            fov="fov_1",
            condition="control",
            channel="GFP",
        )
        assert records == []
