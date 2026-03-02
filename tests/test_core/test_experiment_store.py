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
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord


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
    fov_id = experiment.add_fov("control", width=256, height=256)
    seg_id = experiment.add_segmentation(
        "seg_ctrl", "cellular", 256, 256,
        source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
    )

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
                          metric="mean_intensity", value=42.0 + cid,
                          segmentation_id=seg_id)
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


# === Acceptance Test 3: Condition/FOV management (flat model) ===


class TestConditionsAndFovs:
    def test_conditions_and_fovs(self, experiment):
        experiment.add_condition("control")
        experiment.add_condition("treated")
        experiment.add_fov("control", width=2048, height=2048)
        experiment.add_fov("control", width=2048, height=2048)
        experiment.add_fov("treated", width=2048, height=2048)

        assert experiment.get_conditions() == ["control", "treated"]
        control_fovs = experiment.get_fovs(condition="control")
        assert len(control_fovs) == 2

    def test_timepoints(self, experiment):
        experiment.add_timepoint("t0", time_seconds=0.0)
        experiment.add_timepoint("t1", time_seconds=60.0)
        assert experiment.get_timepoints() == ["t0", "t1"]

    def test_fov_display_name_auto_generated(self, experiment):
        experiment.add_condition("HS")
        fov_id = experiment.add_fov("HS")
        fov = experiment.get_fov_by_id(fov_id)
        assert fov.display_name == "HS_N1_FOV_001"

    def test_fov_display_name_sequential(self, experiment):
        experiment.add_condition("HS")
        experiment.add_fov("HS")
        experiment.add_fov("HS")
        fovs = experiment.get_fovs(condition="HS")
        assert fovs[0].display_name == "HS_N1_FOV_001"
        assert fovs[1].display_name == "HS_N1_FOV_002"

    def test_fov_explicit_display_name(self, experiment):
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", display_name="my_custom_fov")
        fov = experiment.get_fov_by_id(fov_id)
        assert fov.display_name == "my_custom_fov"


# === Acceptance Test 4: Write and read OME-Zarr image ===


class TestImageIO:
    def test_write_and_read_image(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=512, height=512)

        data = np.random.randint(0, 65535, (512, 512), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        result_dask = experiment.read_image(fov_id, "DAPI")
        assert isinstance(result_dask, da.Array)

        result_np = experiment.read_image_numpy(fov_id, "DAPI")
        np.testing.assert_array_equal(result_np, data)

    def test_multi_channel_image(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=256, height=256)

        dapi = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
        gfp = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)

        experiment.write_image(fov_id, "DAPI", dapi)
        experiment.write_image(fov_id, "GFP", gfp)

        result_dapi = experiment.read_image_numpy(fov_id, "DAPI")
        result_gfp = experiment.read_image_numpy(fov_id, "GFP")

        np.testing.assert_array_equal(result_dapi, dapi)
        np.testing.assert_array_equal(result_gfp, gfp)


# === Acceptance Test 5: Cell records ===


