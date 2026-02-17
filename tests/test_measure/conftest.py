"""Shared fixtures for measurement module tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.core.models import CellRecord


@pytest.fixture
def measure_experiment(tmp_path: Path) -> ExperimentStore:
    """Create an experiment with 2 channels, 1 condition, 2 regions, labels, and cells.

    Layout:
        - Condition: "control"
        - Regions: "region_1" (64x64), "region_2" (64x64)
        - Channels: "DAPI" (segmentation), "GFP" (measurement)
        - Each region has a label image with 2 cells and corresponding cell records.

    Cell 1: label=1, bbox (10,10,20,20) — filled with value 100 in GFP
    Cell 2: label=2, bbox (40,40,20,20) — filled with value 200 in GFP
    """
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("DAPI", role="segmentation")
    store.add_channel("GFP")
    store.add_condition("control")

    seg_run_id = store.add_segmentation_run("DAPI", "mock", {"diameter": 30.0})

    for region_name in ("region_1", "region_2"):
        store.add_region(region_name, "control", width=64, height=64, pixel_size_um=0.65)

        # DAPI image — uniform background
        dapi = np.full((64, 64), 50, dtype=np.uint16)
        store.write_image(region_name, "control", "DAPI", dapi)

        # GFP image — cells have distinct intensities
        gfp = np.zeros((64, 64), dtype=np.uint16)
        gfp[10:30, 10:30] = 100  # Cell 1 region
        gfp[40:60, 40:60] = 200  # Cell 2 region
        store.write_image(region_name, "control", "GFP", gfp)

        # Label image — 2 cells
        labels = np.zeros((64, 64), dtype=np.int32)
        labels[10:30, 10:30] = 1
        labels[40:60, 40:60] = 2
        store.write_labels(region_name, "control", labels, seg_run_id)

        # Get region info for cell records
        regions = store.get_regions(condition="control")
        region_info = [r for r in regions if r.name == region_name][0]

        cells = [
            CellRecord(
                region_id=region_info.id,
                segmentation_id=seg_run_id,
                label_value=1,
                centroid_x=20.0, centroid_y=20.0,
                bbox_x=10, bbox_y=10, bbox_w=20, bbox_h=20,
                area_pixels=400.0,
            ),
            CellRecord(
                region_id=region_info.id,
                segmentation_id=seg_run_id,
                label_value=2,
                centroid_x=50.0, centroid_y=50.0,
                bbox_x=40, bbox_y=40, bbox_w=20, bbox_h=20,
                area_pixels=400.0,
            ),
        ]
        store.add_cells(cells)

    yield store
    store.close()


@pytest.fixture
def single_region_experiment(tmp_path: Path) -> ExperimentStore:
    """A minimal experiment with 1 region, 1 channel, 1 cell for focused tests."""
    store = ExperimentStore.create(tmp_path / "test.percell")
    store.add_channel("GFP")
    store.add_condition("control")
    store.add_region("region_1", "control", width=32, height=32)

    # Image: known pattern — cell area has value 10
    image = np.zeros((32, 32), dtype=np.uint16)
    image[5:15, 5:15] = 10
    store.write_image("region_1", "control", "GFP", image)

    # Labels
    seg_run_id = store.add_segmentation_run("GFP", "mock", {})
    labels = np.zeros((32, 32), dtype=np.int32)
    labels[5:15, 5:15] = 1
    store.write_labels("region_1", "control", labels, seg_run_id)

    # Cell
    regions = store.get_regions(condition="control")
    cell = CellRecord(
        region_id=regions[0].id,
        segmentation_id=seg_run_id,
        label_value=1,
        centroid_x=10.0, centroid_y=10.0,
        bbox_x=5, bbox_y=5, bbox_w=10, bbox_h=10,
        area_pixels=100.0,
    )
    store.add_cells([cell])

    yield store
    store.close()
