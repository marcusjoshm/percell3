"""Tests for percell3 import command."""

from pathlib import Path

import numpy as np
import tifffile
from click.testing import CliRunner

from percell3.cli.main import cli


class TestImportCommand:
    def test_import_tiff_directory(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        result = runner.invoke(
            cli, ["import", str(tiff_dir), "-e", str(experiment_path), "--yes"]
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output
        assert "Regions imported: 1" in result.output
        assert "Images written: 2" in result.output

    def test_import_with_condition(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--condition", "treated", "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output

    def test_import_with_channel_map(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--channel-map", "00:DAPI", "--channel-map", "01:GFP", "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output

    def test_import_nonexistent_source(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(
            cli, ["import", "/nonexistent/path", "-e", str(experiment_path)]
        )
        # Click checks exists=True on the path argument
        assert result.exit_code != 0

    def test_import_nonexistent_experiment(
        self, runner: CliRunner, tiff_dir: Path,
    ):
        result = runner.invoke(
            cli, ["import", str(tiff_dir), "-e", "/nonexistent/exp.percell", "--yes"]
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_import_shows_preview(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        # Without --yes, import shows preview and prompts
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path)],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Scan results" in result.output
        assert "Files found" in result.output
        assert "Import cancelled" in result.output

    def test_import_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0
        assert "Import TIFF images" in result.output
        assert "--channel-map" in result.output

    def test_invalid_channel_map_format(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--channel-map", "INVALID", "--yes"],
        )
        assert result.exit_code == 1
        assert "Invalid channel map" in result.output
