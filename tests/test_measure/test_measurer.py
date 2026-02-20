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


class TestMeasureFovMasked:
    """Tests for Measurer.measure_fov_masked() — inside/outside threshold mask."""

    @pytest.fixture
    def masked_experiment(self, measure_experiment: ExperimentStore):
        """Extend measure_experiment with a threshold mask on GFP.

        Threshold mask: top-left quadrant (y<32, x<32) is True.
        Cell 1 at (10:30, 10:30) is fully inside the mask.
        Cell 2 at (40:60, 40:60) is fully outside the mask.
        """
        store = measure_experiment
        # Add a threshold run
        run_id = store.add_threshold_run("GFP", "manual", {"value": 50.0})

        # Create mask: top-left quadrant is True
        mask = np.zeros((64, 64), dtype=np.uint8)
        mask[:32, :32] = 255
        store.write_mask("fov_1", "control", "GFP", mask, run_id)

        return store, run_id

    def test_mask_inside_measures_cells(self, masked_experiment):
        """mask_inside should produce measurements for all cells."""
        store, run_id = masked_experiment
        measurer = Measurer()
        count = measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside"],
        )
        # 2 cells x 1 channel x 7 metrics = 14
        assert count == 14

    def test_mask_inside_values(self, masked_experiment):
        """Cell 1 is fully inside mask, Cell 2 has 0 pixels inside mask."""
        store, run_id = masked_experiment
        measurer = Measurer()
        measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside"],
            metrics=["mean_intensity"],
        )
        df = store.get_measurements(
            channels=["GFP"], metrics=["mean_intensity"], scope="mask_inside",
        )
        assert len(df) == 2
        # Sort by value to identify cells
        df_sorted = df.sort_values("value").reset_index(drop=True)
        # Cell 2 is fully outside mask → 0 pixels inside → value=0.0
        assert df_sorted.iloc[0]["value"] == pytest.approx(0.0)
        # Cell 1 is fully inside mask → mean_intensity = 100.0
        assert df_sorted.iloc[1]["value"] == pytest.approx(100.0)

    def test_mask_outside_values(self, masked_experiment):
        """Cell 1 has 0 pixels outside mask, Cell 2 is fully outside."""
        store, run_id = masked_experiment
        measurer = Measurer()
        measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_outside"],
            metrics=["mean_intensity"],
        )
        df = store.get_measurements(
            channels=["GFP"], metrics=["mean_intensity"], scope="mask_outside",
        )
        assert len(df) == 2
        df_sorted = df.sort_values("value").reset_index(drop=True)
        # Cell 1 is fully inside mask → 0 pixels outside → value=0.0
        assert df_sorted.iloc[0]["value"] == pytest.approx(0.0)
        # Cell 2 is fully outside mask → mean_intensity = 200.0
        assert df_sorted.iloc[1]["value"] == pytest.approx(200.0)

    def test_both_scopes(self, masked_experiment):
        """Both scopes should produce double the measurements."""
        store, run_id = masked_experiment
        measurer = Measurer()
        count = measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside", "mask_outside"],
            metrics=["mean_intensity"],
        )
        # 2 cells x 1 channel x 1 metric x 2 scopes = 4
        assert count == 4

    def test_zero_pixel_cells_get_zero_value(self, masked_experiment):
        """Cells with 0 pixels in the scoped mask should get value=0.0, not be skipped."""
        store, run_id = masked_experiment
        measurer = Measurer()
        measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside"],
            metrics=["area"],
        )
        df = store.get_measurements(metrics=["area"], scope="mask_inside")
        assert len(df) == 2  # Both cells present, not skipped
        values = sorted(df["value"].tolist())
        assert values[0] == pytest.approx(0.0)  # Cell 2: 0 pixels inside
        assert values[1] == pytest.approx(400.0)  # Cell 1: full 20x20

    def test_scope_stored_in_records(self, masked_experiment):
        """Records should have the correct scope value."""
        store, run_id = masked_experiment
        measurer = Measurer()
        measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside", "mask_outside"],
            metrics=["mean_intensity"],
        )
        df = store.get_measurements()
        scopes = set(df["scope"].tolist())
        assert scopes == {"mask_inside", "mask_outside"}

    def test_threshold_run_id_stored(self, masked_experiment):
        """Records should have the correct threshold_run_id."""
        store, run_id = masked_experiment
        measurer = Measurer()
        measurer.measure_fov_masked(
            store,
            fov="fov_1",
            condition="control",
            channels=["GFP"],
            threshold_channel="GFP",
            threshold_run_id=run_id,
            scopes=["mask_inside"],
            metrics=["mean_intensity"],
        )
        df = store.get_measurements(scope="mask_inside")
        assert all(df["threshold_run_id"] == run_id)

    def test_invalid_scope_raises(self, masked_experiment):
        """Invalid scope should raise ValueError."""
        store, run_id = masked_experiment
        measurer = Measurer()
        with pytest.raises(ValueError, match="Invalid scope"):
            measurer.measure_fov_masked(
                store,
                fov="fov_1",
                condition="control",
                channels=["GFP"],
                threshold_channel="GFP",
                threshold_run_id=run_id,
                scopes=["whole_cell"],
            )
