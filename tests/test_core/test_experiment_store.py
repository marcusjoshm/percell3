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
    BioRepNotFoundError,
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
        group = store["control/N1/r1"]
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


# === Biological Replicates ===


class TestBioReps:
    """Tests for the biological replicate layer (condition-scoped)."""

    def test_no_default_bio_rep_at_creation(self, experiment):
        """New experiment has no bio reps until a condition is created."""
        reps = experiment.get_bio_reps()
        assert reps == []

    def test_bio_rep_created_lazily_with_fov(self, experiment):
        """Default N1 bio rep is created per-condition when first FOV is added."""
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control")
        reps = experiment.get_bio_reps(condition="control")
        assert reps == ["N1"]

    def test_add_bio_rep(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N2", condition="control")
        reps = experiment.get_bio_reps(condition="control")
        assert "N2" in reps

    def test_add_duplicate_bio_rep_raises(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N1", condition="control")
        with pytest.raises(DuplicateError):
            experiment.add_bio_rep("N1", condition="control")

    def test_same_bio_rep_name_different_conditions(self, experiment):
        """N1/control and N1/treated are separate bio reps."""
        experiment.add_condition("control")
        experiment.add_condition("treated")
        experiment.add_bio_rep("N1", condition="control")
        experiment.add_bio_rep("N1", condition="treated")
        assert experiment.get_bio_reps(condition="control") == ["N1"]
        assert experiment.get_bio_reps(condition="treated") == ["N1"]

    def test_get_nonexistent_bio_rep_raises(self, experiment):
        with pytest.raises(BioRepNotFoundError):
            experiment.get_bio_rep("N999")

    def test_add_fov_auto_creates_default_bio_rep(self, experiment):
        """Adding FOV without bio_rep auto-creates N1 for the condition."""
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control")
        fovs = experiment.get_fovs(condition="control")
        assert len(fovs) == 1
        assert fovs[0].bio_rep == "N1"

    def test_add_fov_explicit_bio_rep(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N2", condition="control")
        experiment.add_fov("r1", condition="control", bio_rep="N2")
        fovs = experiment.get_fovs(condition="control", bio_rep="N2")
        assert len(fovs) == 1
        assert fovs[0].bio_rep == "N2"

    def test_add_fov_defaults_to_n1_when_multiple(self, experiment):
        """When N2+ bio reps exist, bio_rep=None defaults to N1."""
        experiment.add_condition("control")
        experiment.add_bio_rep("N1", condition="control")
        experiment.add_bio_rep("N2", condition="control")
        experiment.add_fov("r1", condition="control")  # should default to N1
        fovs = experiment.get_fovs(condition="control", bio_rep="N1")
        assert len(fovs) == 1
        assert fovs[0].name == "r1"

    def test_get_fovs_filter_by_bio_rep(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N2", condition="control")
        experiment.add_fov("r1", condition="control", bio_rep="N1")
        experiment.add_fov("r2", condition="control", bio_rep="N2")

        n1_fovs = experiment.get_fovs(condition="control", bio_rep="N1")
        assert len(n1_fovs) == 1
        assert n1_fovs[0].name == "r1"

        n2_fovs = experiment.get_fovs(condition="control", bio_rep="N2")
        assert len(n2_fovs) == 1
        assert n2_fovs[0].name == "r2"

    def test_same_fov_name_different_bio_reps(self, experiment):
        """Same FOV name is allowed in different bio reps."""
        experiment.add_condition("control")
        experiment.add_bio_rep("N2", condition="control")
        experiment.add_fov("r1", condition="control", bio_rep="N1")
        experiment.add_fov("r1", condition="control", bio_rep="N2")

        all_fovs = experiment.get_fovs(condition="control")
        assert len(all_fovs) == 2

    def test_fov_info_has_bio_rep(self, experiment):
        """FovInfo includes bio_rep field."""
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control")
        fov = experiment.get_fovs(condition="control")[0]
        assert fov.bio_rep == "N1"

    def test_write_read_image_with_bio_rep(self, experiment):
        """Image I/O works with explicit bio_rep."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control")

        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        experiment.write_image("r1", "control", "DAPI", data, bio_rep="N1")
        result = experiment.read_image_numpy("r1", "control", "DAPI", bio_rep="N1")
        np.testing.assert_array_equal(result, data)

    def test_zarr_path_is_condition_bio_rep_fov(self, experiment):
        """Zarr group path is condition/bio_rep/fov."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        experiment.add_fov("r1", condition="control")

        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        experiment.write_image("r1", "control", "DAPI", data)

        store = zarr.open(str(experiment.images_zarr_path), mode="r")
        assert "control/N1/r1" in store

    def test_get_cells_bio_rep_column(self, experiment):
        """Cell query results include bio_rep_name."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("r1", condition="control")
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        experiment.add_cells(cells)

        df = experiment.get_cells(condition="control")
        assert "bio_rep_name" in df.columns
        assert df["bio_rep_name"].iloc[0] == "N1"

    def test_get_cells_filter_by_bio_rep(self, experiment):
        """get_cells(bio_rep=...) filters cells by bio rep."""
        experiment.add_condition("control")
        experiment.add_bio_rep("N2", condition="control")
        experiment.add_channel("DAPI")
        fov1 = experiment.add_fov("r1", condition="control", bio_rep="N1")
        fov2 = experiment.add_fov("r2", condition="control", bio_rep="N2")
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        cells_n1 = [
            CellRecord(
                fov_id=fov1, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cells_n2 = [
            CellRecord(
                fov_id=fov2, segmentation_id=seg_id, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 6)
        ]
        experiment.add_cells(cells_n1)
        experiment.add_cells(cells_n2)

        assert experiment.get_cell_count(condition="control", bio_rep="N1") == 3
        assert experiment.get_cell_count(condition="control", bio_rep="N2") == 5
        assert experiment.get_cell_count() == 8

    def test_measurement_pivot_includes_bio_rep(self, experiment):
        """get_measurement_pivot() result includes bio_rep_name column."""
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("r1", condition="control")
        seg_id = experiment.add_segmentation_run(channel="DAPI", model_name="cyto3")

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        cell_ids = experiment.add_cells(cells)

        gfp = experiment.get_channel("GFP")
        experiment.add_measurements([
            MeasurementRecord(cell_id=cell_ids[0], channel_id=gfp.id,
                              metric="mean_intensity", value=42.0)
        ])

        pivot = experiment.get_measurement_pivot()
        assert "bio_rep_name" in pivot.columns
        assert pivot["bio_rep_name"].iloc[0] == "N1"


class TestBioRepNameValidation:
    """Security tests: name validation on bio rep names."""

    def test_path_traversal(self, experiment):
        experiment.add_condition("control")
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_bio_rep("../evil", condition="control")

    def test_slash(self, experiment):
        experiment.add_condition("control")
        with pytest.raises(ValueError, match="invalid characters"):
            experiment.add_bio_rep("N1/evil", condition="control")

    def test_empty_name(self, experiment):
        experiment.add_condition("control")
        with pytest.raises(ValueError, match="must not be empty"):
            experiment.add_bio_rep("", condition="control")

    def test_valid_names(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N1", condition="control")
        experiment.add_bio_rep("bio-rep-3", condition="control")
        experiment.add_bio_rep("sample_A", condition="control")
        assert len(experiment.get_bio_reps(condition="control")) == 3


class TestRenameExperiment:
    def test_rename_experiment(self, experiment):
        experiment.rename_experiment("New Name")
        assert experiment.name == "New Name"


class TestRenameCondition:
    def test_rename_condition(self, experiment):
        experiment.add_condition("old_cond")
        experiment.rename_condition("old_cond", "new_cond")
        assert "new_cond" in experiment.get_conditions()
        assert "old_cond" not in experiment.get_conditions()

    def test_rename_condition_with_data(self, experiment):
        """Rename a condition that has images stored in zarr."""
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        experiment.add_fov("FOV1", "ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image("FOV1", "ctrl", "DAPI", data)

        experiment.rename_condition("ctrl", "control")
        assert "control" in experiment.get_conditions()
        # Verify data is still readable under the new name
        img = experiment.read_image("FOV1", "control", "DAPI")
        assert img.shape == (64, 64)


class TestRenameChannel:
    def test_rename_channel(self, experiment):
        experiment.add_channel("DAPI")
        experiment.rename_channel("DAPI", "Hoechst")
        ch_names = [ch.name for ch in experiment.get_channels()]
        assert "Hoechst" in ch_names
        assert "DAPI" not in ch_names


class TestRenameBioRep:
    def test_rename_bio_rep(self, experiment):
        experiment.add_condition("ctrl")
        experiment.add_fov("FOV1", "ctrl")  # auto-creates N1
        experiment.rename_bio_rep("N1", "Rep1", condition="ctrl")
        assert "Rep1" in experiment.get_bio_reps(condition="ctrl")
        assert "N1" not in experiment.get_bio_reps(condition="ctrl")

    def test_rename_bio_rep_with_data(self, experiment):
        """Rename a bio-rep that has images stored in zarr."""
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        experiment.add_fov("FOV1", "ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image("FOV1", "ctrl", "DAPI", data)

        experiment.rename_bio_rep("N1", "Rep1", condition="ctrl")
        assert "Rep1" in experiment.get_bio_reps(condition="ctrl")
        img = experiment.read_image("FOV1", "ctrl", "DAPI", bio_rep="Rep1")
        assert img.shape == (64, 64)


class TestRenameFov:
    def test_rename_fov(self, experiment):
        experiment.add_condition("ctrl")
        experiment.add_fov("FOV1", "ctrl")
        experiment.rename_fov("FOV1", "FOV_A", "ctrl")
        fov_names = [f.name for f in experiment.get_fovs()]
        assert "FOV_A" in fov_names
        assert "FOV1" not in fov_names

    def test_rename_fov_with_data(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        experiment.add_fov("FOV1", "ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image("FOV1", "ctrl", "DAPI", data)

        experiment.rename_fov("FOV1", "FOV_A", "ctrl")
        img = experiment.read_image("FOV_A", "ctrl", "DAPI")
        assert img.shape == (64, 64)


class TestDeleteCellsForFov:
    def test_deletes_cells_and_measurements(self, experiment_with_data):
        store = experiment_with_data
        # experiment_with_data has 10 cells on FOV "r1" / condition "control"
        assert store.get_cell_count(condition="control", fov="r1") == 10

        deleted = store.delete_cells_for_fov("r1", "control")
        assert deleted == 10
        assert store.get_cell_count(condition="control", fov="r1") == 0

    def test_returns_zero_for_empty_fov(self, experiment):
        experiment.add_condition("ctrl")
        experiment.add_fov("r1", "ctrl", width=32, height=32)
        assert experiment.delete_cells_for_fov("r1", "ctrl") == 0


class TestGetFovSegmentationSummary:
    def test_with_segmented_fovs(self, experiment_with_data):
        store = experiment_with_data
        summary = store.get_fov_segmentation_summary()
        # experiment_with_data has 10 cells on FOV "r1" with model "cyto3"
        fovs = store.get_fovs()
        r1 = [f for f in fovs if f.name == "r1"][0]
        assert summary[r1.id][0] == 10
        assert summary[r1.id][1] == "cyto3"

    def test_empty_experiment(self, experiment):
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("r1", "ctrl", width=32, height=32)
        summary = experiment.get_fov_segmentation_summary()
        assert summary[fov_id] == (0, None)
