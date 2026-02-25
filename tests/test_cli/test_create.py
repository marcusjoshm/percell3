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

    def test_create_in_empty_existing_directory(self, runner: CliRunner, tmp_path: Path):
        """Empty existing directory should be accepted without error."""
        path = tmp_path / "empty.percell"
        path.mkdir()
        result = runner.invoke(cli, ["create", str(path)])
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert (path / "experiment.db").exists()

    def test_create_non_empty_without_overwrite_fails(self, runner: CliRunner, tmp_path: Path):
        """Non-empty directory without --overwrite should fail."""
        path = tmp_path / "existing.percell"
        path.mkdir()
        (path / "some_file.txt").write_text("data")
        result = runner.invoke(cli, ["create", str(path)])
        assert result.exit_code == 1
        assert "not empty" in result.output

    def test_create_non_empty_with_overwrite(self, runner: CliRunner, tmp_path: Path):
        """Non-empty directory with --overwrite should succeed."""
        path = tmp_path / "existing.percell"
        path.mkdir()
        (path / "old_file.txt").write_text("old data")
        result = runner.invoke(cli, ["create", str(path), "--overwrite"])
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert (path / "experiment.db").exists()
        assert not (path / "old_file.txt").exists()

    def test_create_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["create", "--help"])
        assert result.exit_code == 0
        assert "Create a new .percell experiment" in result.output

    def test_cli_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "PerCell 3" in result.output
        assert "create" in result.output
