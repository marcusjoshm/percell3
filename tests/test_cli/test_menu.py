"""Tests for percell3 interactive menu."""

from pathlib import Path

from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.cli.menu import MenuState, _show_header, _show_menu
from percell3.core import ExperimentStore


class TestMenuLaunch:
    def test_no_args_launches_menu(self, runner: CliRunner):
        # Menu prompts for input; send 'q' to quit immediately
        result = runner.invoke(cli, [], input="q\n")
        assert result.exit_code == 0
        assert "PerCell 3" in result.output
        assert "Create experiment" in result.output
        assert "coming soon" in result.output

    def test_menu_shows_disabled_items(self, runner: CliRunner):
        result = runner.invoke(cli, [], input="q\n")
        assert "Segment cells" in result.output
        assert "coming soon" in result.output

    def test_disabled_item_shows_message(self, runner: CliRunner):
        # Select disabled item "3" (Segment), then quit
        result = runner.invoke(cli, [], input="3\nq\n")
        assert "not yet available" in result.output

    def test_help_shows_commands(self, runner: CliRunner):
        result = runner.invoke(cli, [], input="h\nq\n")
        assert "percell3 create" in result.output
        assert "percell3 import" in result.output

    def test_invalid_option_shows_error(self, runner: CliRunner):
        result = runner.invoke(cli, [], input="z\nq\n")
        assert "Invalid option" in result.output


class TestMenuState:
    def test_initial_state(self):
        state = MenuState()
        assert state.experiment_path is None
        assert state.store is None
        assert state.running is True

    def test_set_experiment(self, experiment: ExperimentStore):
        state = MenuState()
        state.set_experiment(experiment.path)
        assert state.experiment_path == experiment.path
        assert state.store is not None
        state.close()

    def test_close_releases_store(self, experiment: ExperimentStore):
        state = MenuState()
        state.set_experiment(experiment.path)
        state.close()
        assert state.store is None


class TestMenuCreateExperiment:
    def test_create_via_menu(self, runner: CliRunner, tmp_path: Path):
        exp_path = tmp_path / "menu_exp.percell"
        result = runner.invoke(
            cli, [],
            input=f"1\n{exp_path}\nMyExp\nA test\nq\n",
        )
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert exp_path.exists()


class TestMenuSelectExperiment:
    def test_select_experiment_via_menu(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = runner.invoke(
            cli, [],
            input=f"e\n{experiment_path}\nq\n",
        )
        assert result.exit_code == 0
        assert "Opened experiment" in result.output

    def test_select_nonexistent_path(self, runner: CliRunner):
        result = runner.invoke(
            cli, [],
            input="e\n/nonexistent/path.percell\nq\n",
        )
        assert "does not exist" in result.output