class TestCells:
    def test_add_and_query_cells(self, experiment):
        experiment.add_channel("DAPI", role="nucleus")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

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

    def test_cell_count_by_fov_id(self, experiment_with_data):
        fov = experiment_with_data.get_fovs()[0]
        assert experiment_with_data.get_cell_count(fov_id=fov.id) == 10

    def test_cell_count_by_condition(self, experiment_with_data):
        assert experiment_with_data.get_cell_count(condition="control") == 10


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
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

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
                              metric="mean_intensity", value=42.0,
                              segmentation_id=seg_id)
            for cid in cell_ids
        ]
        rfp_measurements = [
            MeasurementRecord(cell_id=cid, channel_id=rfp.id,
                              metric="mean_intensity", value=99.0,
                              segmentation_id=seg_id)
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
        fov_id = experiment.add_fov("control", width=512, height=512)
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 512, 512,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

        labels = np.zeros((512, 512), dtype=np.int32)
        labels[100:150, 100:150] = 1
        labels[200:260, 200:260] = 2

        experiment.write_labels(labels, seg_id)
        result = experiment.read_labels(seg_id)
        np.testing.assert_array_equal(result, labels)


# === Acceptance Test 8: NGFF metadata compliance ===


class TestNGFFMetadata:
    def test_zarr_has_ngff_metadata(self, experiment):
        experiment.add_channel("DAPI", color="#0000FF")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=128, height=128)

        data = np.random.randint(0, 65535, (128, 128), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        store = zarr.open(str(experiment.images_zarr_path), mode="r")
        group = store[f"fov_{fov_id}"]
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
        fov_id = experiment.add_fov("control", width=128, height=128)
        thr_id = experiment.add_threshold(
            "thr_test", "otsu", 128, 128,
            source_fov_id=fov_id, source_channel="GFP",
        )

        mask = np.zeros((128, 128), dtype=bool)
        mask[20:80, 20:80] = True

        experiment.write_mask(mask, thr_id)
        result = experiment.read_mask(thr_id)
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


class TestSegmentations:
    def test_add_segmentation(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
            parameters={"diameter": 30},
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

    def test_fov_display_name_with_path_traversal(self, experiment):
        experiment.add_condition("control")
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_fov("control", display_name="../../etc")

    def test_timepoint_name_with_slash(self, experiment):
        with pytest.raises(ValueError, match="invalid characters"):
            experiment.add_timepoint("t0/evil")

    def test_valid_names_pass(self, experiment):
        experiment.add_channel("DAPI-488")
        experiment.add_channel("GFP_signal")
        experiment.add_condition("control.1")
        experiment.add_timepoint("t0")


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

    def test_get_segmentations(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI",
            model_name="cyto3", parameters={"diameter": 30},
        )
        segs = experiment.get_segmentations()
        assert len(segs) == 1
        assert segs[0].source_channel == "DAPI"
        assert segs[0].model_name == "cyto3"
        assert segs[0].parameters == {"diameter": 30}

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
        r = FovInfo(id=1, display_name="ctrl_N1_FOV_001", condition="control")
        with pytest.raises(AttributeError):
            r.display_name = "other"

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


# === Biological Replicates (experiment-global) ===


class TestBioReps:
    """Tests for the biological replicate layer (experiment-global)."""

    def test_no_default_bio_rep_at_creation(self, experiment):
        """New experiment has no bio reps until one is created."""
        reps = experiment.get_bio_reps()
        assert reps == []

    def test_bio_rep_created_lazily_with_fov(self, experiment):
        """Default N1 bio rep is created when first FOV is added."""
        experiment.add_condition("control")
        experiment.add_fov("control")
        reps = experiment.get_bio_reps()
        assert reps == ["N1"]

    def test_add_bio_rep(self, experiment):
        experiment.add_bio_rep("N2")
        reps = experiment.get_bio_reps()
        assert "N2" in reps

    def test_add_duplicate_bio_rep_raises(self, experiment):
        experiment.add_bio_rep("N1")
        with pytest.raises(DuplicateError):
            experiment.add_bio_rep("N1")

    def test_bio_reps_are_global(self, experiment):
        """Bio reps are shared across all conditions."""
        experiment.add_condition("control")
        experiment.add_condition("treated")
        experiment.add_bio_rep("N1")
        experiment.add_fov("control", bio_rep="N1")
        experiment.add_fov("treated", bio_rep="N1")
        assert experiment.get_bio_reps() == ["N1"]

    def test_get_nonexistent_bio_rep_raises(self, experiment):
        with pytest.raises(BioRepNotFoundError):
            experiment.get_bio_rep("N999")

    def test_add_fov_auto_creates_default_bio_rep(self, experiment):
        """Adding FOV without bio_rep auto-creates N1."""
        experiment.add_condition("control")
        experiment.add_fov("control")
        fovs = experiment.get_fovs(condition="control")
        assert len(fovs) == 1
        assert fovs[0].bio_rep == "N1"

    def test_add_fov_explicit_bio_rep(self, experiment):
        experiment.add_condition("control")
        experiment.add_bio_rep("N2")
        experiment.add_fov("control", bio_rep="N2")
        fovs = experiment.get_fovs(condition="control", bio_rep="N2")
        assert len(fovs) == 1
        assert fovs[0].bio_rep == "N2"

    def test_fov_info_has_bio_rep(self, experiment):
        """FovInfo includes bio_rep field."""
        experiment.add_condition("control")
        experiment.add_fov("control")
        fov = experiment.get_fovs(condition="control")[0]
        assert fov.bio_rep == "N1"

    def test_write_read_image_with_bio_rep(self, experiment):
        """Image I/O works with fov_id regardless of bio_rep."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)
        result = experiment.read_image_numpy(fov_id, "DAPI")
        np.testing.assert_array_equal(result, data)

    def test_zarr_path_uses_fov_id(self, experiment):
        """Zarr group path is fov_{id}, not condition/bio_rep/fov."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        data = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        store = zarr.open(str(experiment.images_zarr_path), mode="r")
        assert f"fov_{fov_id}" in store

    def test_get_cells_bio_rep_column(self, experiment):
        """Cell query results include bio_rep_name."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

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
        experiment.add_bio_rep("N1")
        experiment.add_bio_rep("N2")
        experiment.add_channel("DAPI")
        fov1 = experiment.add_fov("control", bio_rep="N1")
        fov2 = experiment.add_fov("control", bio_rep="N2")
        seg_id1 = experiment.add_segmentation(
            "seg_n1", "cellular", 64, 64,
            source_fov_id=fov1, source_channel="DAPI", model_name="cyto3",
        )
        seg_id2 = experiment.add_segmentation(
            "seg_n2", "cellular", 64, 64,
            source_fov_id=fov2, source_channel="DAPI", model_name="cyto3",
        )

        cells_n1 = [
            CellRecord(
                fov_id=fov1, segmentation_id=seg_id1, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 4)
        ]
        cells_n2 = [
            CellRecord(
                fov_id=fov2, segmentation_id=seg_id2, label_value=i,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
            for i in range(1, 6)
        ]
        experiment.add_cells(cells_n1)
        experiment.add_cells(cells_n2)

        n1_cells = experiment.get_cells(bio_rep="N1")
        assert len(n1_cells) == 3
        n2_cells = experiment.get_cells(bio_rep="N2")
        assert len(n2_cells) == 5
        assert experiment.get_cell_count() == 8

    def test_measurement_pivot_includes_bio_rep(self, experiment):
        """get_measurement_pivot() result includes bio_rep_name column."""
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

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
                              metric="mean_intensity", value=42.0,
                              segmentation_id=seg_id)
        ])

        pivot = experiment.get_measurement_pivot()
        assert "bio_rep_name" in pivot.columns
        assert pivot["bio_rep_name"].iloc[0] == "N1"

    def test_measurement_pivot_mixed_scopes(self, experiment):
        """Pivot with mixed scopes: whole_cell gets clean names, mask scopes get suffix."""
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="GFP", model_name="cyto3",
        )

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
                              metric="mean_intensity", value=42.0,
                              scope="whole_cell", segmentation_id=seg_id),
            MeasurementRecord(cell_id=cell_ids[0], channel_id=gfp.id,
                              metric="mean_intensity", value=30.0,
                              scope="mask_inside", segmentation_id=seg_id),
            MeasurementRecord(cell_id=cell_ids[0], channel_id=gfp.id,
                              metric="mean_intensity", value=12.0,
                              scope="mask_outside", segmentation_id=seg_id),
        ])

        pivot = experiment.get_measurement_pivot()
        assert "GFP_mean_intensity" in pivot.columns
        assert "GFP_mean_intensity_mask_inside" in pivot.columns
        assert "GFP_mean_intensity_mask_outside" in pivot.columns
        assert pivot["GFP_mean_intensity"].iloc[0] == 42.0
        assert pivot["GFP_mean_intensity_mask_inside"].iloc[0] == 30.0
        assert pivot["GFP_mean_intensity_mask_outside"].iloc[0] == 12.0

    def test_measurement_pivot_scope_filter(self, experiment):
        """Pivot with scope filter returns only that scope."""
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="GFP", model_name="cyto3",
        )

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
                              metric="mean_intensity", value=42.0,
                              scope="whole_cell", segmentation_id=seg_id),
            MeasurementRecord(cell_id=cell_ids[0], channel_id=gfp.id,
                              metric="mean_intensity", value=30.0,
                              scope="mask_inside", segmentation_id=seg_id),
        ])

        pivot = experiment.get_measurement_pivot(scope="whole_cell")
        assert "GFP_mean_intensity" in pivot.columns
        assert "GFP_mean_intensity_mask_inside" not in pivot.columns

        pivot2 = experiment.get_measurement_pivot(scope="mask_inside")
        assert "GFP_mean_intensity_mask_inside" in pivot2.columns
        assert len(pivot2) == 1


class TestBioRepNameValidation:
    """Security tests: name validation on bio rep names."""

    def test_path_traversal(self, experiment):
        with pytest.raises(ValueError, match="must not contain"):
            experiment.add_bio_rep("../evil")

    def test_slash(self, experiment):
        with pytest.raises(ValueError, match="invalid characters"):
            experiment.add_bio_rep("N1/evil")

    def test_empty_name(self, experiment):
        with pytest.raises(ValueError, match="must not be empty"):
            experiment.add_bio_rep("")

    def test_valid_names(self, experiment):
        experiment.add_bio_rep("N1")
        experiment.add_bio_rep("bio-rep-3")
        experiment.add_bio_rep("sample_A")
        assert len(experiment.get_bio_reps()) == 3


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
        """Rename condition is DB-only; zarr paths use fov_id."""
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        experiment.rename_condition("ctrl", "control")
        assert "control" in experiment.get_conditions()
        img = experiment.read_image(fov_id, "DAPI")
        assert img.shape == (64, 64)


class TestRenameChannel:
    def test_rename_channel(self, experiment):
        experiment.add_channel("DAPI")
        experiment.rename_channel("DAPI", "Hoechst")
        ch_names = [ch.name for ch in experiment.get_channels()]
        assert "Hoechst" in ch_names
        assert "DAPI" not in ch_names

    def test_rename_channel_independent_of_masks(self, experiment):
        """Masks and particle labels are keyed by threshold_id, not channel name."""
        experiment.add_channel("ch00")
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=64, height=64)

        thr_id = experiment.add_threshold(
            "thr_test", "otsu", 64, 64,
            source_fov_id=fov_id, source_channel="ch00",
        )

        # Write a mask and particle labels
        mask = np.zeros((64, 64), dtype=np.int32)
        mask[10:20, 10:20] = 1
        experiment.write_mask(mask, thr_id)

        plabels = np.zeros((64, 64), dtype=np.int32)
        plabels[12:18, 12:18] = 1
        experiment.write_particle_labels(plabels, thr_id)

        # Rename the channel
        experiment.rename_channel("ch00", "GFP")

        # Masks and particle labels are keyed by threshold_id, unaffected by rename
        result = experiment.read_particle_labels(thr_id)
        assert result.shape == (64, 64)
        assert result[15, 15] == 1

        mask_result = experiment.read_mask(thr_id)
        assert mask_result.shape == (64, 64)
        assert mask_result[15, 15] > 0


class TestRenameBioRep:
    def test_rename_bio_rep(self, experiment):
        experiment.add_condition("ctrl")
        experiment.add_fov("ctrl")  # auto-creates N1
        experiment.rename_bio_rep("N1", "Rep1")
        assert "Rep1" in experiment.get_bio_reps()
        assert "N1" not in experiment.get_bio_reps()

    def test_rename_bio_rep_with_data(self, experiment):
        """Rename bio_rep is DB-only; zarr paths use fov_id."""
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        experiment.rename_bio_rep("N1", "Rep1")
        assert "Rep1" in experiment.get_bio_reps()
        img = experiment.read_image(fov_id, "DAPI")
        assert img.shape == (64, 64)


class TestRenameFov:
    def test_rename_fov(self, experiment):
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl")
        experiment.rename_fov(fov_id, "FOV_A")
        fov = experiment.get_fov_by_id(fov_id)
        assert fov.display_name == "FOV_A"

    def test_rename_fov_with_data(self, experiment):
        """Rename FOV is DB-only; zarr paths use fov_id."""
        experiment.add_channel("DAPI")
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=64, height=64)
        data = np.zeros((64, 64), dtype=np.uint16)
        experiment.write_image(fov_id, "DAPI", data)

        experiment.rename_fov(fov_id, "FOV_A")
        img = experiment.read_image(fov_id, "DAPI")
        assert img.shape == (64, 64)


class TestDeleteCellsForFov:
    def test_deletes_cells_and_measurements(self, experiment_with_data):
        store = experiment_with_data
        fov = store.get_fovs()[0]
        assert store.get_cell_count(fov_id=fov.id) == 10

        deleted = store.delete_cells_for_fov(fov.id)
        assert deleted == 10
        assert store.get_cell_count(fov_id=fov.id) == 0

    def test_returns_zero_for_empty_fov(self, experiment):
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=32, height=32)
        assert experiment.delete_cells_for_fov(fov_id) == 0


class TestDeleteFov:
    """Tests for ExperimentStore.delete_fov()."""

    def test_deletes_fov_and_all_data(self, experiment_with_data):
        store = experiment_with_data
        fov = store.get_fovs()[0]
        fov_id = fov.id

        # Precondition: FOV exists with cells
        assert store.get_cell_count(fov_id=fov_id) == 10

        store.delete_fov(fov_id)

        # FOV row gone
        fovs = store.get_fovs()
        assert all(f.id != fov_id for f in fovs)

    def test_deletes_fov_with_no_cells(self, experiment):
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=32, height=32)
        assert len(experiment.get_fovs()) == 1

        experiment.delete_fov(fov_id)
        assert len(experiment.get_fovs()) == 0

    def test_raises_for_nonexistent_fov(self, experiment):
        from percell3.core.exceptions import ExperimentError

        with pytest.raises(ExperimentError):
            experiment.delete_fov(9999)


class TestGetFovSegmentationSummary:
    def test_with_segmented_fovs(self, experiment_with_data):
        store = experiment_with_data
        summary = store.get_fov_segmentation_summary()
        fov = store.get_fovs()[0]
        assert summary[fov.id][0] == 10
        assert summary[fov.id][1] == "cyto3"

    def test_empty_experiment(self, experiment):
        experiment.add_condition("ctrl")
        fov_id = experiment.add_fov("ctrl", width=32, height=32)
        summary = experiment.get_fov_segmentation_summary()
        assert summary[fov_id] == (0, None)


# === Particle CRUD ===


class TestParticles:
    """Tests for particle add/get/delete via ExperimentStore."""

    @pytest.fixture
    def store_with_threshold(self, experiment):
        """Experiment with a channel, condition, FOV, segmentation, cells, and threshold."""
        experiment.add_channel("DAPI", role="nucleus")
        experiment.add_channel("GFP", role="signal")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=128, height=128)
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 128, 128,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )
        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=i,
                centroid_x=50.0 + i, centroid_y=60.0 + i,
                bbox_x=40 + i, bbox_y=50 + i, bbox_w=20, bbox_h=20,
                area_pixels=300.0,
            )
            for i in range(1, 4)
        ]
        experiment.add_cells(cells)
        thr_id = experiment.add_threshold(
            "thr_test", "otsu", 128, 128,
            source_fov_id=fov_id, source_channel="GFP",
        )
        return experiment, thr_id, fov_id

    def test_add_and_get_particles(self, store_with_threshold):
        store, thr_id, fov_id = store_with_threshold

        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=55.0, centroid_y=65.0,
                bbox_x=50, bbox_y=60, bbox_w=10, bbox_h=10,
                area_pixels=80.0, circularity=0.9,
            ),
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=2,
                centroid_x=57.0, centroid_y=67.0,
                bbox_x=52, bbox_y=62, bbox_w=8, bbox_h=8,
                area_pixels=50.0,
            ),
        ]
        store.add_particles(particles)

        df = store.get_particles(fov_id=fov_id)
        assert len(df) == 2
        assert "circularity" in df.columns

    def test_get_particles_by_threshold(self, store_with_threshold):
        store, thr_id, fov_id = store_with_threshold

        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=55.0, centroid_y=65.0,
                bbox_x=50, bbox_y=60, bbox_w=10, bbox_h=10,
                area_pixels=80.0,
            ),
        ]
        store.add_particles(particles)

        df = store.get_particles(threshold_id=thr_id)
        assert len(df) == 1

    def test_get_particles_empty(self, store_with_threshold):
        store, thr_id, fov_id = store_with_threshold
        df = store.get_particles(fov_id=fov_id)
        assert len(df) == 0

    def test_delete_particles_for_fov(self, store_with_threshold):
        store, thr_id, fov_id = store_with_threshold

        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=i,
                centroid_x=55.0, centroid_y=65.0,
                bbox_x=50, bbox_y=60, bbox_w=10, bbox_h=10,
                area_pixels=80.0,
            )
            for i in range(1, 4)
        ]
        store.add_particles(particles)
        deleted = store.delete_particles_for_fov(fov_id)
        assert deleted == 3

        df = store.get_particles(threshold_id=thr_id)
        assert len(df) == 0

    def test_delete_particles_for_threshold(self, store_with_threshold):
        store, thr_id, fov_id = store_with_threshold

        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=55.0, centroid_y=65.0,
                bbox_x=50, bbox_y=60, bbox_w=10, bbox_h=10,
                area_pixels=80.0,
            ),
        ]
        store.add_particles(particles)
        deleted = store.delete_particles_for_threshold(thr_id)
        assert deleted == 1


class TestThresholds:
    def test_get_thresholds(self, experiment):
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        experiment.add_threshold(
            "thr_test", "otsu", 64, 64,
            source_fov_id=fov_id, source_channel="GFP",
            parameters={"group": "g1"},
        )
        thresholds = experiment.get_thresholds()
        assert len(thresholds) == 1
        assert thresholds[0].source_channel == "GFP"
        assert thresholds[0].method == "otsu"
        assert thresholds[0].parameters == {"group": "g1"}


class TestDeleteTagsByPrefix:
    def test_delete_matching_prefix(self, experiment_with_data):
        store = experiment_with_data
        store.add_tag("group:GFP:mean:g1")
        store.add_tag("group:GFP:mean:g2")
        store.add_tag("positive")

        df = store.get_cells(condition="control")
        all_ids = df["id"].tolist()

        store.tag_cells(all_ids[:5], "group:GFP:mean:g1")
        store.tag_cells(all_ids[5:], "group:GFP:mean:g2")
        store.tag_cells(all_ids[:3], "positive")

        deleted = store.delete_tags_by_prefix("group:GFP:mean:")
        assert deleted == 10  # 5 + 5

        # "positive" tags should remain
        tagged = store.get_cells(condition="control", tags=["positive"])
        assert len(tagged) == 3

    def test_delete_with_cell_ids_scope(self, experiment_with_data):
        store = experiment_with_data
        store.add_tag("group:GFP:mean:g1")

        df = store.get_cells(condition="control")
        all_ids = df["id"].tolist()
        store.tag_cells(all_ids, "group:GFP:mean:g1")

        # Only remove from first 3 cells
        deleted = store.delete_tags_by_prefix("group:GFP:mean:", cell_ids=all_ids[:3])
        assert deleted == 3

        # Remaining 7 should still have the tag
        tagged = store.get_cells(condition="control", tags=["group:GFP:mean:g1"])
        assert len(tagged) == 7


class TestParticleLabelIO:
    def test_write_and_read_particle_labels(self, experiment):
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=128, height=128)
        thr_id = experiment.add_threshold(
            "thr_test", "otsu", 128, 128,
            source_fov_id=fov_id, source_channel="GFP",
        )

        labels = np.zeros((128, 128), dtype=np.int32)
        labels[20:40, 20:40] = 1
        labels[60:80, 60:80] = 2

        experiment.write_particle_labels(labels, thr_id)
        result = experiment.read_particle_labels(thr_id)
        np.testing.assert_array_equal(result, labels)

    def test_particle_labels_zarr_path(self, experiment):
        """Particle labels are stored at thresh_{id}/particles/0."""
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control", width=64, height=64)
        thr_id = experiment.add_threshold(
            "thr_test", "otsu", 64, 64,
            source_fov_id=fov_id, source_channel="GFP",
        )

        labels = np.zeros((64, 64), dtype=np.int32)
        labels[10:20, 10:20] = 1
        experiment.write_particle_labels(labels, thr_id)

        store = zarr.open(str(experiment.masks_zarr_path), mode="r")
        assert f"thresh_{thr_id}/particles" in store


# === FOV Status Cache ===


class TestFovStatusCache:
    def test_cache_updated_on_add_cells(self, experiment):
        """Status cache is refreshed when cells are added."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

        # Add fov_config so the status cache can reflect the segmentation
        experiment.set_fov_config_entry(fov_id, seg_id)

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        experiment.add_cells(cells)

        from percell3.core.queries import select_fov_status_cache
        cache = select_fov_status_cache(experiment._conn)
        assert len(cache) == 1
        assert cache[0]["fov_id"] == fov_id
        status = cache[0]["status"]
        assert len(status["segmentations"]) == 1
        assert "cell_count" in status["segmentations"][0]

    def test_cache_updated_on_add_measurements(self, experiment):
        """Status cache is refreshed when measurements are added."""
        experiment.add_channel("DAPI")
        experiment.add_channel("GFP")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

        # Add fov_config so the status cache can reflect the segmentation
        experiment.set_fov_config_entry(fov_id, seg_id)

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
                              metric="mean_intensity", value=42.0,
                              segmentation_id=seg_id)
        ])

        from percell3.core.queries import select_fov_status_cache
        cache = select_fov_status_cache(experiment._conn)
        assert cache[0]["fov_id"] == fov_id
        status = cache[0]["status"]
        assert len(status["segmentations"]) == 1

    def test_cache_cleared_on_delete_cells(self, experiment):
        """Status cache reflects segmentation after cell deletion."""
        experiment.add_channel("DAPI")
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")
        seg_id = experiment.add_segmentation(
            "seg_test", "cellular", 64, 64,
            source_fov_id=fov_id, source_channel="DAPI", model_name="cyto3",
        )

        # Add fov_config so the status cache can reflect the segmentation
        experiment.set_fov_config_entry(fov_id, seg_id)

        cells = [
            CellRecord(
                fov_id=fov_id, segmentation_id=seg_id, label_value=1,
                centroid_x=100, centroid_y=200,
                bbox_x=80, bbox_y=180, bbox_w=40, bbox_h=40,
                area_pixels=1200,
            )
        ]
        experiment.add_cells(cells)
        experiment.delete_cells_for_fov(fov_id)

        from percell3.core.queries import select_fov_status_cache
        cache = select_fov_status_cache(experiment._conn)
        # After deleting cells, segmentation still exists in the cache via fov_config
        status = cache[0]["status"]
        assert len(status["segmentations"]) == 1


