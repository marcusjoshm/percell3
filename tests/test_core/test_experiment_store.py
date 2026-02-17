"""Tests for percell3.core.experiment_store — acceptance tests + edge cases."""

from __future__ import annotations

import shutil
from pathlib import Path

import dask.array as da
import numpy as np
import pandas as pd
import pytest
import zarr

from percell3.core.exceptions import (
    DuplicateError,
    ExperimentError,
    ExperimentNotFoundError,
)
from percell3.core.experiment_store import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord


@pytest.fixture
def experiment(tmp_path: Path) -> ExperimentStore:
    """A fresh experiment for testing."""
    exp = ExperimentStore.create(tmp_path / "test.percell", name="Test Experiment")
    yield exp
    exp.close()


@pytest.fixture
def experiment_with_data(experiment: ExperimentStore) -> ExperimentStore:
    """An experiment pre-loaded with channels, conditions, fovs, cells, and measurements."""
    experiment.add_channel("DAPI", role="nucleus", color="#0000FF")
    experiment.add_channel("GFP", role="signal", color="#00FF00")
    experiment.add_condition("control")
    experiment.add_condition("treated")
    fov_id = experiment.add_fov("r1", condition="control", width=256, height=256)
    seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=100.0 + i, centroid_y=200.0 + i,
            bbox_x=80 + i, bbox_y=180 + i, bbox_w=40, bbox_h=40,
            area_pixels=1200.0 + i * 10,
        )
        for i in range(1, 11)
    ]
    cell_ids = experiment.add_cells(cells)

    gfp = experiment.get_channel("GFP")
    measurements = [
        MeasurementRecord(cell_id=cid, channel_id=gfp.id,
                          metric="mean_intensity", value=42.0 + cid)
        for cid in cell_ids
    ]
    experiment.add_measurements(measurements)
    return experiment


# === Acceptance Test 1: Create and open experiment ===


class TestLifecycle:
    def test_create_experiment(self, tmp_path):
        exp_path = tmp_path / "test.percell"
        exp = ExperimentStore.create(exp_path, name="Test Experiment")

        assert exp_path.exists()
        assert (exp_path / "experiment.db").exists()
        assert (exp_path / "images.zarr").exists()
        assert (exp_path / "labels.zarr").exists()
        assert (exp_path / "masks.zarr").exists()
        assert (exp_path / "exports").exists()
        assert exp.name == "Test Experiment"
        exp.close()

    def test_open_experiment(self, tmp_path):
        exp_path = tmp_path / "test.percell"
        ExperimentStore.create(exp_path, name="Test").close()
        exp = ExperimentStore.open(exp_path)
        assert exp.name == "Test"
        exp.close()

    def test_context_manager(self, tmp_path):
        exp_path = tmp_path / "test.percell"
        with ExperimentStore.create(exp_path) as exp:
            exp.add_channel("DAPI")

    def test_create_already_exists_raises(self, tmp_path):
        exp_path = tmp_path / "test.percell"
        ExperimentStore.create(exp_path).close()
        with pytest.raises(ExperimentError):
            ExperimentStore.create(exp_path)

    def test_open_nonexistent_raises(self, tmp_path):
        with pytest.raises(ExperimentNotFoundError):
            ExperimentStore.open(tmp_path / "nope.percell")

    def test_properties(self, experiment):
        assert experiment.db_path == experiment.path / "experiment.db"
        assert experiment.images_zarr_path == experiment.path / "images.zarr"
        assert experiment.labels_zarr_path == experiment.path / "labels.zarr"
        assert experiment.masks_zarr_path == experiment.path / "masks.zarr"


# === Acceptance Test 2: Channel management ===


class TestChannels:
    def test_add_and_get_channels(self, experiment):
        experiment.add_channel("DAPI", role="nucleus", color="#0000FF")
        experiment.add_channel("GFP", role="signal", color="#00FF00")

        channels = experiment.get_channels()
        assert len(channels) == 2
        assert channels[0].name == "DAPI"
        assert channels[0].role == "nucleus"

        dapi = experiment.get_channel("DAPI")
        assert dapi.color == "#0000FF"

    def test_duplicate_channel_raises(self, experiment):
        experiment.add_channel("DAPI")
        with pytest.raises(DuplicateError):
            experiment.add_channel("DAPI")


# === Acceptance Test 3: Condition/FOV hierarchy ===


