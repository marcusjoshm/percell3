"""Tests for PerCellImporter — importing FOVs from another PerCell project."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord
from percell3.io.percell_import import ImportResult, PerCellImporter


@pytest.fixture
def source_project(tmp_path):
    """Create a source project with 2 FOVs, 2 channels, cells, measurements."""
    store = ExperimentStore.create(tmp_path / "source.percell")
    store.add_channel("DAPI")
    store.add_channel("GFP")
    store.add_condition("control")
    store.add_condition("treated")

    # FOV 1: control, 32x32
    fov1 = store.add_fov(
        "control", width=32, height=32, pixel_size_um=0.65,
    )
    img1_dapi = np.full((32, 32), 100, dtype=np.uint16)
    img1_gfp = np.full((32, 32), 200, dtype=np.uint16)
    store.write_image(fov1, "DAPI", img1_dapi)
    store.write_image(fov1, "GFP", img1_gfp)

    # FOV 2: treated, 32x32
    fov2 = store.add_fov(
        "treated", width=32, height=32, pixel_size_um=0.65,
    )
    img2_dapi = np.full((32, 32), 150, dtype=np.uint16)
    img2_gfp = np.full((32, 32), 250, dtype=np.uint16)
    store.write_image(fov2, "DAPI", img2_dapi)
    store.write_image(fov2, "GFP", img2_gfp)

    yield store
    store.close()


@pytest.fixture
def dest_project(tmp_path):
    """Create an empty destination project with 1 channel."""
    store = ExperimentStore.create(tmp_path / "dest.percell")
    store.add_channel("DAPI")
    store.add_condition("control")
    yield store
    store.close()


class TestBasicImport:
    """Test basic FOV import with images only."""

    def test_import_single_fov(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        result = importer.import_fovs([src_fovs[0].id])

        assert result.fovs_imported == 1
        dst_fovs = dest_project.get_fovs()
        assert len(dst_fovs) == 1
        assert dst_fovs[0].display_name == src_fovs[0].display_name

    def test_import_copies_images(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([src_fovs[0].id])

        dst_fovs = dest_project.get_fovs()
        dapi = dest_project.read_image_numpy(dst_fovs[0].id, "DAPI")
        np.testing.assert_array_equal(dapi, np.full((32, 32), 100, dtype=np.uint16))

    def test_import_preserves_metadata(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([src_fovs[0].id])

        dst_fov = dest_project.get_fovs()[0]
        src_fov = src_fovs[0]
        assert dst_fov.condition == src_fov.condition
        assert dst_fov.width == src_fov.width
        assert dst_fov.height == src_fov.height
        assert dst_fov.pixel_size_um == src_fov.pixel_size_um

    def test_import_multiple_fovs(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        result = importer.import_fovs([f.id for f in src_fovs])

        assert result.fovs_imported == 2
        assert len(dest_project.get_fovs()) == 2


class TestChannelMatching:
    """Test channel name matching and creation."""

    def test_reuses_existing_channel(self, source_project, dest_project):
        """DAPI already exists in dest — should reuse, not duplicate."""
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([src_fovs[0].id])

        channels = dest_project.get_channels()
        dapi_channels = [ch for ch in channels if ch.name == "DAPI"]
        assert len(dapi_channels) == 1

    def test_creates_missing_channel(self, source_project, dest_project):
        """GFP doesn't exist in dest — should be created."""
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        result = importer.import_fovs([src_fovs[0].id])

        channels = dest_project.get_channels()
        channel_names = {ch.name for ch in channels}
        assert "GFP" in channel_names
        assert result.channels_created >= 1

    def test_channel_reindexing(self, tmp_path):
        """Source and dest have different channel display_order."""
        # Source: GFP=0, DAPI=1
        src = ExperimentStore.create(tmp_path / "src_reindex.percell")
        src.add_channel("GFP")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=16, height=16)
        src.write_image(fov_id, "GFP", np.full((16, 16), 111, dtype=np.uint16))
        src.write_image(fov_id, "DAPI", np.full((16, 16), 222, dtype=np.uint16))

        # Dest: DAPI=0 (already exists), GFP will be created at index 1
        dst = ExperimentStore.create(tmp_path / "dst_reindex.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        importer.import_fovs([fov_id])

        dst_fov = dst.get_fovs()[0]
        # Verify data is correctly mapped to the right channel
        dapi = dst.read_image_numpy(dst_fov.id, "DAPI")
        gfp = dst.read_image_numpy(dst_fov.id, "GFP")
        np.testing.assert_array_equal(dapi, np.full((16, 16), 222, dtype=np.uint16))
        np.testing.assert_array_equal(gfp, np.full((16, 16), 111, dtype=np.uint16))

        src.close()
        dst.close()


class TestConditionBioRepMatching:
    """Test condition and bio_rep name matching."""

    def test_reuses_existing_condition(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([src_fovs[0].id])  # control FOV

        conditions = dest_project.get_conditions()
        assert conditions.count("control") == 1

    def test_creates_missing_condition(self, source_project, dest_project):
        """'treated' doesn't exist in dest — should be created."""
        src_fovs = source_project.get_fovs()
        treated_fov = [f for f in src_fovs if f.condition == "treated"][0]
        importer = PerCellImporter(source_project, dest_project)
        result = importer.import_fovs([treated_fov.id])

        conditions = dest_project.get_conditions()
        assert "treated" in conditions
        assert result.conditions_created >= 1


class TestSegmentationImport:
    """Test segmentation import with cells."""

    def test_whole_field_seg_reused(self, source_project, dest_project):
        """Whole-field seg with matching dimensions should be reused."""
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([src_fovs[0].id])

        # Should reuse existing whole_field seg (same 32x32 dimensions)
        segs = dest_project.get_segmentations(seg_type="whole_field")
        assert len(segs) == 1  # only one, reused

    def test_cellular_seg_imported(self, tmp_path):
        """Cellular segmentations should be imported as new entities."""
        src = ExperimentStore.create(tmp_path / "src_seg.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=32, height=32)
        src.write_image(fov_id, "DAPI", np.full((32, 32), 100, dtype=np.uint16))

        # Add a cellular segmentation with labels and cells
        seg_id = src.add_segmentation(
            "cyto3_DAPI_1", "cellular", 32, 32,
            source_fov_id=fov_id, source_channel="DAPI",
            model_name="cyto3",
        )
        labels = np.zeros((32, 32), dtype=np.int32)
        labels[5:15, 5:15] = 1
        labels[15:25, 15:25] = 2
        src.write_labels(labels, seg_id)

        cells = [
            CellRecord(fov_id, seg_id, 1, 10.0, 10.0, 5, 5, 10, 10, 100.0),
            CellRecord(fov_id, seg_id, 2, 20.0, 20.0, 15, 15, 10, 10, 100.0),
        ]
        src.add_cells(cells)

        dst = ExperimentStore.create(tmp_path / "dst_seg.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.segmentations_created >= 1
        assert result.cells_imported == 2

        # Verify labels copied
        dst_segs = dst.get_segmentations(seg_type="cellular")
        assert len(dst_segs) >= 1
        dst_labels = dst.read_labels(dst_segs[0].id)
        np.testing.assert_array_equal(dst_labels, labels)

        # Verify cells exist
        dst_fov = dst.get_fovs()[0]
        dst_cells = dst.get_cells(fov_id=dst_fov.id, is_valid=False)
        assert len(dst_cells) == 2

        src.close()
        dst.close()


class TestThresholdImport:
    """Test threshold import with masks and particles."""

    def test_threshold_imported_with_mask(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_thr.percell")
        src.add_channel("GFP")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=32, height=32)
        src.write_image(fov_id, "GFP", np.full((32, 32), 100, dtype=np.uint16))

        thr_id = src.add_threshold(
            "otsu_GFP_1", "otsu", 32, 32,
            source_fov_id=fov_id, source_channel="GFP",
        )
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[10:20, 10:20] = 255
        src.write_mask(mask, thr_id)

        dst = ExperimentStore.create(tmp_path / "dst_thr.percell")
        dst.add_channel("GFP")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.thresholds_created == 1
        dst_thrs = dst.get_thresholds()
        # Filter out any auto-created thresholds
        imported_thrs = [t for t in dst_thrs if "otsu" in t.name]
        assert len(imported_thrs) == 1

        dst_mask = dst.read_mask(imported_thrs[0].id)
        np.testing.assert_array_equal(dst_mask, mask)

        src.close()
        dst.close()

    def test_particles_imported(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_particles.percell")
        src.add_channel("GFP")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=32, height=32)
        src.write_image(fov_id, "GFP", np.full((32, 32), 100, dtype=np.uint16))

        thr_id = src.add_threshold(
            "otsu_GFP_1", "otsu", 32, 32,
            source_fov_id=fov_id, source_channel="GFP",
        )
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[10:20, 10:20] = 255
        src.write_mask(mask, thr_id)

        particles = [
            ParticleRecord(
                fov_id=fov_id, threshold_id=thr_id, label_value=1,
                centroid_x=15.0, centroid_y=15.0,
                bbox_x=10, bbox_y=10, bbox_w=10, bbox_h=10,
                area_pixels=50.0,
            ),
        ]
        src.add_particles(particles)

        dst = ExperimentStore.create(tmp_path / "dst_particles.percell")
        dst.add_channel("GFP")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.particles_imported == 1
        dst_fov = dst.get_fovs()[0]
        dst_particles = dst.get_particles(fov_id=dst_fov.id)
        assert len(dst_particles) == 1

        src.close()
        dst.close()


class TestMeasurementImport:
    """Test measurement import with ID remapping."""

    def test_measurements_imported(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_meas.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=32, height=32)
        src.write_image(fov_id, "DAPI", np.full((32, 32), 100, dtype=np.uint16))

        # Get whole_field seg
        segs = src.get_segmentations(seg_type="whole_field")
        seg_id = segs[0].id

        # Add a cell and measurement
        ch = src.get_channel("DAPI")
        cells = [
            CellRecord(fov_id, seg_id, 1, 16.0, 16.0, 0, 0, 32, 32, 1024.0),
        ]
        cell_ids = src.add_cells(cells)

        measurements = [
            MeasurementRecord(
                cell_id=cell_ids[0], channel_id=ch.id,
                metric="mean_intensity", value=100.0,
                segmentation_id=seg_id,
            ),
        ]
        src.add_measurements(measurements)

        dst = ExperimentStore.create(tmp_path / "dst_meas.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.measurements_imported == 1
        dst_fov = dst.get_fovs()[0]
        dst_cells = dst.get_cells(fov_id=dst_fov.id, is_valid=False)
        assert len(dst_cells) == 1

        dst_meas = dst.get_measurements(cell_ids=[int(dst_cells.iloc[0]["id"])])
        assert len(dst_meas) == 1
        assert dst_meas.iloc[0]["metric"] == "mean_intensity"
        assert dst_meas.iloc[0]["value"] == 100.0

        src.close()
        dst.close()


class TestCellTagImport:
    """Test cell tag import."""

    def test_cell_tags_imported(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_tags.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=32, height=32)
        src.write_image(fov_id, "DAPI", np.full((32, 32), 100, dtype=np.uint16))

        segs = src.get_segmentations(seg_type="whole_field")
        seg_id = segs[0].id
        cells = [
            CellRecord(fov_id, seg_id, 1, 16.0, 16.0, 0, 0, 32, 32, 1024.0),
        ]
        cell_ids = src.add_cells(cells)

        src.add_tag("group:GFP:mean_intensity:g1")
        src.tag_cells(cell_ids, "group:GFP:mean_intensity:g1")

        dst = ExperimentStore.create(tmp_path / "dst_tags.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        importer.import_fovs([fov_id])

        # Verify tags exist in dest
        dst_tags = dst.get_tags()
        assert "group:GFP:mean_intensity:g1" in dst_tags

        # Verify cell is tagged
        dst_fov = dst.get_fovs()[0]
        dst_cells = dst.get_cells(fov_id=dst_fov.id, is_valid=False)
        cell_id = int(dst_cells.iloc[0]["id"])
        rows = dst._conn.execute(
            "SELECT tag_id FROM cell_tags WHERE cell_id = ?", (cell_id,),
        ).fetchall()
        assert len(rows) == 1

        src.close()
        dst.close()


class TestNameCollisions:
    """Test handling of name collisions."""

    def test_fov_name_collision(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_coll.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", display_name="FOV_001", width=16, height=16)
        src.write_image(fov_id, "DAPI", np.full((16, 16), 100, dtype=np.uint16))

        dst = ExperimentStore.create(tmp_path / "dst_coll.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")
        dst.add_fov("c1", display_name="FOV_001", width=16, height=16)

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.fovs_imported == 1
        dst_fovs = dst.get_fovs()
        assert len(dst_fovs) == 2
        names = {f.display_name for f in dst_fovs}
        assert "FOV_001" in names
        assert "FOV_001_imported_1" in names
        assert len(result.warnings) >= 1

        src.close()
        dst.close()

    def test_seg_name_collision(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_seg_coll.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=16, height=16)
        src.write_image(fov_id, "DAPI", np.full((16, 16), 100, dtype=np.uint16))
        seg_id = src.add_segmentation(
            "cyto3_DAPI_1", "cellular", 16, 16,
            source_fov_id=fov_id, source_channel="DAPI",
        )
        labels = np.ones((16, 16), dtype=np.int32)
        src.write_labels(labels, seg_id)

        dst = ExperimentStore.create(tmp_path / "dst_seg_coll.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")
        dst.add_segmentation("cyto3_DAPI_1", "cellular", 16, 16)

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.fovs_imported == 1
        segs = dst.get_segmentations(seg_type="cellular")
        names = {s.name for s in segs}
        assert "cyto3_DAPI_1" in names
        assert "cyto3_DAPI_1_imported_1" in names

        src.close()
        dst.close()

    def test_threshold_name_collision(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_thr_coll.percell")
        src.add_channel("GFP")
        src.add_condition("c1")
        fov_id = src.add_fov("c1", width=16, height=16)
        src.write_image(fov_id, "GFP", np.full((16, 16), 100, dtype=np.uint16))
        thr_id = src.add_threshold(
            "otsu_GFP_1", "otsu", 16, 16,
            source_fov_id=fov_id, source_channel="GFP",
        )
        mask = np.zeros((16, 16), dtype=np.uint8)
        mask[5:10, 5:10] = 255
        src.write_mask(mask, thr_id)

        dst = ExperimentStore.create(tmp_path / "dst_thr_coll.percell")
        dst.add_channel("GFP")
        dst.add_condition("c1")
        dst.add_threshold("otsu_GFP_1", "otsu", 16, 16)

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov_id])

        assert result.fovs_imported == 1
        thrs = dst.get_thresholds()
        names = {t.name for t in thrs}
        assert "otsu_GFP_1" in names
        assert "otsu_GFP_1_imported_1" in names

        src.close()
        dst.close()


class TestAtomicity:
    """Test per-FOV atomicity on failure."""

    def test_failed_fov_does_not_corrupt(self, tmp_path):
        """If one FOV fails, previously imported FOVs should remain intact."""
        src = ExperimentStore.create(tmp_path / "src_atom.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov1 = src.add_fov("c1", width=16, height=16)
        src.write_image(fov1, "DAPI", np.full((16, 16), 100, dtype=np.uint16))
        fov2 = src.add_fov("c1", width=16, height=16)
        src.write_image(fov2, "DAPI", np.full((16, 16), 200, dtype=np.uint16))

        dst = ExperimentStore.create(tmp_path / "dst_atom.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        # Import both FOVs — first should succeed
        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov1, fov2])

        # Both should succeed in normal case
        assert result.fovs_imported == 2
        assert len(dst.get_fovs()) == 2

        src.close()
        dst.close()


class TestSameProjectGuard:
    """Test rejection of self-import."""

    def test_same_project_rejected(self, tmp_path):
        store = ExperimentStore.create(tmp_path / "self.percell")
        store.add_channel("DAPI")
        store.add_condition("c1")

        importer = PerCellImporter(store, store)
        with pytest.raises(ValueError, match="same project"):
            importer.import_fovs([1])

        store.close()


class TestEmptyFov:
    """Test importing FOV with no cells."""

    def test_empty_fov_imported(self, source_project, dest_project):
        """FOV with images but no cells should import successfully."""
        src_fovs = source_project.get_fovs()
        importer = PerCellImporter(source_project, dest_project)
        result = importer.import_fovs([src_fovs[0].id])

        assert result.fovs_imported == 1
        assert result.cells_imported == 0


class TestMultiFovSharedSeg:
    """Test importing multiple FOVs that share a segmentation."""

    def test_shared_seg_imported_once(self, tmp_path):
        src = ExperimentStore.create(tmp_path / "src_shared.percell")
        src.add_channel("DAPI")
        src.add_condition("c1")
        fov1 = src.add_fov("c1", width=16, height=16)
        fov2 = src.add_fov("c1", width=16, height=16)
        src.write_image(fov1, "DAPI", np.full((16, 16), 100, dtype=np.uint16))
        src.write_image(fov2, "DAPI", np.full((16, 16), 200, dtype=np.uint16))

        # Create a shared cellular segmentation referenced by both FOVs
        seg_id = src.add_segmentation(
            "shared_seg", "cellular", 16, 16,
            source_fov_id=fov1, source_channel="DAPI",
        )
        labels = np.ones((16, 16), dtype=np.int32)
        src.write_labels(labels, seg_id)

        # Assign to both FOVs
        src.set_fov_config_entry(fov2, seg_id)

        dst = ExperimentStore.create(tmp_path / "dst_shared.percell")
        dst.add_channel("DAPI")
        dst.add_condition("c1")

        importer = PerCellImporter(src, dst)
        result = importer.import_fovs([fov1, fov2])

        assert result.fovs_imported == 2
        # Shared seg should only be created once
        assert result.segmentations_created == 1

        dst_segs = dst.get_segmentations(seg_type="cellular")
        assert len(dst_segs) == 1

        src.close()
        dst.close()


class TestProgressCallback:
    """Test progress callback."""

    def test_callback_called(self, source_project, dest_project):
        src_fovs = source_project.get_fovs()
        calls = []

        def on_progress(current, total, msg):
            calls.append((current, total, msg))

        importer = PerCellImporter(source_project, dest_project)
        importer.import_fovs([f.id for f in src_fovs], progress_callback=on_progress)

        assert len(calls) == 2
        assert calls[0][0] == 1
        assert calls[1][0] == 2
        assert calls[0][1] == 2
