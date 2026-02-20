"""Tests for CellGrouper — GMM-based cell grouping."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord
from percell3.measure.cell_grouper import (
    MIN_CELLS_FOR_GMM,
    CellGrouper,
    GroupingResult,
)


@pytest.fixture
def grouper_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with cells and measurements suitable for grouping."""
    store = ExperimentStore.create(tmp_path / "grouper.percell")
    store.add_channel("DAPI", role="nucleus")
    store.add_channel("GFP", role="signal")
    store.add_condition("control")
    fov_id = store.add_fov("fov_1", "control", width=256, height=256)
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

    # 30 cells with bimodal mean_intensity: 15 low (~50), 15 high (~200)
    rng = np.random.default_rng(42)
    cells = []
    for i in range(1, 31):
        cells.append(CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=50.0 + i * 5, centroid_y=50.0 + i * 5,
            bbox_x=40 + i * 5, bbox_y=40 + i * 5, bbox_w=20, bbox_h=20,
            area_pixels=300.0 + rng.normal(0, 10),
        ))
    cell_ids = store.add_cells(cells)

    gfp = store.get_channel("GFP")
    measurements = []
    for j, cid in enumerate(cell_ids):
        if j < 15:
            val = rng.normal(50, 5)
        else:
            val = rng.normal(200, 10)
        measurements.append(MeasurementRecord(
            cell_id=cid, channel_id=gfp.id,
            metric="mean_intensity", value=float(val),
        ))
    store.add_measurements(measurements)

    yield store
    store.close()


@pytest.fixture
def few_cells_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with fewer than MIN_CELLS_FOR_GMM cells."""
    store = ExperimentStore.create(tmp_path / "few.percell")
    store.add_channel("DAPI")
    store.add_channel("GFP")
    store.add_condition("control")
    fov_id = store.add_fov("fov_1", "control", width=64, height=64)
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")

    cells = [
        CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=i,
            centroid_x=10.0 * i, centroid_y=10.0 * i,
            bbox_x=5 * i, bbox_y=5 * i, bbox_w=10, bbox_h=10,
            area_pixels=100.0,
        )
        for i in range(1, 6)  # 5 cells < MIN_CELLS_FOR_GMM
    ]
    cell_ids = store.add_cells(cells)

    gfp = store.get_channel("GFP")
    measurements = [
        MeasurementRecord(
            cell_id=cid, channel_id=gfp.id,
            metric="mean_intensity", value=42.0 + cid,
        )
        for cid in cell_ids
    ]
    store.add_measurements(measurements)

    yield store
    store.close()


class TestCellGrouper:
    def test_bimodal_finds_two_groups(self, grouper_experiment: ExperimentStore):
        """With a clearly bimodal distribution, GMM should find 2 groups."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        assert isinstance(result, GroupingResult)
        assert result.n_groups == 2
        # Groups should be ordered by ascending mean
        assert result.group_means[0] < result.group_means[1]
        assert len(result.tag_names) == 2
        assert result.tag_names[0] == "group:GFP:mean_intensity:g1"
        assert result.tag_names[1] == "group:GFP:mean_intensity:g2"

    def test_cells_tagged(self, grouper_experiment: ExperimentStore):
        """Cells should be tagged with their group assignment."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        # Check that cells are tagged
        for tag_name in result.tag_names:
            tagged = grouper_experiment.get_cells(
                condition="control", tags=[tag_name],
            )
            assert len(tagged) > 0

    def test_all_cells_assigned(self, grouper_experiment: ExperimentStore):
        """Every cell should be in exactly one group."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        total_tagged = 0
        for tag_name in result.tag_names:
            tagged = grouper_experiment.get_cells(
                condition="control", tags=[tag_name],
            )
            total_tagged += len(tagged)
        total_cells = len(grouper_experiment.get_cells(condition="control"))
        assert total_tagged == total_cells

    def test_few_cells_single_group(self, few_cells_experiment: ExperimentStore):
        """With fewer than MIN_CELLS_FOR_GMM, should use single group."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            few_cells_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        assert result.n_groups == 1
        assert result.bic_scores == []
        assert result.tag_names == ["group:GFP:mean_intensity:g1"]

    def test_area_metric_from_cells_table(self, grouper_experiment: ExperimentStore):
        """area_pixels metric should work without explicit measurements."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="area_pixels",
        )
        assert result.n_groups >= 1
        assert len(result.cell_ids) == 30

    def test_no_cells_raises(self, tmp_path: Path):
        """Empty FOV should raise ValueError."""
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("GFP")
        store.add_condition("control")
        store.add_fov("fov_1", "control", width=64, height=64)

        grouper = CellGrouper()
        with pytest.raises(ValueError, match="No cells found"):
            grouper.group_cells(
                store, fov="fov_1", condition="control",
                channel="GFP", metric="mean_intensity",
            )
        store.close()

    def test_missing_measurements_raises(self, tmp_path: Path):
        """If grouping metric hasn't been measured, should raise ValueError."""
        store = ExperimentStore.create(tmp_path / "nomeas.percell")
        store.add_channel("DAPI")
        store.add_channel("GFP")
        store.add_condition("control")
        fov_id = store.add_fov("fov_1", "control", width=64, height=64)
        seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")
        store.add_cells([CellRecord(
            fov_id=fov_id, segmentation_id=seg_id, label_value=1,
            centroid_x=10, centroid_y=10,
            bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10,
            area_pixels=100,
        )])

        grouper = CellGrouper()
        with pytest.raises(ValueError, match="No measurements"):
            grouper.group_cells(
                store, fov="fov_1", condition="control",
                channel="GFP", metric="mean_intensity",
            )
        store.close()

    def test_regrouping_cleans_old_tags(self, grouper_experiment: ExperimentStore):
        """Re-grouping should remove old group tags before assigning new ones."""
        grouper = CellGrouper()
        # First grouping
        result1 = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        # Second grouping (same params)
        result2 = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        # All cells should still be in exactly one group
        total_tagged = 0
        for tag_name in result2.tag_names:
            tagged = grouper_experiment.get_cells(
                condition="control", tags=[tag_name],
            )
            total_tagged += len(tagged)
        total_cells = len(grouper_experiment.get_cells(condition="control"))
        assert total_tagged == total_cells

    def test_bic_scores_populated(self, grouper_experiment: ExperimentStore):
        """BIC scores should be populated for GMM fitting."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        assert len(result.bic_scores) > 0

    def test_group_labels_match_cell_ids(self, grouper_experiment: ExperimentStore):
        """group_labels array length should match cell_ids length."""
        grouper = CellGrouper()
        result = grouper.group_cells(
            grouper_experiment, fov="fov_1", condition="control",
            channel="GFP", metric="mean_intensity",
        )
        assert len(result.group_labels) == len(result.cell_ids)
        assert set(result.group_labels) == set(range(result.n_groups))
