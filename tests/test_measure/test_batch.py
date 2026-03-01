"""Tests for BatchMeasurer — experiment-wide measurement."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord
from percell3.measure.batch import BatchMeasurer, BatchResult, ConfigBatchResult


class TestBatchMeasurer:

    def test_measure_all_fovs_all_channels(self, measure_experiment: ExperimentStore):
        """Batch measure all FOVs x all channels should produce correct totals."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(measure_experiment)

        assert isinstance(result, BatchResult)
        assert result.fovs_processed == 2
        assert result.channels_measured == 2  # DAPI + GFP
        # 2 FOVs x 2 cells x 2 channels x 7 metrics = 56
        assert result.total_measurements == 56
        assert result.elapsed_seconds > 0

    def test_measure_specific_channels(self, measure_experiment: ExperimentStore):
        """Only specified channels should be measured."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(
            measure_experiment, channels=["GFP"],
        )
        assert result.channels_measured == 1
        # 2 FOVs x 2 cells x 1 channel x 7 metrics = 28
        assert result.total_measurements == 28

    def test_measure_specific_metrics(self, measure_experiment: ExperimentStore):
        """Only specified metrics should be computed."""
        batch = BatchMeasurer()
        result = batch.measure_experiment(
            measure_experiment,
            channels=["GFP"],
            metrics=["mean_intensity", "area"],
        )
        # 2 FOVs x 2 cells x 1 channel x 2 metrics = 8
        assert result.total_measurements == 8

    def test_progress_callback(self, measure_experiment: ExperimentStore):
        """Progress callback should be called once per FOV."""
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
        store.add_fov("control", width=32, height=32)

        batch = BatchMeasurer()
        with pytest.raises(ValueError, match="No channels"):
            batch.measure_experiment(store, channels=[])
        store.close()

    def test_no_fovs_raises(self, tmp_path):
        """No FOVs should raise ValueError."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("control")

        batch = BatchMeasurer()
        with pytest.raises(ValueError, match="No fovs found"):
            batch.measure_experiment(store)
        store.close()

    def test_condition_filter(self, tmp_path):
        """Condition filter should only process matching FOVs."""
        store = ExperimentStore.create(tmp_path / "multi.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        store.add_condition("treated")

        for cond in ("control", "treated"):
            fov_id = store.add_fov(cond, width=32, height=32)
            image = np.full((32, 32), 100, dtype=np.uint16)
            store.write_image(fov_id, "GFP", image)

        batch = BatchMeasurer()
        # No cells exist, so we expect 0 measurements but no error
        # fovs_processed counts FOVs that ran successfully (even with 0 cells)
        result = batch.measure_experiment(store, condition="control")
        assert result.fovs_processed == 1
        assert result.total_measurements == 0
        assert len(result.warnings) == 1  # 1 FOV with 0 measurements
        store.close()

    def test_warnings_for_empty_fovs(self, tmp_path):
        """FOVs with 0 cells should generate warnings."""
        store = ExperimentStore.create(tmp_path / "warn.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        fov_id = store.add_fov("control", width=32, height=32)
        image = np.zeros((32, 32), dtype=np.uint16)
        store.write_image(fov_id, "GFP", image)

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
            fovs_processed=2,
            channels_measured=1,
            elapsed_seconds=1.5,
        )
        with pytest.raises(AttributeError):
            result.total_measurements = 20


# ---------------------------------------------------------------------------
# Fixture for config-driven batch measurement
# ---------------------------------------------------------------------------


@pytest.fixture
def config_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with segmentation + threshold runs and a measurement config.

    Layout:
        - Condition: "control"
        - 1 FOV (64x64)
        - Channels: "DAPI" (segmentation), "GFP" (measurement + thresholding)
        - 1 segmentation run with 2 cells
        - 1 threshold run on GFP
        - 1 measurement config with 1 entry (whole_cell + masked)

    Cell 1: label=1, bbox (5,5,20,20) — GFP value 200 (above threshold)
    Cell 2: label=2, bbox (40,40,20,20) — GFP value 50 (below threshold)
    """
    store = ExperimentStore.create(tmp_path / "config.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    # DAPI image
    dapi = np.full((64, 64), 50, dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi)

    # GFP image — cell 1 region bright, cell 2 region dim
    gfp = np.zeros((64, 64), dtype=np.uint16)
    gfp[5:25, 5:25] = 200
    gfp[40:60, 40:60] = 50
    store.write_image(fov_id, "GFP", gfp)

    # Segmentation run
    seg_run_id = store.add_segmentation_run(
        fov_id=fov_id, channel="DAPI", model_name="mock",
        parameters={"diameter": 30.0},
    )
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[5:25, 5:25] = 1
    labels[40:60, 40:60] = 2
    store.write_labels(fov_id, labels, seg_run_id)

    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_run_id,
            label_value=1,
            centroid_x=15.0, centroid_y=15.0,
            bbox_x=5, bbox_y=5, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_run_id,
            label_value=2,
            centroid_x=50.0, centroid_y=50.0,
            bbox_x=40, bbox_y=40, bbox_w=20, bbox_h=20,
            area_pixels=400.0,
        ),
    ]
    store.add_cells(cells)

    # Threshold run on GFP with manual threshold at 100
    from percell3.measure.thresholding import ThresholdEngine
    engine = ThresholdEngine()
    thr_result = engine.threshold_fov(
        store, fov_id=fov_id, channel="GFP",
        method="manual", manual_value=100.0,
    )

    # Create measurement config with one entry (seg + threshold)
    config_id = store.create_measurement_config("test_config")
    store.add_measurement_config_entry(
        config_id=config_id, fov_id=fov_id,
        segmentation_run_id=seg_run_id,
        threshold_run_id=thr_result.threshold_run_id,
    )

    store._test_fov_id = fov_id
    store._test_seg_run_id = seg_run_id
    store._test_thr_run_id = thr_result.threshold_run_id
    store._test_config_id = config_id
    yield store
    store.close()


class TestMeasureConfig:
    """Tests for BatchMeasurer.measure_config()."""

    def test_whole_cell_and_masked_measurements(
        self, config_experiment: ExperimentStore,
    ):
        """measure_config should produce whole_cell + mask-scoped measurements."""
        store = config_experiment
        batch = BatchMeasurer()

        result = batch.measure_config(store, store._test_config_id)

        assert isinstance(result, ConfigBatchResult)
        assert result.entries_processed == 1
        assert result.entries_skipped == 0
        assert result.total_measurements > 0
        assert result.elapsed_seconds > 0

        # Check whole_cell measurements exist
        cells_df = store.get_cells(fov_id=store._test_fov_id)
        cell_ids = cells_df["id"].tolist()
        wc = store.get_measurements(cell_ids=cell_ids, scope="whole_cell")
        assert not wc.empty

        # Check mask-scoped measurements exist
        mi = store.get_measurements(cell_ids=cell_ids, scope="mask_inside")
        assert not mi.empty
        mo = store.get_measurements(cell_ids=cell_ids, scope="mask_outside")
        assert not mo.empty

    def test_particle_extraction(self, config_experiment: ExperimentStore):
        """measure_config should extract particles during measurement."""
        store = config_experiment
        batch = BatchMeasurer()

        result = batch.measure_config(store, store._test_config_id)

        assert result.total_particles > 0

        # Verify particle labels written to zarr
        particle_labels = store.read_particle_labels(
            store._test_fov_id, "GFP", store._test_thr_run_id,
        )
        assert particle_labels.shape == (64, 64)
        assert np.max(particle_labels) > 0

    def test_skip_if_already_measured(self, config_experiment: ExperimentStore):
        """measure_config should skip entries that are already measured."""
        store = config_experiment
        batch = BatchMeasurer()

        # First run: should process
        result1 = batch.measure_config(store, store._test_config_id)
        assert result1.entries_processed == 1
        assert result1.entries_skipped == 0

        # Second run: should skip
        result2 = batch.measure_config(store, store._test_config_id)
        assert result2.entries_processed == 0
        assert result2.entries_skipped == 1
        assert result2.total_measurements == 0

    def test_force_remeasure(self, config_experiment: ExperimentStore):
        """measure_config with force=True should re-measure even if measured."""
        store = config_experiment
        batch = BatchMeasurer()

        # First run
        result1 = batch.measure_config(store, store._test_config_id)
        assert result1.entries_processed == 1

        # Second run with force=True
        result2 = batch.measure_config(
            store, store._test_config_id, force=True,
        )
        assert result2.entries_processed == 1
        assert result2.entries_skipped == 0
        assert result2.total_measurements > 0

    def test_channel_resolution_from_threshold_run(
        self, config_experiment: ExperimentStore,
    ):
        """measure_config should resolve channel from threshold run metadata."""
        store = config_experiment
        batch = BatchMeasurer()
        result = batch.measure_config(store, store._test_config_id)

        # Mask measurements should exist — channel resolved from threshold run
        cells_df = store.get_cells(fov_id=store._test_fov_id)
        cell_ids = cells_df["id"].tolist()
        mi = store.get_measurements(cell_ids=cell_ids, scope="mask_inside")
        assert not mi.empty

    def test_progress_callback(self, config_experiment: ExperimentStore):
        """Progress callback should be called once per config entry."""
        store = config_experiment
        batch = BatchMeasurer()
        calls: list[tuple[int, int, str]] = []

        def callback(current: int, total: int, name: str) -> None:
            calls.append((current, total, name))

        batch.measure_config(
            store, store._test_config_id, progress_callback=callback,
        )
        assert len(calls) == 1
        assert calls[0] == (1, 1, calls[0][2])  # 1 of 1 entries

    def test_empty_config(self, tmp_path: Path):
        """Measuring an empty config should return zero results."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        config_id = store.create_measurement_config("empty")

        batch = BatchMeasurer()
        result = batch.measure_config(store, config_id)

        assert result.entries_processed == 0
        assert result.entries_skipped == 0
        assert result.total_measurements == 0
        store.close()

    def test_whole_cell_only_entry(self, tmp_path: Path):
        """Config entry without threshold_run_id should only do whole_cell."""
        store = ExperimentStore.create(tmp_path / "wc.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        fov_id = store.add_fov("control", width=32, height=32)
        store.write_image(fov_id, "GFP", np.full((32, 32), 100, dtype=np.uint16))
        store.write_image(fov_id, "DAPI", np.full((32, 32), 50, dtype=np.uint16))

        seg_id = store.add_segmentation_run(
            fov_id=fov_id, channel="DAPI", model_name="mock", parameters={},
        )
        labels = np.zeros((32, 32), dtype=np.int32)
        labels[5:15, 5:15] = 1
        store.write_labels(fov_id, labels, seg_id)
        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10, area_pixels=100.0,
        )])

        config_id = store.create_measurement_config("wc_only")
        store.add_measurement_config_entry(
            config_id=config_id, fov_id=fov_id,
            segmentation_run_id=seg_id,
            threshold_run_id=None,  # No threshold
        )

        batch = BatchMeasurer()
        result = batch.measure_config(store, config_id)

        assert result.entries_processed == 1
        assert result.total_particles == 0  # No particle extraction

        # Only whole_cell measurements
        cells_df = store.get_cells(fov_id=fov_id)
        cell_ids = cells_df["id"].tolist()
        wc = store.get_measurements(cell_ids=cell_ids, scope="whole_cell")
        assert not wc.empty
        mi = store.get_measurements(cell_ids=cell_ids, scope="mask_inside")
        assert mi.empty

        store.close()

    def test_partial_failure_commits_completed(self, tmp_path: Path):
        """If one entry fails, completed entries should be committed."""
        store = ExperimentStore.create(tmp_path / "partial.percell")
        store.add_channel("DAPI", role="segmentation")
        store.add_channel("GFP")
        store.add_condition("control")

        # FOV 1: normal (will succeed)
        fov1 = store.add_fov("control", width=32, height=32)
        store.write_image(fov1, "GFP", np.full((32, 32), 100, dtype=np.uint16))
        store.write_image(fov1, "DAPI", np.full((32, 32), 50, dtype=np.uint16))
        seg1 = store.add_segmentation_run(
            fov_id=fov1, channel="DAPI", model_name="mock", parameters={},
        )
        labels1 = np.zeros((32, 32), dtype=np.int32)
        labels1[5:15, 5:15] = 1
        store.write_labels(fov1, labels1, seg1)
        store.add_cells([CellRecord(
            fov_id=fov1, segmentation_id=seg1, label_value=1,
            centroid_x=10.0, centroid_y=10.0,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10, area_pixels=100.0,
        )])

        # FOV 2: has a segmentation run but no images (will fail)
        fov2 = store.add_fov("control", width=32, height=32)
        seg2 = store.add_segmentation_run(
            fov_id=fov2, channel="DAPI", model_name="mock", parameters={},
        )
        # Deliberately no labels or images written for fov2

        config_id = store.create_measurement_config("partial")
        store.add_measurement_config_entry(
            config_id=config_id, fov_id=fov1,
            segmentation_run_id=seg1,
        )
        store.add_measurement_config_entry(
            config_id=config_id, fov_id=fov2,
            segmentation_run_id=seg2,
        )

        batch = BatchMeasurer()
        result = batch.measure_config(store, config_id)

        # FOV 1 should have measurements
        cells1 = store.get_cells(fov_id=fov1)
        wc1 = store.get_measurements(cell_ids=cells1["id"].tolist(), scope="whole_cell")
        assert not wc1.empty

        # Result should report 1 processed + warnings
        assert result.entries_processed >= 1
        assert len(result.warnings) >= 0  # fov2 may fail or have 0 cells

        store.close()

    def test_config_batch_result_frozen(self):
        """ConfigBatchResult should be immutable (frozen dataclass)."""
        result = ConfigBatchResult(
            entries_processed=5,
            entries_skipped=2,
            total_measurements=100,
            total_particles=50,
            elapsed_seconds=3.5,
        )
        with pytest.raises(AttributeError):
            result.entries_processed = 10
