"""Tests for percell3 export-prism command."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore
from percell3.core.models import CellRecord, MeasurementRecord


@pytest.fixture
def prism_experiment(tmp_path: Path) -> ExperimentStore:
    """Experiment with multi-condition, multi-biorep data for Prism export testing.

    Layout:
    - 2 conditions: Control, HS
    - 2 bio_reps: N1, N2
    - 2 FOVs per (condition, bio_rep) — to test pooling
    - 2 channels: DAPI, GFP
    - Metrics: mean_intensity, median_intensity on both channels
    - Particle summary metrics on GFP only
    - Different cell counts per condition to test ragged columns
    """
    store = ExperimentStore.create(tmp_path / "prism_test.percell", name="PrismTest")

    store.add_channel("DAPI", role="nuclear")
    store.add_channel("GFP")
    store.add_condition("Control")
    store.add_condition("HS")
    store.add_bio_rep("N2")  # N1 is auto-created

    # Segmentation run
    seg_id = store.add_segmentation_run(channel="DAPI", model_name="cyto3")
    dapi_ch = store.get_channel("DAPI")
    gfp_ch = store.get_channel("GFP")

    img = np.zeros((64, 64), dtype=np.uint16)

    all_cell_ids: dict[str, list[int]] = {}

    # Add FOVs, images, cells, and measurements
    for cond in ("Control", "HS"):
        for bio_rep in ("N1", "N2"):
            key = f"{cond}_{bio_rep}"
            all_cell_ids[key] = []
            for fov_num in (1, 2):
                fov_id = store.add_fov(
                    cond, width=64, height=64, pixel_size_um=0.65,
                    bio_rep=bio_rep,
                )
                store.write_image(fov_id, "DAPI", img)
                store.write_image(fov_id, "GFP", img)

                # Different cell counts: Control gets 3 cells/FOV, HS gets 2
                n_cells = 3 if cond == "Control" else 2
                cells = [
                    CellRecord(
                        fov_id=fov_id, segmentation_id=seg_id, label_value=i + 1,
                        centroid_x=10.0 + i * 10, centroid_y=20.0,
                        bbox_x=5 + i * 10, bbox_y=15, bbox_w=15, bbox_h=15,
                        area_pixels=200.0,
                    )
                    for i in range(n_cells)
                ]
                cell_ids = store.add_cells(cells)
                all_cell_ids[key].extend(cell_ids)

                # Add measurements for both channels
                measurements = []
                for cid in cell_ids:
                    for ch, ch_info in [("DAPI", dapi_ch), ("GFP", gfp_ch)]:
                        measurements.append(MeasurementRecord(
                            cell_id=cid, channel_id=ch_info.id,
                            metric="mean_intensity", value=100.0 + cid,
                        ))
                        measurements.append(MeasurementRecord(
                            cell_id=cid, channel_id=ch_info.id,
                            metric="median_intensity", value=90.0 + cid,
                        ))
                store.add_measurements(measurements)

    # Add particle summary metrics for GFP on Control_N1 cells
    control_n1_ids = all_cell_ids["Control_N1"]
    particle_summaries = []
    for cid in control_n1_ids:
        particle_summaries.append(MeasurementRecord(
            cell_id=cid, channel_id=gfp_ch.id,
            metric="particle_count", value=2.0,
        ))
        particle_summaries.append(MeasurementRecord(
            cell_id=cid, channel_id=gfp_ch.id,
            metric="mean_particle_area", value=40.0,
        ))
    store.add_measurements(particle_summaries)

    yield store
    store.close()


class TestPrismExportCore:
    def test_basic_directory_structure(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Creates channel subdirectories with metric CSV files."""
        out_dir = tmp_path / "prism_out"
        result = prism_experiment.export_prism_csv(out_dir)

        assert result["files_written"] > 0
        assert result["channels_exported"] == 2

        # Channel directories exist
        assert (out_dir / "DAPI").is_dir()
        assert (out_dir / "GFP").is_dir()

        # Metric files exist
        assert (out_dir / "DAPI" / "mean_intensity.csv").is_file()
        assert (out_dir / "DAPI" / "median_intensity.csv").is_file()
        assert (out_dir / "GFP" / "mean_intensity.csv").is_file()
        assert (out_dir / "GFP" / "median_intensity.csv").is_file()

        # Particle summary files exist in GFP
        assert (out_dir / "GFP" / "particle_count.csv").is_file()
        assert (out_dir / "GFP" / "mean_particle_area.csv").is_file()

        # Particle files do NOT exist in DAPI (no particle data there)
        assert not (out_dir / "DAPI" / "particle_count.csv").exists()

    def test_column_headers_alphabetical(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Columns are condition_biorep sorted alphabetically."""
        out_dir = tmp_path / "prism_out"
        prism_experiment.export_prism_csv(out_dir)

        with open(out_dir / "DAPI" / "mean_intensity.csv") as f:
            reader = csv.reader(f)
            headers = next(reader)

        assert headers == ["Control_N1", "Control_N2", "HS_N1", "HS_N2"]

    def test_fov_pooling(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Cells from 2 FOVs per (condition, bio_rep) are pooled into one column."""
        out_dir = tmp_path / "prism_out"
        prism_experiment.export_prism_csv(out_dir)

        with open(out_dir / "DAPI" / "mean_intensity.csv") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)

        # Control has 3 cells/FOV * 2 FOVs = 6 cells per (Control, N1)
        # HS has 2 cells/FOV * 2 FOVs = 4 cells per (HS, N1)
        control_n1_idx = headers.index("Control_N1")
        hs_n1_idx = headers.index("HS_N1")

        # Count non-empty values in each column
        control_n1_values = [r[control_n1_idx] for r in rows if r[control_n1_idx]]
        hs_n1_values = [r[hs_n1_idx] for r in rows if r[hs_n1_idx]]

        assert len(control_n1_values) == 6
        assert len(hs_n1_values) == 4

    def test_ragged_columns(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Shorter columns are padded with empty strings."""
        out_dir = tmp_path / "prism_out"
        prism_experiment.export_prism_csv(out_dir)

        with open(out_dir / "DAPI" / "mean_intensity.csv") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)

        # Control columns have 6 rows, HS columns have 4 rows
        # Total rows should be max(6, 6, 4, 4) = 6
        assert len(rows) == 6

        # Last 2 rows should have empty HS columns
        hs_n1_idx = headers.index("HS_N1")
        assert rows[4][hs_n1_idx] == ""
        assert rows[5][hs_n1_idx] == ""

    def test_channel_filter(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Only specified channels are exported."""
        out_dir = tmp_path / "prism_out"
        result = prism_experiment.export_prism_csv(out_dir, channels=["DAPI"])

        assert result["channels_exported"] == 1
        assert (out_dir / "DAPI").is_dir()
        assert not (out_dir / "GFP").exists()

    def test_metric_filter(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Only specified metrics are exported."""
        out_dir = tmp_path / "prism_out"
        result = prism_experiment.export_prism_csv(out_dir, metrics=["mean_intensity"])

        assert (out_dir / "DAPI" / "mean_intensity.csv").is_file()
        assert not (out_dir / "DAPI" / "median_intensity.csv").exists()

    def test_scope_suffix_in_filename(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Non-default scope adds suffix to filenames."""
        store = prism_experiment
        # Add mask_inside measurements
        gfp_ch = store.get_channel("GFP")
        cells_df = store.get_cells(is_valid=True)
        mask_measurements = [
            MeasurementRecord(
                cell_id=row["id"], channel_id=gfp_ch.id,
                metric="mean_intensity", value=50.0,
                scope="mask_inside",
            )
            for _, row in cells_df.iterrows()
        ]
        store.add_measurements(mask_measurements)

        out_dir = tmp_path / "prism_out"
        store.export_prism_csv(out_dir, channels=["GFP"], scope="mask_inside")

        # Regular metric gets scope suffix
        assert (out_dir / "GFP" / "mean_intensity_mask_inside.csv").is_file()
        # Particle metrics do NOT get scope suffix
        assert (out_dir / "GFP" / "particle_count.csv").is_file()

    def test_empty_experiment(
        self, tmp_path: Path,
    ):
        """Empty experiment returns zero files without error."""
        store = ExperimentStore.create(tmp_path / "empty.percell", name="Empty")
        try:
            out_dir = tmp_path / "prism_out"
            result = store.export_prism_csv(out_dir)
            assert result["files_written"] == 0
            assert result["channels_exported"] == 0
        finally:
            store.close()

    def test_only_valid_cells_exported(
        self, prism_experiment: ExperimentStore, tmp_path: Path,
    ):
        """Cells marked is_valid=False are excluded."""
        store = prism_experiment
        # Mark 2 cells as invalid via direct SQL
        cells_df = store.get_cells(is_valid=False)
        first_two = cells_df["id"].tolist()[:2]
        for cid in first_two:
            store._conn.execute(
                "UPDATE cells SET is_valid = 0 WHERE id = ?", (cid,),
            )
        store._conn.commit()

        out_dir = tmp_path / "prism_out"
        store.export_prism_csv(out_dir)

        # Read all values from one file and count total non-empty cells
        with open(out_dir / "DAPI" / "mean_intensity.csv") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            all_values = [v for row in reader for v in row if v]

        # Total cells = 20 (various per condition_biorep) minus 2 invalid
        assert len(all_values) == 18


class TestPrismExportCLI:
    def test_cli_export_prism(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """End-to-end CLI test."""
        exp_path = str(prism_experiment.path)
        out_dir = tmp_path / "cli_prism"
        result = runner.invoke(
            cli, ["export-prism", str(out_dir), "-e", exp_path],
        )
        assert result.exit_code == 0, result.output
        assert "Prism export complete" in result.output
        assert (out_dir / "DAPI" / "mean_intensity.csv").is_file()

    def test_cli_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["export-prism", "--help"])
        assert result.exit_code == 0
        assert "Prism-ready CSV" in result.output

    def test_cli_overwrite_protection(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """Non-empty directory rejected without --overwrite."""
        exp_path = str(prism_experiment.path)
        out_dir = tmp_path / "cli_prism"
        out_dir.mkdir()
        (out_dir / "existing.txt").write_text("existing")

        result = runner.invoke(
            cli, ["export-prism", str(out_dir), "-e", exp_path],
        )
        assert result.exit_code == 1
        assert "not empty" in result.output.lower()

        # With --overwrite, should succeed
        result = runner.invoke(
            cli, ["export-prism", str(out_dir), "-e", exp_path, "--overwrite"],
        )
        assert result.exit_code == 0

    def test_cli_missing_parent(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """Nonexistent parent directory fails with clear error."""
        exp_path = str(prism_experiment.path)
        bad_dir = tmp_path / "nonexistent" / "out"
        result = runner.invoke(
            cli, ["export-prism", str(bad_dir), "-e", exp_path],
        )
        assert result.exit_code == 1
        assert "does not exist" in result.output.lower()

    def test_cli_existing_file_rejected(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """Existing file at output path is rejected."""
        exp_path = str(prism_experiment.path)
        out_path = tmp_path / "output.csv"
        out_path.write_text("data")
        result = runner.invoke(
            cli, ["export-prism", str(out_path), "-e", exp_path],
        )
        assert result.exit_code == 1
        assert "existing file" in result.output.lower()

    def test_cli_no_measurements(
        self,
        runner: CliRunner,
        tmp_path: Path,
    ):
        """Experiment with no measurements shows helpful message."""
        store = ExperimentStore.create(tmp_path / "empty.percell", name="Empty")
        store.close()
        out_dir = tmp_path / "prism_out"
        result = runner.invoke(
            cli, ["export-prism", str(out_dir), "-e", str(tmp_path / "empty.percell")],
        )
        assert result.exit_code == 0
        assert "no measurements" in result.output.lower()

    def test_cli_channel_filter(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """--channels filters exported channels."""
        exp_path = str(prism_experiment.path)
        out_dir = tmp_path / "cli_prism"
        result = runner.invoke(
            cli, ["export-prism", str(out_dir), "-e", exp_path, "--channels", "GFP"],
        )
        assert result.exit_code == 0
        assert (out_dir / "GFP").is_dir()
        assert not (out_dir / "DAPI").exists()

    def test_cli_metric_filter(
        self,
        runner: CliRunner,
        prism_experiment: ExperimentStore,
        tmp_path: Path,
    ):
        """--metrics filters exported metrics."""
        exp_path = str(prism_experiment.path)
        out_dir = tmp_path / "cli_prism"
        result = runner.invoke(
            cli,
            ["export-prism", str(out_dir), "-e", exp_path,
             "--metrics", "mean_intensity"],
        )
        assert result.exit_code == 0
        assert (out_dir / "DAPI" / "mean_intensity.csv").is_file()
        assert not (out_dir / "DAPI" / "median_intensity.csv").exists()
