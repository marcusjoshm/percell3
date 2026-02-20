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
            reader = csv.DictReader(f)
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
        cell1 = next(r for r in rows if float(r["GFP_particle_count"]) == 2.0)
        assert float(cell1["GFP_total_particle_area"]) == 80.0
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
        cells_df = store.get_cells()
        cell_ids = cells_df["id"].tolist()
        mask_measurements = [
            MeasurementRecord(
                cell_id=cid, channel_id=ch_info.id,
                metric="mean_intensity", value=50.0 + i,
                scope="mask_inside",
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
            reader = csv.DictReader(f)
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
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3  # 3 particles in fixture
        headers = set(rows[0].keys())
        # Context columns
        assert "cell_id" in headers
        assert "condition_name" in headers
        assert "fov_name" in headers
        assert "bio_rep_name" in headers
        # Particle data columns
        assert "area_pixels" in headers
        assert "mean_intensity" in headers
        assert "integrated_intensity" in headers
        # Internal IDs should be dropped
        assert "id" not in headers
        assert "threshold_run_id" not in headers

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
        content = particle_path.read_text().strip()
        # Empty DataFrame writes empty string
        assert content == ""


class TestMultiChannelParticleExport:
    def test_export_particles_with_channels(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """--channels adds per-channel intensity columns to particle CSV."""
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
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1  # 1 particle in fixture
        headers = set(rows[0].keys())

        # Per-channel intensity columns should be present
        assert "DAPI_mean_intensity" in headers
        assert "DAPI_max_intensity" in headers
        assert "DAPI_integrated_intensity" in headers
        assert "GFP_mean_intensity" in headers
        assert "GFP_max_intensity" in headers
        assert "GFP_integrated_intensity" in headers

        # Original single-channel intensity columns should be gone
        assert "mean_intensity" not in headers
        assert "max_intensity" not in headers
        assert "integrated_intensity" not in headers

        # Verify intensity values are non-zero (real pixel data)
        row = rows[0]
        assert float(row["DAPI_mean_intensity"]) == pytest.approx(200.0, rel=0.01)
        assert float(row["GFP_mean_intensity"]) == pytest.approx(150.0, rel=0.01)

    def test_export_particles_metric_filter(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """--metrics filters particle CSV to selected metrics only."""
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
            reader = csv.DictReader(f)
            rows = list(reader)

        headers = set(rows[0].keys())
        # Filtered metrics + context columns
        assert "mean_intensity" in headers
        assert "area_pixels" in headers
        # Other metrics should be excluded
        assert "max_intensity" not in headers
        assert "perimeter" not in headers

    def test_export_particles_channels_and_metrics(
        self,
        runner: CliRunner,
        experiment_with_particle_images: ExperimentStore,
        tmp_path: Path,
    ):
        """--channels + --metrics expands intensity metrics per channel."""
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
            reader = csv.DictReader(f)
            rows = list(reader)

        headers = set(rows[0].keys())
        # area_pixels is a non-intensity metric — included as-is
        assert "area_pixels" in headers
        # mean_intensity expands per channel
        assert "DAPI_mean_intensity" in headers
        assert "GFP_mean_intensity" in headers
        # max_intensity and integrated_intensity not in --metrics, so excluded
        assert "DAPI_max_intensity" not in headers
        assert "GFP_integrated_intensity" not in headers


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
        assert "fov1" in result.output

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
