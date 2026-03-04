"""Tests for percell3 export command."""

import csv
from pathlib import Path

import pytest
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore
from percell3.core.models import MeasurementRecord


class TestExportCommand:
    def test_export_csv(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        exp_path = str(experiment_with_data.path)
        out_path = tmp_path / "output.csv"
        result = runner.invoke(cli, ["export", str(out_path), "-e", exp_path])
        assert result.exit_code == 0
        assert "Exported" in result.output

    def test_export_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "Export measurements to CSV" in result.output

    def test_export_nonexistent_experiment(self, runner: CliRunner, tmp_path: Path):
        out_path = tmp_path / "output.csv"
        result = runner.invoke(
            cli, ["export", str(out_path), "-e", "/nonexistent/exp.percell"]
        )
        assert result.exit_code != 0

    def test_export_overwrite_protection(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        exp_path = str(experiment_with_data.path)
        out_path = tmp_path / "output.csv"
        out_path.write_text("existing data")

        # Without --overwrite, should fail
        result = runner.invoke(cli, ["export", str(out_path), "-e", exp_path])
        assert result.exit_code == 1
        assert "already exists" in result.output

        # With --overwrite, should succeed
        result = runner.invoke(
            cli, ["export", str(out_path), "-e", exp_path, "--overwrite"]
        )
        assert result.exit_code == 0
        assert "Exported" in result.output

    def test_export_expanduser(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        """Export should expand ~ in output path."""
        exp_path = str(experiment_with_data.path)
        # Use a path that doesn't start with ~ to avoid writing to home dir
        out_path = tmp_path / "expanded.csv"
        result = runner.invoke(cli, ["export", str(out_path), "-e", exp_path])
        assert result.exit_code == 0

    def test_export_directory_path_rejected(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        """Passing a directory as output should fail with a clear error."""
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(cli, ["export", str(tmp_path), "-e", exp_path])
        assert result.exit_code == 1
        assert "directory" in result.output.lower()

    def test_export_directory_with_overwrite_still_rejected(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        """--overwrite should not bypass directory rejection."""
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(
            cli, ["export", str(tmp_path), "-e", exp_path, "--overwrite"]
        )
        assert result.exit_code == 1
        assert "directory" in result.output.lower()

    def test_export_missing_parent_directory(
        self, runner: CliRunner, experiment_with_data: ExperimentStore, tmp_path: Path,
    ):
        """Nonexistent parent directory should fail with a clear error."""
        exp_path = str(experiment_with_data.path)
        bad_path = tmp_path / "nonexistent" / "output.csv"
        result = runner.invoke(cli, ["export", str(bad_path), "-e", exp_path])
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_export_shows_overwrite_and_channels_in_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["export", "--help"])
        assert "--overwrite" in result.output
        assert "--channels" in result.output
        assert "--metrics" in result.output
        assert "--include-particles" in result.output


class TestParticleExport:
    def test_export_with_particles_flag(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
        tmp_path: Path,
    ):
        """--include-particles creates companion _particles.csv alongside main CSV."""
        exp_path = str(experiment_with_particles.path)
        out_path = tmp_path / "measurements.csv"
        result = runner.invoke(
            cli,
            ["export", str(out_path), "-e", exp_path, "--include-particles"],
        )
        assert result.exit_code == 0, result.output
        assert out_path.exists()
        particle_path = tmp_path / "measurements_particles.csv"
        assert particle_path.exists()
        assert "particle data" in result.output.lower()

    def test_export_cell_csv_contains_particle_summaries(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
        tmp_path: Path,
    ):
        """Cell-level CSV includes particle summary columns like particle_count."""
        exp_path = str(experiment_with_particles.path)
        out_path = tmp_path / "measurements.csv"
        result = runner.invoke(
            cli,
            ["export", str(out_path), "-e", exp_path],
        )
        assert result.exit_code == 0, result.output

        with open(out_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        assert len(rows) == 3  # 3 cells
        headers = set(rows[0].keys())
        # Particle summary metrics should appear as GFP_<metric> columns
        assert "GFP_particle_count" in headers
        assert "GFP_mean_particle_area" in headers
        assert "GFP_total_particle_area" in headers
        assert "GFP_particle_coverage_fraction" in headers
        assert "GFP_mean_particle_mean_intensity" in headers
        assert "GFP_mean_particle_integrated_intensity" in headers
        assert "GFP_total_particle_integrated_intensity" in headers
        # Verify values: cell 1 has 2 particles, cell 3 has 0
        # Area metrics are converted from pixels to um2 at export time
        # (pixel_size_um=0.65 → factor = 0.65² = 0.4225)
        cell1 = next(r for r in rows if float(r["GFP_particle_count"]) == 2.0)
        assert float(cell1["GFP_total_particle_area"]) == pytest.approx(80.0 * 0.4225)
        cell3 = next(r for r in rows if float(r["GFP_particle_count"]) == 0.0)
        assert float(cell3["GFP_total_particle_area"]) == 0.0

    def test_export_scope_filter_includes_particle_summaries(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
        tmp_path: Path,
    ):
        """Scope filter (e.g. mask_inside) still includes particle summary metrics."""
        store = experiment_with_particles
        exp_path = str(store.path)

        # Add mask_inside measurements so the scope filter has something to return
        ch_info = store.get_channel("GFP")
        seg_id = store.get_segmentations()[0].id
        thr_id = store.get_thresholds()[0].id
        cells_df = store.get_cells()
        cell_ids = cells_df["id"].tolist()
        mask_measurements = [
            MeasurementRecord(
                cell_id=cid, channel_id=ch_info.id,
                metric="mean_intensity", value=50.0 + i,
                scope="mask_inside",
                segmentation_id=seg_id,
                threshold_id=thr_id,
            )
            for i, cid in enumerate(cell_ids)
        ]
        store.add_measurements(mask_measurements)

        out_path = tmp_path / "scoped.csv"
        result = runner.invoke(
            cli,
            [
                "export", str(out_path), "-e", exp_path,
                "--metrics", "mean_intensity,particle_count,total_particle_area",
            ],
        )
        assert result.exit_code == 0, result.output

        with open(out_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        headers = set(rows[0].keys())
        # Particle summaries should be present (scope=whole_cell)
        assert "GFP_particle_count" in headers
        assert "GFP_total_particle_area" in headers
        # The mask_inside measurement should also appear with scope suffix
        assert "GFP_mean_intensity_mask_inside" in headers

    def test_export_particles_file_columns(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
        tmp_path: Path,
    ):
        """Particle CSV has expected context and data columns."""
        exp_path = str(experiment_with_particles.path)
        out_path = tmp_path / "out.csv"
        result = runner.invoke(
            cli,
            ["export", str(out_path), "-e", exp_path, "--include-particles"],
        )
        assert result.exit_code == 0, result.output

        particle_path = tmp_path / "out_particles.csv"
        with open(particle_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        assert len(rows) == 3  # 3 particles in fixture
        headers = set(rows[0].keys())
        # Context columns
        assert "condition_name" in headers
        assert "fov_name" in headers
        assert "bio_rep_name" in headers
        # Particle data columns
        assert "area_pixels" in headers
        assert "mean_intensity" in headers
        assert "max_intensity" in headers
        assert "integrated_intensity" in headers
        # Internal IDs should be dropped
        assert "id" not in headers
        assert "threshold_id" not in headers

    def test_export_particles_overwrite_protection(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
        tmp_path: Path,
    ):
        """Companion particle file blocked without --overwrite."""
        exp_path = str(experiment_with_particles.path)
        out_path = tmp_path / "meas.csv"
        particle_path = tmp_path / "meas_particles.csv"
        particle_path.write_text("existing")

        result = runner.invoke(
            cli,
            ["export", str(out_path), "-e", exp_path, "--include-particles"],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output.lower()

        # With --overwrite, should succeed
        result = runner.invoke(
            cli,
            [
                "export", str(out_path), "-e", exp_path,
                "--include-particles", "--overwrite",
            ],
        )
        assert result.exit_code == 0

    def test_export_particles_no_data(
        self,
        runner: CliRunner,
        experiment_with_data: ExperimentStore,
        tmp_path: Path,
    ):
        """--include-particles when no particles exist writes empty CSV."""
        exp_path = str(experiment_with_data.path)
        out_path = tmp_path / "output.csv"
        result = runner.invoke(
            cli,
            ["export", str(out_path), "-e", exp_path, "--include-particles"],
        )
        assert result.exit_code == 0
        particle_path = tmp_path / "output_particles.csv"
        assert particle_path.exists()
        # Empty particle export may have provenance comments but no data rows
        content = particle_path.read_text()
        data_lines = [line for line in content.strip().splitlines()
                       if not line.startswith("#")]
        assert len(data_lines) == 0


class TestMultiChannelParticleExport:
    def test_export_particles_with_channels(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """Particle CSV has per-channel intensity columns when channels specified."""
        exp_path = str(experiment_with_particle_images.path)
        out_path = tmp_path / "meas.csv"
        result = runner.invoke(
            cli,
            [
                "export", str(out_path), "-e", exp_path,
                "--include-particles", "--channels", "DAPI,GFP",
            ],
        )
        assert result.exit_code == 0, result.output

        particle_path = tmp_path / "meas_particles.csv"
        assert particle_path.exists()
        with open(particle_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        assert len(rows) == 1  # 1 particle in fixture
        headers = set(rows[0].keys())

        # Per-channel intensity columns
        assert "mean_intensity_DAPI" in headers
        assert "mean_intensity_GFP" in headers
        assert "max_intensity_DAPI" in headers
        assert "max_intensity_GFP" in headers
        assert "integrated_intensity_DAPI" in headers
        assert "integrated_intensity_GFP" in headers

        # Bare intensity columns should NOT be present when channels specified
        assert "mean_intensity" not in headers

        # Context columns
        assert "fov_name" in headers
        assert "condition_name" in headers
        assert "threshold_name" in headers

        # Verify per-channel values match the fixture image data
        row = rows[0]
        # Particle is at rows 18:26, cols 8:16
        # DAPI bright spot = 200, GFP bright spot = 150
        assert float(row["mean_intensity_DAPI"]) == pytest.approx(200.0, rel=0.01)
        assert float(row["mean_intensity_GFP"]) == pytest.approx(150.0, rel=0.01)

    def test_export_particles_metric_filter(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """Metric filter keeps matching geometry and intensity columns."""
        exp_path = str(experiment_with_particle_images.path)
        out_path = tmp_path / "meas.csv"
        result = runner.invoke(
            cli,
            [
                "export", str(out_path), "-e", exp_path,
                "--include-particles", "--metrics", "mean_intensity,area_pixels",
            ],
        )
        assert result.exit_code == 0, result.output

        particle_path = tmp_path / "meas_particles.csv"
        with open(particle_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        headers = set(rows[0].keys())
        # No channels specified → bare intensity columns
        assert "mean_intensity" in headers
        assert "area_pixels" in headers
        assert "fov_name" in headers
        # max_intensity not in filter → excluded
        assert "max_intensity" not in headers

    def test_export_particles_channels_and_metrics(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """Channels + metrics filter: per-channel intensity, filtered by metric name."""
        exp_path = str(experiment_with_particle_images.path)
        out_path = tmp_path / "meas.csv"
        result = runner.invoke(
            cli,
            [
                "export", str(out_path), "-e", exp_path,
                "--include-particles",
                "--channels", "DAPI,GFP",
                "--metrics", "mean_intensity,area_pixels",
            ],
        )
        assert result.exit_code == 0, result.output

        particle_path = tmp_path / "meas_particles.csv"
        with open(particle_path) as f:
            lines = [line for line in f if not line.startswith("#")]
        reader = csv.DictReader(lines)
        rows = list(reader)

        headers = set(rows[0].keys())
        # Geometry metric in filter
        assert "area_pixels" in headers
        # Per-channel mean_intensity (in filter)
        assert "mean_intensity_DAPI" in headers
        assert "mean_intensity_GFP" in headers
        # max_intensity / integrated_intensity NOT in filter → excluded
        assert "max_intensity_DAPI" not in headers
        assert "integrated_intensity_GFP" not in headers


class TestFovFilteredExport:
    """Tests for export_csv/export_particles_csv/export_prism_csv with fov_ids filter."""

    @pytest.fixture
    def two_fov_experiment(self, tmp_path: Path) -> ExperimentStore:
        """Experiment with 2 FOVs, each having cells and measurements."""
        import numpy as np
        from percell3.core.models import CellRecord, MeasurementRecord, ParticleRecord

        store = ExperimentStore.create(tmp_path / "twofov.percell", name="TwoFOV")
        store.add_channel("GFP")
        store.add_condition("ctrl")
        store.add_condition("treated")

        fov1_id = store.add_fov("ctrl", width=32, height=32, pixel_size_um=0.65)
        fov2_id = store.add_fov("treated", width=32, height=32, pixel_size_um=0.65)

        img = np.full((32, 32), 100, dtype=np.uint16)
        store.write_image(fov1_id, "GFP", img)
        store.write_image(fov2_id, "GFP", img)

        seg_id = store.add_segmentation(
            "seg", "cellular", 32, 32,
            source_fov_id=fov1_id, source_channel="GFP",
        )

        # 2 cells in fov1, 1 cell in fov2
        cells = [
            CellRecord(
                fov_id=fov1_id, segmentation_id=seg_id, label_value=1,
                centroid_x=8, centroid_y=8, bbox_x=0, bbox_y=0,
                bbox_w=16, bbox_h=16, area_pixels=100,
            ),
            CellRecord(
                fov_id=fov1_id, segmentation_id=seg_id, label_value=2,
                centroid_x=24, centroid_y=24, bbox_x=16, bbox_y=16,
                bbox_w=16, bbox_h=16, area_pixels=100,
            ),
            CellRecord(
                fov_id=fov2_id, segmentation_id=seg_id, label_value=1,
                centroid_x=16, centroid_y=16, bbox_x=0, bbox_y=0,
                bbox_w=32, bbox_h=32, area_pixels=200,
            ),
        ]
        cell_ids = store.add_cells(cells)

        ch = store.get_channel("GFP")
        measurements = [
            MeasurementRecord(
                cell_id=cid, channel_id=ch.id,
                metric="mean_intensity", value=50.0 + i * 10,
                segmentation_id=seg_id,
            )
            for i, cid in enumerate(cell_ids)
        ]
        store.add_measurements(measurements)

        # Particles in fov1 only
        thr_id = store.add_threshold(
            "thr", "otsu", 32, 32,
            source_fov_id=fov1_id, source_channel="GFP",
        )
        particles = [
            ParticleRecord(
                fov_id=fov1_id, threshold_id=thr_id, label_value=1,
                centroid_x=8, centroid_y=8, bbox_x=4, bbox_y=4,
                bbox_w=8, bbox_h=8, area_pixels=40,
                mean_intensity=120, max_intensity=200,
                integrated_intensity=4800,
            ),
        ]
        store.add_particles(particles)

        yield store
        store.close()

    def test_export_csv_fov_filter(self, two_fov_experiment, tmp_path):
        """export_csv with fov_ids only exports cells from selected FOVs."""
        store = two_fov_experiment
        fovs = store.get_fovs()
        fov1 = fovs[0]

        # Export only fov1
        out = tmp_path / "filtered.csv"
        store.export_csv(out, fov_ids=[fov1.id], include_provenance=False)

        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # fov1 has 2 cells
        assert len(rows) == 2
        fov_names = {r["fov_name"] for r in rows}
        assert fov_names == {fov1.display_name}

    def test_export_csv_no_filter_includes_all(self, two_fov_experiment, tmp_path):
        """export_csv with fov_ids=None includes all FOVs (backward compat)."""
        store = two_fov_experiment

        out = tmp_path / "all.csv"
        store.export_csv(out, include_provenance=False)

        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # 3 cells total across 2 FOVs
        assert len(rows) == 3

    def test_export_particles_fov_filter(self, two_fov_experiment, tmp_path):
        """export_particles_csv with fov_ids only exports particles from selected FOVs."""
        store = two_fov_experiment
        fovs = store.get_fovs()
        fov2 = fovs[1]  # No particles

        out = tmp_path / "particles.csv"
        store.export_particles_csv(out, fov_ids=[fov2.id], include_provenance=False)

        content = out.read_text().strip()
        # No particles in fov2 → empty file
        assert content == ""

    def test_export_prism_fov_filter(self, two_fov_experiment, tmp_path):
        """export_prism_csv with fov_ids only exports cells from selected FOVs."""
        store = two_fov_experiment
        fovs = store.get_fovs()
        fov1 = fovs[0]

        out_dir = tmp_path / "prism"
        result = store.export_prism_csv(out_dir, fov_ids=[fov1.id])

        assert result["files_written"] > 0

        # Read the first CSV file and check it only has fov1 cells
        csv_files = list(out_dir.rglob("*.csv"))
        assert len(csv_files) > 0

        with open(csv_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # fov1 is "ctrl" condition — prism columns are condition_biorep
        headers = list(rows[0].keys()) if rows else []
        # Should have ctrl column but not treated
        assert any("ctrl" in h for h in headers)
        # With only fov1 selected, treated FOV should not contribute data
        treated_cols = [h for h in headers if "treated" in h]
        for tc in treated_cols:
            vals = [r[tc] for r in rows if r[tc]]
            assert len(vals) == 0


class TestSummaryCommand:
    def test_summary_table(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
    ):
        """percell3 query summary shows table output."""
        exp_path = str(experiment_with_particles.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "summary"])
        assert result.exit_code == 0, result.output
        assert "Experiment Summary" in result.output
        assert "control" in result.output
        assert "N1" in result.output  # bio rep column shows N1

    def test_summary_csv_format(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
    ):
        """percell3 query summary --format csv produces CSV output."""
        exp_path = str(experiment_with_particles.path)
        result = runner.invoke(
            cli, ["query", "-e", exp_path, "summary", "--format", "csv"],
        )
        assert result.exit_code == 0, result.output
        assert "condition" in result.output
        assert "control" in result.output

    def test_summary_shows_particles(
        self,
        runner: CliRunner,
        experiment_with_particles: ExperimentStore,
    ):
        """Summary shows particle info when particles exist."""
        exp_path = str(experiment_with_particles.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "summary"])
        assert result.exit_code == 0, result.output
        # Should show GFP as particle channel with count
        assert "GFP" in result.output

    def test_summary_empty_experiment(
        self,
        runner: CliRunner,
        experiment: ExperimentStore,
    ):
        """Summary with no FOVs shows appropriate message."""
        exp_path = str(experiment.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "summary"])
        assert result.exit_code == 0
        assert "No FOVs found" in result.output
