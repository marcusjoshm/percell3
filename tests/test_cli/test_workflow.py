"""Tests for percell3 workflow command."""

from pathlib import Path

from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore


class TestWorkflowList:
    def test_list_presets(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "list"])
        assert result.exit_code == 0
        assert "complete" in result.output
        assert "measure_only" in result.output

    def test_list_with_steps(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "list", "--steps"])
        assert result.exit_code == 0
        # Rich may wrap the table title across lines
        assert "Step" in result.output
        assert "import_tiff" in result.output

    def test_list_json_format(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "list", "--format", "json"])
        assert result.exit_code == 0
        assert '"complete"' in result.output
        assert '"description"' in result.output

    def test_list_csv_format(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "list", "--format", "csv"])
        assert result.exit_code == 0
        assert "name,description" in result.output
        assert "complete" in result.output


class TestWorkflowRun:
    def test_run_unknown_workflow(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(
            cli, ["workflow", "run", "nonexistent", "-e", str(experiment_path)]
        )
        assert result.exit_code == 1
        assert "Unknown workflow" in result.output

    def test_run_complete_shows_not_available(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(
            cli, ["workflow", "run", "complete", "-e", str(experiment_path)]
        )
        assert result.exit_code == 0
        # Rich may wrap text across lines; check for key phrase
        assert "segment and measure" in result.output

    def test_run_measure_only_shows_not_available(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(
            cli, ["workflow", "run", "measure_only", "-e", str(experiment_path)]
        )
        assert result.exit_code == 0
        assert "measure module" in result.output


class TestWorkflowHelp:
    def test_workflow_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "Manage and run workflows" in result.output

    def test_workflow_run_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["workflow", "run", "--help"])
        assert result.exit_code == 0
        assert "Run a preset workflow" in result.output
