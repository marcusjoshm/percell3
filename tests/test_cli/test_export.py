"""Tests for percell3 export command."""

from pathlib import Path

from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore


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
