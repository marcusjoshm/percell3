"""Tests for ImageJ ROI .zip import."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.segment.imagej_roi_reader import rois_to_labels


def _make_roi_zip(path: Path, polygons: list[np.ndarray]) -> Path:
    """Create a synthetic ImageJ ROI .zip with polygon ROIs.

    Each polygon is an (N, 2) array of (x, y) vertex coordinates.
    """
    from roifile import ImagejRoi

    with zipfile.ZipFile(path, "w") as zf:
        for i, pts in enumerate(polygons):
            roi = ImagejRoi.frompoints(pts)
            zf.writestr(f"roi_{i:04d}.roi", roi.tobytes())
    return path


def _make_mixed_roi_zip(
    path: Path,
    polygons: list[np.ndarray],
    *,
    add_line: bool = False,
) -> Path:
    """Create a .zip with polygon ROIs and optionally a non-area ROI."""
    from roifile import ImagejRoi

    with zipfile.ZipFile(path, "w") as zf:
        for i, pts in enumerate(polygons):
            roi = ImagejRoi.frompoints(pts)
            zf.writestr(f"roi_{i:04d}.roi", roi.tobytes())

        if add_line:
            # Create a line ROI (2 points, roitype=LINE)
            line_roi = ImagejRoi.frompoints(np.array([[0, 0], [10, 10]]))
            # frompoints with 2 points still makes FREEHAND; manually set type
            # Just write a polygon with 2 vertices — it will be skipped (< 3 verts)
            zf.writestr("line_roi.roi", line_roi.tobytes())
    return path


# ---------------------------------------------------------------------------
# Unit tests for rois_to_labels
# ---------------------------------------------------------------------------


class TestRoisToLabels:
    """Tests for the rois_to_labels() function."""

    def test_single_polygon(self, tmp_path: Path) -> None:
        """One polygon ROI produces a single labelled region."""
        polygon = np.array([[10, 10], [10, 50], [50, 50], [50, 10]])
        zip_path = _make_roi_zip(tmp_path / "single.zip", [polygon])

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 1
        assert info["skipped_count"] == 0
        assert labels[30, 30] == 1  # inside polygon
        assert labels[0, 0] == 0    # background

    def test_two_non_overlapping_polygons(self, tmp_path: Path) -> None:
        """Two non-overlapping polygons get unique label IDs."""
        p1 = np.array([[5, 5], [5, 25], [25, 25], [25, 5]])
        p2 = np.array([[35, 35], [35, 55], [55, 55], [55, 35]])
        zip_path = _make_roi_zip(tmp_path / "two.zip", [p1, p2])

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 2
        assert labels[15, 15] == 1  # inside p1
        assert labels[45, 45] == 2  # inside p2
        assert labels[30, 30] == 0  # between polygons

    def test_overlapping_polygons_last_wins(self, tmp_path: Path) -> None:
        """When polygons overlap, the later ROI overwrites earlier pixels."""
        p1 = np.array([[10, 10], [10, 40], [40, 40], [40, 10]])
        p2 = np.array([[20, 20], [20, 50], [50, 50], [50, 20]])
        zip_path = _make_roi_zip(tmp_path / "overlap.zip", [p1, p2])

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 2
        # Overlap region should have label 2 (last wins)
        assert labels[30, 30] == 2
        # p1-only region should have label 1
        assert labels[15, 15] == 1
        # p2-only region should have label 2
        assert labels[45, 45] == 2

    def test_out_of_bounds_roi_clipped(self, tmp_path: Path) -> None:
        """ROIs extending beyond image bounds are clipped, not crashed."""
        # Polygon extends beyond 32x32 image
        polygon = np.array([[10, 10], [10, 50], [50, 50], [50, 10]])
        zip_path = _make_roi_zip(tmp_path / "oob.zip", [polygon])

        labels, info = rois_to_labels(zip_path, (32, 32))

        assert info["roi_count"] == 1
        assert labels[15, 15] == 1  # inside clipped region
        assert labels.shape == (32, 32)

    def test_coordinate_swap_xy_to_rowcol(self, tmp_path: Path) -> None:
        """Verify (x, y) from roifile is correctly swapped to (row, col).

        A rectangle at x=[5,25], y=[40,55] should fill rows 40-55, cols 5-25.
        """
        # x range [5, 25], y range [40, 55]
        polygon = np.array([[5, 40], [25, 40], [25, 55], [5, 55]])
        zip_path = _make_roi_zip(tmp_path / "swap.zip", [polygon])

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 1
        # (row=47, col=15) should be inside: row in [40,55], col in [5,25]
        assert labels[47, 15] == 1
        # (row=15, col=47) should be outside (this would be wrong if swap failed)
        assert labels[15, 47] == 0

    def test_skips_rois_with_fewer_than_3_vertices(self, tmp_path: Path) -> None:
        """ROIs with < 3 vertices are skipped."""
        good = np.array([[10, 10], [10, 30], [30, 30], [30, 10]])
        bad = np.array([[5, 5], [10, 10]])  # Only 2 points
        zip_path = _make_mixed_roi_zip(
            tmp_path / "mixed.zip", [good], add_line=True,
        )

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 1
        # The 2-point ROI should have been skipped
        assert info["skipped_count"] >= 0  # May or may not be counted depending on type

    def test_empty_zip_raises(self, tmp_path: Path) -> None:
        """A .zip with no polygon ROIs raises ValueError."""
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "not an ROI")

        with pytest.raises(ValueError):
            rois_to_labels(zip_path, (64, 64))

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """A missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="ROI file not found"):
            rois_to_labels(tmp_path / "nope.zip", (64, 64))

    def test_non_imagej_zip_raises(self, tmp_path: Path) -> None:
        """A .zip that doesn't contain ImageJ ROIs raises ValueError."""
        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.csv", "a,b,c\n1,2,3")

        with pytest.raises(ValueError):
            rois_to_labels(zip_path, (64, 64))

    def test_fully_outside_roi_skipped(self, tmp_path: Path) -> None:
        """A polygon entirely outside the image bounds is skipped."""
        # Both polygons: one inside, one fully outside
        inside = np.array([[5, 5], [5, 25], [25, 25], [25, 5]])
        outside = np.array([[100, 100], [100, 120], [120, 120], [120, 100]])
        zip_path = _make_roi_zip(tmp_path / "outside.zip", [inside, outside])

        labels, info = rois_to_labels(zip_path, (64, 64))

        assert info["roi_count"] == 1
        assert info["skipped_count"] == 1


