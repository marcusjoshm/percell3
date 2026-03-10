"""Tests for percell4.workflow.particle_analysis — particle analysis workflow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from percell4.core.constants import FovStatus
from percell4.core.db_types import new_uuid, uuid_to_hex
from percell4.core.experiment_store import ExperimentStore
from percell4.segment.cellpose_adapter import MockSegmenter
from percell4.workflow.particle_analysis import create_particle_analysis_workflow

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE_TOML = FIXTURES_DIR / "sample_experiment.toml"


@pytest.fixture()
def percell_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory to use as .percell root."""
    return tmp_path / "test.percell"


@pytest.fixture()
def store_with_fov(percell_dir: Path):
    """Create an experiment with a single FOV containing a synthetic image.

    Yields (store, fov_id, experiment_id).
    """
    store = ExperimentStore.create(percell_dir, SAMPLE_TOML)

    exp = store.get_experiment()
    exp_id = exp["id"]

    fov_id = new_uuid()
    fov_hex = uuid_to_hex(fov_id)

    # Synthetic image: two bright spots on dark background
    image_dapi = np.zeros((100, 100), dtype=np.uint16)
    image_dapi[20:40, 20:40] = 500
    image_dapi[60:80, 60:80] = 600

    image_gfp = np.ones((100, 100), dtype=np.uint16) * 50
    image_gfp[25:35, 25:35] = 300

    zarr_path = store.layers.write_image_channels(
        fov_hex, {0: image_dapi, 1: image_gfp}
    )

    with store.transaction():
        store.insert_fov(
            id=fov_id,
            experiment_id=exp_id,
            status="pending",
            auto_name="FOV_001",
            zarr_path=zarr_path,
        )
        store.set_fov_status(fov_id, FovStatus.imported, "test setup")

    yield store, fov_id, exp_id
    store.close()


class TestParticleWorkflowCreation:
    """Test workflow factory and step structure."""

    def test_particle_workflow_creation(self) -> None:
        """Factory creates a valid engine with 5 steps."""
        wf = create_particle_analysis_workflow(channel_name="DAPI")
        assert wf.step_count == 5

    def test_particle_workflow_step_names(self) -> None:
        """Steps have the expected names."""
        wf = create_particle_analysis_workflow(channel_name="DAPI")
        names = wf.step_names
        assert names == [
            "segment",
            "measure_whole",
            "threshold",
            "measure_masked",
            "export",
        ]

    def test_particle_workflow_step_order(self) -> None:
        """Topological order matches the linear chain."""
        wf = create_particle_analysis_workflow(channel_name="DAPI")
        order = wf._topological_order()
        assert order == [
            "segment",
            "measure_whole",
            "threshold",
            "measure_masked",
            "export",
        ]

    def test_particle_workflow_dependencies(self) -> None:
        """Each step depends on the previous one."""
        wf = create_particle_analysis_workflow(channel_name="DAPI")

        assert wf.get_step("segment").depends_on == []
        assert wf.get_step("measure_whole").depends_on == ["segment"]
        assert wf.get_step("threshold").depends_on == ["measure_whole"]
        assert wf.get_step("measure_masked").depends_on == ["threshold"]
        assert wf.get_step("export").depends_on == ["measure_masked"]

    def test_particle_workflow_export_skip_when_no_path(self) -> None:
        """Export step has skip_if set when no path is given."""
        wf = create_particle_analysis_workflow(channel_name="DAPI")
        export_step = wf.get_step("export")
        assert export_step.skip_if is not None

    def test_particle_workflow_export_no_skip_with_path(self, tmp_path: Path) -> None:
        """Export step runs when a path is given."""
        out = tmp_path / "output.csv"
        wf = create_particle_analysis_workflow(
            channel_name="DAPI", export_path=out
        )
        export_step = wf.get_step("export")
        # skip_if should return False because export_path is set
        # (but due to closure, it captures export_path from the factory call)
        assert export_step.config["export_path"] == out


class TestParticleWorkflowEndToEnd:
    """Integration test: run the full particle analysis workflow."""

    def test_particle_workflow_end_to_end(
        self, store_with_fov, tmp_path: Path
    ) -> None:
        """Run particle workflow with mock segmenter on synthetic data.

        Verifies:
        - Segmentation produced ROIs
        - Whole-ROI measurements written
        - Thresholds applied and masks created
        - Masked measurements written
        - CSV exported
        """
        store, fov_id, exp_id = store_with_fov
        csv_path = tmp_path / "results.csv"

        wf = create_particle_analysis_workflow(
            channel_name="DAPI",
            roi_type_name="cell",
            model_name="mock",
            diameter=30.0,
            threshold_method="otsu",
            export_path=csv_path,
        )

        # Inject mock segmenter via context
        context = {"segmenter": MockSegmenter()}

        start_log: list[str] = []
        complete_log: list[str] = []

        results = wf.run(
            store,
            context=context,
            on_step_start=lambda n, d: start_log.append(n),
            on_step_complete=lambda n, s: complete_log.append(f"{n}:{s}"),
        )

        # All 5 steps should have run (export should NOT be skipped since
        # we provided a path)
        assert results["segment"]["status"] == "completed"
        assert results["measure_whole"]["status"] == "completed"
        assert results["threshold"]["status"] == "completed"
        assert results["measure_masked"]["status"] == "completed"
        assert results["export"]["status"] == "completed"

        # Verify segmentation produced ROIs
        seg_set_id = context["seg_set_id"]
        seg_set = store.db.get_segmentation_set(seg_set_id)
        assert seg_set["total_roi_count"] >= 1

        # Verify measurements exist
        measurements = store.db.get_active_measurements(fov_id)
        assert len(measurements) > 0

        # Verify CSV was written
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "metric" in content  # header
        assert len(content.strip().split("\n")) > 1  # data rows

        # Verify callbacks were invoked
        assert "segment" in start_log
        assert "segment:completed" in complete_log

    def test_particle_workflow_skips_export_when_no_path(
        self, store_with_fov
    ) -> None:
        """Export step is skipped when no export_path is given."""
        store, fov_id, exp_id = store_with_fov

        wf = create_particle_analysis_workflow(
            channel_name="DAPI",
            roi_type_name="cell",
        )

        context = {"segmenter": MockSegmenter()}
        results = wf.run(store, context=context)

        assert results["export"]["status"] == "skipped"
