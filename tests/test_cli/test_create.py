"""Tests for percell3 create command."""

from pathlib import Path

from click.testing import CliRunner

from percell3.cli.main import cli


class TestCreateCommand:
    def test_create_experiment(self, runner: CliRunner, tmp_path: Path):
        path = tmp_path / "new.percell"
        result = runner.invoke(cli, ["create", str(path)])
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert path.exists()
        assert (path / "experiment.db").exists()
        assert (path / "images.zarr").exists()

    def test_create_with_name(self, runner: CliRunner, tmp_path: Path):
        path = tmp_path / "named.percell"
        result = runner.invoke(cli, ["create", str(path), "--name", "My Experiment"])
        assert result.exit_code == 0
        assert path.exists()

    def test_create_already_exists(self, runner: CliRunner, tmp_path: Path):
        path = tmp_path / "existing.percell"
        path.mkdir()
        result = runner.invoke(cli, ["create", str(path)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_create_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["create", "--help"])
        assert result.exit_code == 0
        assert "Create a new .percell experiment" in result.output

    def test_cli_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "PerCell 3" in result.output
        assert "create" in result.output
