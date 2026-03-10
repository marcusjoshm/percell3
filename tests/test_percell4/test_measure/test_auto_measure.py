"""Tests for percell4.measure.auto_measure — MeasurementNeeded dispatch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import SCOPE_WHOLE_ROI
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.core.models import MeasurementNeeded
from percell4.measure.auto_measure import run_measurements

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


def _build_experiment(tmp_path: Path):
    """Build an experiment with 1 FOV, segmentation, and ROIs.

    Returns (store, fov_id, cell_type_id, channel_ids, pipeline_run_id).
    """
    percell_dir = tmp_path / "test.percell"
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.db.get_experiment()
    experiment_id = exp["id"]
    channels = store.db.get_channels(experiment_id)
    channel_ids = [ch["id"] for ch in channels]

    roi_types = store.db.get_roi_type_definitions(experiment_id)
    cell_type_id = [rt for rt in roi_types if rt["name"] == "cell"][0]["id"]

    pipeline_run_id = new_uuid()
    store.db.insert_pipeline_run(pipeline_run_id, "test_auto")

    # Create FOV
    fov_id = new_uuid()
    store.db.insert_fov(fov_id, experiment_id, status="imported")

    # Write synthetic image
    fov_hex = uuid_to_hex(fov_id)
    image = np.full((30, 30), 100.0, dtype=np.float32)
    store.layers.write_image_channels(fov_hex, {0: image, 1: image * 2})

    # Create segmentation set
    seg_set_id = new_uuid()
    store.db.insert_segmentation_set(
        seg_set_id, experiment_id, cell_type_id, "cellpose",
    )

    # Write labels: one ROI
    labels = np.zeros((30, 30), dtype=np.int32)
    labels[5:15, 5:15] = 1
    seg_hex = uuid_to_hex(seg_set_id)
    store.layers.write_labels(seg_hex, fov_hex, labels)

    # Assign segmentation
    store.db.assign_segmentation(
        [fov_id], seg_set_id, cell_type_id, pipeline_run_id,
    )

    # Create cell identity + ROI
    ci = new_uuid()
    store.db.insert_cell_identity(ci, fov_id, cell_type_id)
    store.db.insert_roi(
        new_uuid(), fov_id, cell_type_id, ci, None,
        label_id=1, bbox_y=5, bbox_x=5, bbox_h=10, bbox_w=10, area_px=100,
    )

    return store, fov_id, cell_type_id, channel_ids, pipeline_run_id


# ===================================================================
# Tests
# ===================================================================


class TestRunMeasurements:
    """run_measurements dispatches work items and writes measurements."""

    def test_whole_roi_measurements(self, tmp_path: Path) -> None:
        store, fov_id, cell_type_id, channel_ids, pr_id = (
            _build_experiment(tmp_path)
        )
        try:
            needed = [
                MeasurementNeeded(
                    fov_id=fov_id,
                    roi_type_id=cell_type_id,
                    channel_ids=channel_ids,
                    reason="new_assignment",
                ),
            ]

            total = run_measurements(store, needed)

            # 1 ROI x 2 channels x 7 metrics = 14
            assert total == 14

            # Verify in DB
            measurements = store.db.get_active_measurements(fov_id)
            assert len(measurements) == 14
        finally:
            store.close()

    def test_progress_callback(self, tmp_path: Path) -> None:
        store, fov_id, cell_type_id, channel_ids, pr_id = (
            _build_experiment(tmp_path)
        )
        try:
            needed = [
                MeasurementNeeded(
                    fov_id=fov_id,
                    roi_type_id=cell_type_id,
                    channel_ids=channel_ids,
                    reason="new_assignment",
                ),
            ]

            progress_calls: list[tuple[int, int]] = []

            def on_progress(current: int, total: int) -> None:
                progress_calls.append((current, total))

            run_measurements(store, needed, on_progress=on_progress)

            assert len(progress_calls) == 1
            assert progress_calls[0] == (1, 1)
        finally:
            store.close()

    def test_empty_needed_list(self, tmp_path: Path) -> None:
        percell_dir = tmp_path / "empty.percell"
        store = ExperimentStore.create(percell_dir, SAMPLE_TOML)
        try:
            total = run_measurements(store, [])
            assert total == 0
        finally:
            store.close()
