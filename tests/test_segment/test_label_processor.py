"""Tests for LabelProcessor cell property extraction."""

from __future__ import annotations

import math

import numpy as np
import pytest
from skimage.draw import disk

from percell3.segment.label_processor import LabelProcessor


@pytest.fixture
def processor() -> LabelProcessor:
    return LabelProcessor()


class TestExtractCells:
    """Tests for LabelProcessor.extract_cells()."""

    def test_known_square_area(self, processor: LabelProcessor) -> None:
        """30x30 square should have area=900."""
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 50:80] = 1  # 30x30 = 900 pixels
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert len(cells) == 1
        assert cells[0].area_pixels == 900.0
        assert cells[0].label_value == 1

    def test_known_square_bbox(self, processor: LabelProcessor) -> None:
        """Bbox for labels[50:80, 50:80] should be x=50, y=50, w=30, h=30."""
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 50:80] = 1
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert cells[0].bbox_x == 50  # min_col
        assert cells[0].bbox_y == 50  # min_row
        assert cells[0].bbox_w == 30
        assert cells[0].bbox_h == 30

    def test_centroid_coordinate_swap(self, processor: LabelProcessor) -> None:
        """Centroid for labels[50:80, 100:130] should be x~115, y~65.

        regionprops returns (row, col) = (y, x). We must swap to (x, y).
        """
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 100:130] = 1  # rows 50-79, cols 100-129
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        # centroid_x should be col average = (100+129)/2 = 114.5
        assert cells[0].centroid_x == pytest.approx(114.5, abs=0.5)
        # centroid_y should be row average = (50+79)/2 = 64.5
        assert cells[0].centroid_y == pytest.approx(64.5, abs=0.5)

    def test_two_objects(self, processor: LabelProcessor) -> None:
        """Two labeled objects should return 2 CellRecords."""
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 50:80] = 1  # 30x30 = 900 pixels
        labels[150:200, 150:200] = 2  # 50x50 = 2500 pixels
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert len(cells) == 2
        assert cells[0].label_value == 1
        assert cells[0].area_pixels == 900.0
        assert cells[1].label_value == 2
        assert cells[1].area_pixels == 2500.0

    def test_with_pixel_size(self, processor: LabelProcessor) -> None:
        """area_um2 should be area_pixels * pixel_size^2."""
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 50:80] = 1  # 900 pixels
        cells = processor.extract_cells(
            labels, fov_id=1, segmentation_id=1, pixel_size_um=0.65
        )
        expected_um2 = 900 * 0.65**2
        assert cells[0].area_um2 == pytest.approx(expected_um2, rel=0.01)

    def test_without_pixel_size(self, processor: LabelProcessor) -> None:
        """area_um2 should be None when pixel_size_um is not provided."""
        labels = np.zeros((256, 256), dtype=np.int32)
        labels[50:80, 50:80] = 1
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert cells[0].area_um2 is None

    def test_empty_label_image(self, processor: LabelProcessor) -> None:
        """All-zero label image should return empty list."""
        labels = np.zeros((100, 100), dtype=np.int32)
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert cells == []

    def test_circle_circularity(self, processor: LabelProcessor) -> None:
        """A disk should have circularity close to 1.0."""
        labels = np.zeros((200, 200), dtype=np.int32)
        rr, cc = disk((100, 100), 40)
        labels[rr, cc] = 1
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert len(cells) == 1
        # Circularity of a discrete circle is approximately 1.0
        assert cells[0].circularity == pytest.approx(1.0, abs=0.15)

    def test_single_pixel_cell_circularity(self, processor: LabelProcessor) -> None:
        """Single-pixel cell has perimeter=0, so circularity should be 0.0."""
        labels = np.zeros((10, 10), dtype=np.int32)
        labels[5, 5] = 1
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert len(cells) == 1
        assert cells[0].area_pixels == 1.0
        assert cells[0].circularity == 0.0

    def test_non_contiguous_labels(self, processor: LabelProcessor) -> None:
        """Non-contiguous label IDs (1, 5) should be handled correctly."""
        labels = np.zeros((100, 100), dtype=np.int32)
        labels[10:20, 10:20] = 1
        labels[50:60, 50:60] = 5  # Skipping IDs 2-4
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert len(cells) == 2
        assert cells[0].label_value == 1
        assert cells[1].label_value == 5

    def test_fov_and_segmentation_ids(self, processor: LabelProcessor) -> None:
        """CellRecords should carry the provided fov_id and segmentation_id."""
        labels = np.zeros((100, 100), dtype=np.int32)
        labels[10:20, 10:20] = 1
        cells = processor.extract_cells(
            labels, fov_id=42, segmentation_id=7, pixel_size_um=1.0
        )
        assert cells[0].fov_id == 42
        assert cells[0].segmentation_id == 7

    def test_perimeter_is_positive_for_multi_pixel(
        self, processor: LabelProcessor
    ) -> None:
        """A multi-pixel region should have perimeter > 0."""
        labels = np.zeros((100, 100), dtype=np.int32)
        labels[10:30, 10:30] = 1  # 20x20 square
        cells = processor.extract_cells(labels, fov_id=1, segmentation_id=1)
        assert cells[0].perimeter is not None
        assert cells[0].perimeter > 0