class TestConditionsAndFovs:
    def test_conditions_and_fovs(self, experiment):
        experiment.add_condition("control")
        experiment.add_condition("treated")
        experiment.add_fov("fov_1", condition="control", width=2048, height=2048)
        experiment.add_fov("fov_2", condition="control", width=2048, height=2048)
        experiment.add_fov("fov_1", condition="treated", width=2048, height=2048)

        assert experiment.get_conditions() == ["control", "treated"]
        control_fovs = experiment.get_fovs(condition="control")
        assert len(control_fovs) == 2

    def test_timepoints(self, experiment):
        experiment.add_timepoint("t0", time_seconds=0.0)
        experiment.add_timepoint("t1", time_seconds=60.0)
        assert experiment.get_timepoints() == ["t0", "t1"]


# === Acceptance Test 4: Write and read OME-Zarr image ===


class TestImageIO:
    def test_write_and_read_image(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        experiment.add_fov("fov_1", condition="control", width=512, height=512)

        data = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
        experiment.write_image("fov_1", "control", "DAPI", data)

        result_dask = experiment.read_image("fov_1", "control", "DAPI")
        assert isinstance(result_dask, da.Array)

        result_np = experiment.read_image_numpy("fov_1", "control", "DAPI")
        np.testing.assert_array_equal(result_np, data)

    def test_multi_channel_image(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control", width=256, height=256)

        dapi = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
        gfp = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)

        experiment.write_image("r1", "control", "DAPI", dapi)
        experiment.write_image("r1", "control", "GFP", gfp)

        result_dapi = experiment.read_image_numpy("r1", "control", "DAPI")
        result_gfp = experiment.read_image_numpy("r1", "control", "GFP")

        np.testing.assert_array_equal(result_dapi, dapi)
        np.testing.assert_array_equal(result_gfp, gfp)


# === Acceptance Test 5: Cell records ===


class TestCells:
    def test_add_and_query_cells(self, experiment):
        experiment.add_channel("DAPI", role="nucleus")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("r1", condition="control")
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id,
                label_value=i, centroid_x=100 + i, centroid_y=200 + i,
                bbox_x=80 + i, bbox_y=180 + i, bbox_w=40, bbox_h=40,
                area_pixels=1200 + i * 10,
            )
            for i in range(1, 51)
        ]
        cell_ids = experiment.add_cells(cells)
        assert len(cell_ids) == 50

        df = experiment.get_cells(condition="control")
        assert len(df) == 50

        df_filtered = experiment.get_cells(min_area=1400)
        assert len(df_filtered) < 50

    def test_cell_count(self, experiment_with_data):
        assert experiment_with_data.get_cell_count() == 10


# === Acceptance Test 6: Measurements ===


class TestMeasurements:
    def test_measurements(self, experiment_with_data):
        df = experiment_with_data.get_measurements(
            channels=["GFP"], metrics=["mean_intensity"]
        )
        assert len(df) == 10

        pivot = experiment_with_data.get_measurement_pivot()
        assert "GFP_mean_intensity" in pivot.columns

    def test_measure_second_channel_independently(self, experiment):
        """Measure a channel that wasn't used for segmentation."""
        experiment.add_channel("DAPI", role="nucleus")
        experiment.add_channel("GFP", role="signal")
        experiment.add_channel("RFP", role="signal")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("r1", condition="control")
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id,
                label_value=i, centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cell_ids = experiment.add_cells(cells)

        gfp = experiment.get_channel("GFP")
        rfp = experiment.get_channel("RFP")

        gfp_measurements = [
            MeasurementRecord(cell_id=cid, channel_id=gfp.id,
                              metric="mean_intensity", value=42.0)
            for cid in cell_ids
        ]
        rfp_measurements = [
            MeasurementRecord(cell_id=cid, channel_id=rfp.id,
                              metric="mean_intensity", value=99.0)
            for cid in cell_ids
        ]
        experiment.add_measurements(gfp_measurements)
        experiment.add_measurements(rfp_measurements)

        pivot = experiment.get_measurement_pivot()
        assert "GFP_mean_intensity" in pivot.columns
        assert "RFP_mean_intensity" in pivot.columns


# === Acceptance Test 7: Label images ===


