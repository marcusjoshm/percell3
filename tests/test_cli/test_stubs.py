"""Tests for percell3 stub commands (coming soon)."""

from click.testing import CliRunner

from percell3.cli.main import cli


class TestStubCommands:
    def test_measure_shows_coming_soon(self, runner: CliRunner):
        result = runner.invoke(cli, ["measure"])
        assert result.exit_code == 0
        assert "not yet available" in result.output

    def test_threshold_shows_coming_soon(self, runner: CliRunner):
        result = runner.invoke(cli, ["threshold"])
        assert result.exit_code == 0
        assert "not yet available" in result.output


class TestStubsInHelp:
    def test_help_shows_all_commands(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "segment" in result.output
        assert "measure" in result.output
        assert "threshold" in result.output
        assert "create" in result.output
        assert "import" in result.output
        assert "query" in result.output
        assert "export" in result.output
        assert "workflow" in result.output
