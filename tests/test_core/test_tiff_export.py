"""Tests for TIFF export of FOV layers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from percell3.core.experiment_store import ExperimentStore
from percell3.core.tiff_export import ExportResult, export_fov_as_tiff


# ---------------------------------------------------------------------------
# Fixture: experiment with 1 FOV, 2 channels, 1 cellular seg, 1 threshold
# ---------------------------------------------------------------------------


@pytest.fixture
def experiment(tmp_path: Path) -> ExperimentStore:
    """Create a minimal experiment for TIFF export tests."""
    exp_dir = tmp_path / "test.percell"
    store = ExperimentStore.create(exp_dir, name="TIFF Export Test")

    # Channels
    store.add_channel("DAPI", color="0000FF")
    store.add_channel("GFP", color="00FF00")

    # Condition + FOV
    store.add_condition("ctrl")
    fov_id = store.add_fov(
        "ctrl",
        display_name="FOV 1",
        width=64,
        height=64,
        pixel_size_um=0.325,
    )

    # Write channel images (uint16)
    rng = np.random.default_rng(42)
    dapi_img = rng.integers(0, 4095, (64, 64), dtype=np.uint16)
    gfp_img = rng.integers(0, 4095, (64, 64), dtype=np.uint16)
    store.write_image(fov_id, "DAPI", dapi_img)
    store.write_image(fov_id, "GFP", gfp_img)

    # Cellular segmentation with labels
    seg_id = store.add_segmentation(
        "cyto3_DAPI_1", "cellular", 64, 64, source_fov_id=fov_id,
    )
    labels = np.zeros((64, 64), dtype=np.int32)
    labels[10:30, 10:30] = 1
    labels[35:55, 35:55] = 2
    store.write_labels(labels, seg_id)

    # Threshold with mask
    thr_id = store.add_threshold(
        "thresh_GFP_1", "otsu", 64, 64,
        source_fov_id=fov_id, source_channel="GFP",
    )
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    store.write_mask(mask, thr_id)

    return store


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "export_out"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExportHappyPath:
    def test_export_channels_labels_mask(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Happy path: 2 channels + 1 labels + 1 mask = 4 files."""
        fov = experiment.get_fovs()[0]
        result = export_fov_as_tiff(experiment, fov.id, output_dir)

        assert len(result.written) == 4
        assert len(result.skipped) == 0

        names = sorted(p.name for p in result.written)
        assert "FOV_1_DAPI.tiff" in names
        assert "FOV_1_GFP.tiff" in names
        assert "FOV_1_cyto3_DAPI_1_labels.tiff" in names
        assert "FOV_1_thresh_GFP_1_mask.tiff" in names

    def test_dtype_preserved(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """uint16 channel images should stay uint16 in the TIFF."""
        fov = experiment.get_fovs()[0]
        export_fov_as_tiff(experiment, fov.id, output_dir)

        dapi_path = output_dir / "FOV_1_DAPI.tiff"
        data = tifffile.imread(str(dapi_path))
        assert data.dtype == np.uint16

    def test_pixel_size_metadata(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Exported TIFFs should contain pixel-size metadata."""
        fov = experiment.get_fovs()[0]
        export_fov_as_tiff(experiment, fov.id, output_dir)

        dapi_path = output_dir / "FOV_1_DAPI.tiff"
        with tifffile.TiffFile(str(dapi_path)) as tif:
            page = tif.pages[0]
            # ImageJ-format: resolution stored as X/Y resolution tags
            # Value should be close to 1/0.325 ≈ 3.077
            x_res = page.tags["XResolution"].value
            # tifffile returns resolution as a tuple (numerator, denominator)
            res_val = x_res[0] / x_res[1]
            expected = 1.0 / 0.325
            assert abs(res_val - expected) < 0.01


class TestFilenameSanitization:
    def test_spaces_and_parens_sanitized(self, tmp_path: Path) -> None:
        """FOV names with spaces/parens should produce clean filenames."""
        exp_dir = tmp_path / "sanitize.percell"
        store = ExperimentStore.create(exp_dir, name="Sanitize Test")
        store.add_channel("DAPI")
        store.add_condition("ctrl")
        fov_id = store.add_fov(
            "ctrl", display_name="FOV (1)", width=8, height=8,
        )
        img = np.zeros((8, 8), dtype=np.uint16)
        store.write_image(fov_id, "DAPI", img)

        out = tmp_path / "out"
        out.mkdir()
        result = export_fov_as_tiff(store, fov_id, out)

        assert len(result.written) == 1
        assert result.written[0].name == "FOV_1_DAPI.tiff"


class TestOverwrite:
    def test_overwrite_false_raises(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Should raise FileExistsError when overwrite=False and file exists."""
        fov = experiment.get_fovs()[0]
        # First export succeeds
        export_fov_as_tiff(experiment, fov.id, output_dir, overwrite=False)
        # Second export should fail
        with pytest.raises(FileExistsError):
            export_fov_as_tiff(experiment, fov.id, output_dir, overwrite=False)

    def test_overwrite_true_replaces(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Should replace files without error when overwrite=True."""
        fov = experiment.get_fovs()[0]
        result1 = export_fov_as_tiff(experiment, fov.id, output_dir, overwrite=True)
        result2 = export_fov_as_tiff(experiment, fov.id, output_dir, overwrite=True)
        assert len(result2.written) == len(result1.written)
        assert len(result2.skipped) == 0


class TestSkippedLayers:
    def test_missing_channel_skipped(self, tmp_path: Path) -> None:
        """Channel in DB but no zarr group for FOV → skipped, not fatal."""
        exp_dir = tmp_path / "missing_ch.percell"
        store = ExperimentStore.create(exp_dir, name="Missing Channel")
        store.add_channel("DAPI")
        store.add_condition("ctrl")
        # Create FOV without writing any images — zarr group doesn't exist
        fov_id = store.add_fov("ctrl", display_name="F1")

        out = tmp_path / "out"
        out.mkdir()
        result = export_fov_as_tiff(store, fov_id, out)

        assert len(result.written) == 0
        assert len(result.skipped) == 1
        assert "DAPI" in result.skipped[0]

    def test_no_config_channels_only(self, tmp_path: Path) -> None:
        """FOV with no fov_config entries → export channels only."""
        exp_dir = tmp_path / "no_config.percell"
        store = ExperimentStore.create(exp_dir, name="No Config")
        store.add_channel("DAPI")
        store.add_condition("ctrl")
        # add_fov with dimensions creates whole_field seg + config entry,
        # so use without dimensions to avoid that.
        fov_id = store.add_fov("ctrl", display_name="F1")

        # We need to write an image; for that the FOV needs to have an image group.
        # Without width/height, write_image still works (zarr creates the group).
        img = np.zeros((8, 8), dtype=np.uint16)
        store.write_image(fov_id, "DAPI", img)

        out = tmp_path / "out"
        out.mkdir()
        result = export_fov_as_tiff(store, fov_id, out)

        assert len(result.written) == 1
        assert result.written[0].name == "F1_DAPI.tiff"


class TestFilteringRules:
    def test_whole_field_seg_excluded(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Whole-field segmentations should NOT produce label TIFFs."""
        fov = experiment.get_fovs()[0]
        result = export_fov_as_tiff(experiment, fov.id, output_dir)

        label_files = [p for p in result.written if "_labels.tiff" in p.name]
        # Only the cellular seg, not the auto-created whole_field
        assert len(label_files) == 1
        assert "whole_field" not in label_files[0].name

    def test_threshold_foreign_fov_excluded(self, tmp_path: Path) -> None:
        """Threshold with source_fov_id != exported fov → not exported."""
        exp_dir = tmp_path / "foreign_thr.percell"
        store = ExperimentStore.create(exp_dir, name="Foreign Thr")
        store.add_channel("GFP")
        store.add_condition("ctrl")
        fov1_id = store.add_fov("ctrl", display_name="F1", width=8, height=8)
        fov2_id = store.add_fov("ctrl", display_name="F2", width=8, height=8)

        store.write_image(fov1_id, "GFP", np.zeros((8, 8), dtype=np.uint16))
        store.write_image(fov2_id, "GFP", np.zeros((8, 8), dtype=np.uint16))

        # Threshold belongs to fov2
        thr_id = store.add_threshold(
            "thresh_1", "otsu", 8, 8, source_fov_id=fov2_id,
        )
        mask = np.zeros((8, 8), dtype=np.uint8)
        store.write_mask(mask, thr_id)

        # Manually add config entry linking fov1 to fov2's threshold
        seg_id = store.get_fov_config(fov1_id)[0].segmentation_id
        store.set_fov_config_entry(fov1_id, seg_id, threshold_id=thr_id)

        out = tmp_path / "out"
        out.mkdir()
        result = export_fov_as_tiff(store, fov1_id, out)

        mask_files = [p for p in result.written if "_mask.tiff" in p.name]
        assert len(mask_files) == 0


class TestDeduplication:
    def test_same_seg_id_in_two_config_entries(
        self, experiment: ExperimentStore, output_dir: Path,
    ) -> None:
        """Same seg_id appearing in 2 config entries → only 1 labels file."""
        fov = experiment.get_fovs()[0]

        # The fixture already has 1 cellular seg in config.
        # Add a second config entry pointing to the same segmentation.
        config = experiment.get_fov_config(fov.id)
        cellular_entries = [
            e for e in config
            if experiment.get_segmentation(e.segmentation_id).seg_type == "cellular"
        ]
        assert len(cellular_entries) >= 1
        seg_id = cellular_entries[0].segmentation_id

        # Create a second threshold so we can add another config entry
        # with the same seg_id
        thr_id2 = experiment.add_threshold(
            "thresh_GFP_2", "manual", 64, 64,
            source_fov_id=fov.id, source_channel="GFP",
        )
        mask = np.zeros((64, 64), dtype=np.uint8)
        experiment.write_mask(mask, thr_id2)

        result = export_fov_as_tiff(experiment, fov.id, output_dir)

        label_files = [p for p in result.written if "_labels.tiff" in p.name]
        assert len(label_files) == 1
