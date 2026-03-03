"""Tests for percell3 import command."""

from pathlib import Path

import numpy as np
import pytest
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
        assert "FOVs imported: 1" in result.output
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


class TestAutoFlag:
    def test_auto_imports_all_groups(
        self, runner: CliRunner, experiment_path: Path,
        multi_condition_tiff_dir: Path,
    ):
        """--auto --yes with multi-FOV dir imports all groups."""
        result = runner.invoke(
            cli,
            ["import", str(multi_condition_tiff_dir), "-e", str(experiment_path),
             "--auto", "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output

    def test_auto_with_channel_map_override(
        self, runner: CliRunner, experiment_path: Path,
        multi_condition_tiff_dir: Path,
    ):
        """--auto --yes --channel-map overrides auto-generated channel names."""
        result = runner.invoke(
            cli,
            ["import", str(multi_condition_tiff_dir), "-e", str(experiment_path),
             "--auto", "--yes", "--channel-map", "00:DAPI"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output

    def test_auto_and_condition_mutually_exclusive(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        """--auto and --condition together produce an error."""
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--auto", "--condition", "ctrl", "--yes"],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_auto_help_shows_flag(self, runner: CliRunner):
        result = runner.invoke(cli, ["import", "--help"])
        assert "--auto" in result.output


class TestFilesFlag:
    def test_import_specific_files(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        """--files imports only the specified files."""
        # tiff_dir has img_ch00_t00.tif and img_ch01_t00.tif
        one_file = tiff_dir / "img_ch00_t00.tif"
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--files", str(one_file), "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output
        assert "Images written: 1" in result.output

    def test_import_multiple_files(
        self, runner: CliRunner, experiment_path: Path, tiff_dir: Path,
    ):
        """--files can be repeated for multiple files."""
        f1 = tiff_dir / "img_ch00_t00.tif"
        f2 = tiff_dir / "img_ch01_t00.tif"
        result = runner.invoke(
            cli,
            ["import", str(tiff_dir), "-e", str(experiment_path),
             "--files", str(f1), "--files", str(f2), "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output
        assert "Images written: 2" in result.output


class TestTileOptions:
    @pytest.fixture
    def tile_tiff_dir(self, tmp_path: Path) -> Path:
        """Create a 2x2 tile grid with 1 channel."""
        d = tmp_path / "tiles"
        d.mkdir()
        for s in range(4):
            data = np.full((32, 32), fill_value=(s + 1) * 10, dtype=np.uint16)
            tifffile.imwrite(str(d / f"FOV1_s{s:02d}_ch00.tif"), data)
        return d

    def test_tile_grid_import(
        self, runner: CliRunner, experiment_path: Path, tile_tiff_dir: Path,
    ):
        """--tile-grid 2x2 stitches 4 tiles into a single FOV."""
        result = runner.invoke(
            cli,
            ["import", str(tile_tiff_dir), "-e", str(experiment_path),
             "--tile-grid", "2x2", "--tile-type", "row_by_row",
             "--tile-order", "right_and_down", "--yes"],
        )
        assert result.exit_code == 0
        assert "Import complete" in result.output
        assert "FOVs imported: 1" in result.output
        assert "Images written: 1" in result.output

    def test_tile_grid_invalid_format(
        self, runner: CliRunner, experiment_path: Path, tile_tiff_dir: Path,
    ):
        """--tile-grid with bad format produces an error."""
        result = runner.invoke(
            cli,
            ["import", str(tile_tiff_dir), "-e", str(experiment_path),
             "--tile-grid", "abc", "--yes"],
        )
        assert result.exit_code == 1
        assert "Invalid" in result.output

    def test_tile_type_without_grid_errors(
        self, runner: CliRunner, experiment_path: Path, tile_tiff_dir: Path,
    ):
        """--tile-type without --tile-grid produces an error."""
        result = runner.invoke(
            cli,
            ["import", str(tile_tiff_dir), "-e", str(experiment_path),
             "--tile-type", "row_by_row", "--yes"],
        )
        assert result.exit_code == 1
        assert "--tile-grid is required" in result.output

    def test_help_shows_tile_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["import", "--help"])
        assert "--tile-grid" in result.output
        assert "--tile-type" in result.output
        assert "--tile-order" in result.output
