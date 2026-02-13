"""Tests for percell3 query command."""

from pathlib import Path

from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore


class TestQueryChannels:
    def test_channels_table(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "channels"])
        assert result.exit_code == 0
        assert "DAPI" in result.output
        assert "GFP" in result.output

    def test_channels_csv(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(
            cli, ["query", "-e", exp_path, "channels", "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "name,role,color" in result.output
        assert "DAPI" in result.output

    def test_channels_json(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(
            cli, ["query", "-e", exp_path, "channels", "--format", "json"]
        )
        assert result.exit_code == 0
        assert '"DAPI"' in result.output

    def test_channels_empty(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(cli, ["query", "-e", str(experiment_path), "channels"])
        assert result.exit_code == 0
        assert "No channels found" in result.output


class TestQueryRegions:
    def test_regions_table(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "regions"])
        assert result.exit_code == 0
        assert "region1" in result.output
        assert "control" in result.output

    def test_regions_with_condition_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(
            cli, ["query", "-e", exp_path, "regions", "--condition", "control"]
        )
        assert result.exit_code == 0
        assert "region1" in result.output

    def test_regions_empty(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(cli, ["query", "-e", str(experiment_path), "regions"])
        assert result.exit_code == 0
        assert "No regions found" in result.output


class TestQueryConditions:
    def test_conditions_table(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ):
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(cli, ["query", "-e", exp_path, "conditions"])
        assert result.exit_code == 0
        assert "control" in result.output


class TestQueryHelp:
    def test_query_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["query", "--help"])
        assert result.exit_code == 0
        assert "Query experiment data" in result.output

    def test_query_nonexistent_experiment(self, runner: CliRunner):
        result = runner.invoke(
            cli, ["query", "-e", "/nonexistent/exp.percell", "channels"]
        )
        assert result.exit_code != 0