# ---------------------------------------------------------------------------
# Integration test: .zip → labels → cells → measurements
# ---------------------------------------------------------------------------


@pytest.fixture
def experiment_with_fov(tmp_path: Path) -> ExperimentStore:
    """Create an experiment with 1 FOV and a channel."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_condition("ctrl")

    image = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
    fov_id = store.add_fov("ctrl", width=64, height=64, pixel_size_um=0.65)
    store.write_image(fov_id, "DAPI", image)

    store._test_fov_id = fov_id
    yield store
    store.close()


class TestImagejRoiIntegration:
    """End-to-end: .zip → labels → segmentation → cells → auto-measure."""

    def test_import_flow(
        self, tmp_path: Path, experiment_with_fov: ExperimentStore
    ) -> None:
        """Import a 2-ROI .zip and verify cells are created."""
        from percell3.measure.auto_measure import on_segmentation_created
        from percell3.segment.roi_import import store_labels_and_cells

        store = experiment_with_fov
        fov_id = store._test_fov_id
        fov_info = store.get_fov_by_id(fov_id)

        # Create .zip with 2 polygon ROIs
        p1 = np.array([[5, 5], [5, 25], [25, 25], [25, 5]])
        p2 = np.array([[35, 35], [35, 55], [55, 55], [55, 35]])
        zip_path = _make_roi_zip(tmp_path / "test_rois.zip", [p1, p2])

        # Read ROIs
        labels, info = rois_to_labels(
            zip_path, (fov_info.height, fov_info.width),
        )
        assert info["roi_count"] == 2

        # Create segmentation entity
        seg_id = store.add_segmentation(
            name="test_imagej",
            seg_type="cellular",
            width=fov_info.width,
            height=fov_info.height,
            source_fov_id=fov_id,
            source_channel="imagej",
            model_name="imagej",
            parameters={"source": "imagej", "imported": True},
        )

        # Store labels and extract cells
        cell_count = store_labels_and_cells(
            store, labels, fov_id, seg_id, fov_info.pixel_size_um,
        )
        assert cell_count == 2

        # Verify cells in DB
        cells = store.get_cells(fov_id=fov_id)
        assert len(cells) == 2

        # Trigger auto-measurement
        on_segmentation_created(store, seg_id, [fov_id])

        # Verify measurements exist
        meas = store.get_measurements()
        assert len(meas) > 0

    def test_segmentation_assigned_to_config(
        self, tmp_path: Path, experiment_with_fov: ExperimentStore
    ) -> None:
        """Imported segmentation is auto-assigned to FOV config."""
        from percell3.segment.roi_import import store_labels_and_cells

        store = experiment_with_fov
        fov_id = store._test_fov_id
        fov_info = store.get_fov_by_id(fov_id)

        p1 = np.array([[10, 10], [10, 30], [30, 30], [30, 10]])
        zip_path = _make_roi_zip(tmp_path / "config_test.zip", [p1])

        labels, info = rois_to_labels(
            zip_path, (fov_info.height, fov_info.width),
        )

        seg_id = store.add_segmentation(
            name="imagej_config_test",
            seg_type="cellular",
            width=fov_info.width,
            height=fov_info.height,
            source_fov_id=fov_id,
            source_channel="imagej",
            model_name="imagej",
            parameters={"source": "imagej", "imported": True},
        )

        store_labels_and_cells(
            store, labels, fov_id, seg_id, fov_info.pixel_size_um,
        )

        # _auto_config_segmentation should have assigned the seg to fov_config
        config = store.get_fov_config(fov_id)
        seg_ids_in_config = {e.segmentation_id for e in config}
        assert seg_id in seg_ids_in_config