class TestLabels:
    def test_write_and_read_labels(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control", width=512, height=512)
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        labels = np.zeros((512, 512), dtype=np.int32)
        labels[100:150, 100:150] = 1
        labels[200:260, 200:260] = 2

        experiment.write_labels("r1", "control", labels, segmentation_run_id=seg_id)
        result = experiment.read_labels("r1", "control", timepoint=None)
        np.testing.assert_array_equal(result, labels)


# === Acceptance Test 8: NGFF metadata compliance ===


class TestNGFFMetadata:
    def test_zarr_has_ngff_metadata(self, experiment):
        experiment.add_channel("DAPI", color="#0000FF")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control", width=128, height=128)

        data = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
        experiment.write_image("r1", "control", "DAPI", data)

        store = zarr.open(str(experiment.images_zarr_path), mode="r")
        group = store["control/r1"]
        attrs = dict(group.attrs)

        assert "multiscales" in attrs
        ms = attrs["multiscales"][0]
        assert ms["version"] == "0.4"
        assert any(a["name"] == "y" and a["type"] == "space" for a in ms["axes"])
        assert any(a["name"] == "x" and a["type"] == "space" for a in ms["axes"])


# === Acceptance Test 9: Export ===


class TestExport:
    def test_export_csv(self, experiment_with_data, tmp_path):
        csv_path = tmp_path / "results.csv"
        experiment_with_data.export_csv(csv_path, channels=["GFP"])
        df = pd.read_csv(csv_path)
        assert "cell_id" in df.columns
        assert "GFP_mean_intensity" in df.columns


# === Acceptance Test 10: Portability ===


class TestPortability:
    def test_percell_directory_is_portable(self, experiment_with_data, tmp_path):
        copy_path = tmp_path / "copy.percell"
        shutil.copytree(experiment_with_data.path, copy_path)

        with ExperimentStore.open(copy_path) as exp2:
            assert exp2.get_channels() == experiment_with_data.get_channels()
            assert exp2.get_cell_count() == experiment_with_data.get_cell_count()


# === Additional edge case tests ===


class TestMasks:
    def test_write_and_read_mask(self, experiment):
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control", width=128, height=128)
        thr_id = experiment.add_threshold_run(channel="GFP", method="otsu")

        mask = np.zeros((128, 128), dtype=bool)
        mask[20:80, 20:80] = True

        experiment.write_mask("r1", "control", "GFP", mask, threshold_run_id=thr_id)
        result = experiment.read_mask("r1", "control", "GFP", timepoint=None)
        assert result.dtype == np.uint8
        assert result[50, 50] == 255
        assert result[0, 0] == 0


class TestTags:
    def test_tag_and_filter_cells(self, experiment_with_data):
        experiment_with_data.add_tag("positive", color="#00FF00")
        df = experiment_with_data.get_cells(condition="control")
        cell_ids = df["id"].tolist()[:3]
        experiment_with_data.tag_cells(cell_ids, "positive")

        tagged = experiment_with_data.get_cells(condition="control", tags=["positive"])
        assert len(tagged) == 3

    def test_untag_cells(self, experiment_with_data):
        experiment_with_data.add_tag("positive")
        df = experiment_with_data.get_cells(condition="control")
        cell_ids = df["id"].tolist()
        experiment_with_data.tag_cells(cell_ids, "positive")
        experiment_with_data.untag_cells(cell_ids[:2], "positive")

        tagged = experiment_with_data.get_cells(condition="control", tags=["positive"])
        assert len(tagged) == len(cell_ids) - 2


class TestAnalysisRuns:
    def test_start_and_complete(self, experiment):
        run_id = experiment.start_analysis_run("test_plugin", {"param": 1})
        assert run_id >= 1
        experiment.complete_analysis_run(run_id, status="completed", cell_count=42)


class TestSegmentationRuns:
    def test_add_segmentation_run(self, experiment):
        experiment.add_channel("DAPI")
        seg_id = experiment.add_segmentation_run(
            channel="DAPI", model_name="cyto3",
            parameters={"diameter": 30}
        )
        assert seg_id >= 1


# === Name validation (path traversal prevention) ===


class TestNameValidation:
    def test_channel_name_with_path_traversal(self, experiment):
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_channel("../evil")

    def test_channel_name_with_slash(self, experiment):
        with pytest.raises(ValueError, match="invalid characters"):
            experiment.add_channel("DAPI/GFP")

    def test_condition_name_with_dotdot(self, experiment):
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_condition("a..b")

    def test_condition_name_empty(self, experiment):
        with pytest.raises(ValueError, match="must not be empty"):
            experiment.add_condition("")

    def test_fov_name_with_path_traversal(self, experiment):
        experiment.add_condition("control")
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_fov("../../etc", condition="control")

    def test_timepoint_name_with_slash(self, experiment):
        with pytest.raises(ValueError, match="invalid characters"):
            experiment.add_timepoint("t0/evil")

    def test_valid_names_pass(self, experiment):
        experiment.add_channel("DAPI-488")
        experiment.add_channel("GFP_signal")
        experiment.add_condition("control.1")
        experiment.add_timepoint("t0")


# === P2/P3 review fixes ===


class TestGetCellCountExplicit:
    def test_count_all(self, experiment_with_data):
        assert experiment_with_data.get_cell_count() == 10

    def test_count_by_condition(self, experiment_with_data):
        assert experiment_with_data.get_cell_count(condition="control") == 10

    def test_count_by_condition_and_fov(self, experiment_with_data):
        assert experiment_with_data.get_cell_count(condition="control", fov="r1") == 10

    def test_count_fov_without_condition_raises(self, experiment_with_data):
        with pytest.raises(ValueError, match="'condition' is required"):
            experiment_with_data.get_cell_count(fov="r1")


class TestGetCellsFovFilter:
    def test_fov_without_condition_raises(self, experiment_with_data):
        with pytest.raises(ValueError, match="'condition' is required"):
            experiment_with_data.get_cells(fov="r1")


class TestExportCsvNoKwargs:
    def test_export_still_works(self, experiment_with_data, tmp_path):
        csv_path = tmp_path / "results.csv"
        experiment_with_data.export_csv(csv_path, channels=["GFP"])
        df = pd.read_csv(csv_path)
        assert "cell_id" in df.columns


class TestAddChannelIsSegmentation:
    def test_is_segmentation_flag(self, experiment):
        experiment.add_channel("DAPI", is_segmentation=True)
        ch = experiment.get_channel("DAPI")
        assert ch.is_segmentation is True

    def test_default_not_segmentation(self, experiment):
        experiment.add_channel("GFP")
        ch = experiment.get_channel("GFP")
        assert ch.is_segmentation is False


class TestIntrospection:
    def test_get_tags(self, experiment):
        experiment.add_tag("positive", color="#00FF00")
        experiment.add_tag("negative")
        assert experiment.get_tags() == ["positive", "negative"]

    def test_get_tags_empty(self, experiment):
        assert experiment.get_tags() == []

    def test_get_segmentation_runs(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_segmentation_run(channel="DAPI", model_name="cyto3", parameters={"diameter": 30})
        runs = experiment.get_segmentation_runs()
        assert len(runs) == 1
        assert runs[0]["channel"] == "DAPI"
        assert runs[0]["model_name"] == "cyto3"
        assert runs[0]["parameters"] == {"diameter": 30}

    def test_get_analysis_runs(self, experiment):
        experiment.start_analysis_run("my_plugin", {"threshold": 100})
        runs = experiment.get_analysis_runs()
        assert len(runs) == 1
        assert runs[0]["plugin_name"] == "my_plugin"
        assert runs[0]["parameters"] == {"threshold": 100}


class TestExperimentStoreRepr:
    def test_repr(self, experiment):
        r = repr(experiment)
        assert "ExperimentStore" in r
        assert str(experiment.path) in r


class TestFrozenDataclasses:
    def test_channel_config_frozen(self):
        from percell3.core.models import ChannelConfig
        ch = ChannelConfig(id=1, name="DAPI")
        with pytest.raises(AttributeError):
            ch.name = "GFP"

    def test_fov_info_frozen(self):
        from percell3.core.models import FovInfo
        r = FovInfo(id=1, name="r1", condition="control")
        with pytest.raises(AttributeError):
            r.name = "r2"

    def test_cell_record_frozen(self):
        cell = CellRecord(
            fov_id=1, segmentation_id=1, label_value=1,
            centroid_x=100, centroid_y=200,
            bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
            area_pixels=1200,
        )
        with pytest.raises(AttributeError):
            cell.area_pixels = 999

    def test_measurement_record_frozen(self):
        m = MeasurementRecord(cell_id=1, channel_id=1, metric="mean", value=42.0)
        with pytest.raises(AttributeError):
            m.value = 99.0