# === FOV Tags ===


class TestFovTags:
    def test_add_and_get_fov_tag(self, experiment):
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        experiment.add_fov_tag(fov_id, "needs_review")
        tags = experiment.get_fov_tags(fov_id)
        assert tags == ["needs_review"]

    def test_remove_fov_tag(self, experiment):
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        experiment.add_fov_tag(fov_id, "needs_review")
        experiment.remove_fov_tag(fov_id, "needs_review")
        tags = experiment.get_fov_tags(fov_id)
        assert tags == []

    def test_fov_tag_creates_tag_if_needed(self, experiment):
        """add_fov_tag auto-creates the tag if it doesn't exist."""
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        experiment.add_fov_tag(fov_id, "new_tag")
        assert "new_tag" in experiment.get_tags()

    def test_multiple_fov_tags(self, experiment):
        experiment.add_condition("control")
        fov_id = experiment.add_fov("control")

        experiment.add_fov_tag(fov_id, "tag_a")
        experiment.add_fov_tag(fov_id, "tag_b")
        tags = experiment.get_fov_tags(fov_id)
        assert len(tags) == 2
        assert set(tags) == {"tag_a", "tag_b"}


# === Experiment Summary ===


class TestExperimentSummary:
    def test_empty_experiment(self, experiment):
        """Summary with no FOVs returns empty list."""
        summary = experiment.get_experiment_summary()
        assert summary == []

    def test_summary_with_data(self, experiment_with_data):
        """Summary returns per-FOV status info."""
        summary = experiment_with_data.get_experiment_summary()
        assert len(summary) == 1
        row = summary[0]
        assert row["cells"] == 10
        assert row["condition_name"] == "control"
        assert "GFP" in row["measured_channels"]
