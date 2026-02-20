"""Tests for percell3 interactive menu."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from percell3.cli import _recent
from percell3.cli.main import cli
from percell3.cli.menu import (
    MenuState,
    _MenuCancel,
    _MenuHome,
    _print_numbered_list,
    _show_header,
    _show_menu,
    menu_prompt,
    numbered_select_many,
    numbered_select_one,
)
from percell3.cli.utils import console
from percell3.core import ExperimentStore


@pytest.fixture(autouse=True)
def _isolate_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect recent experiments to a temp directory to isolate tests."""
    config_dir = tmp_path / "config"
    recent_file = config_dir / "recent.json"
    monkeypatch.setattr(_recent, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(_recent, "_RECENT_FILE", recent_file)


def _invoke_menu(runner: CliRunner, args=None, **kwargs):
    """Invoke CLI with _is_interactive patched to True so the menu launches."""
    with patch("percell3.cli.main._is_interactive", return_value=True):
        return runner.invoke(cli, args or [], **kwargs)


class TestMenuLaunch:
    def test_no_args_launches_menu(self, runner: CliRunner):
        # Menu prompts for input; send 'q' to quit immediately
        result = _invoke_menu(runner, input="q\n")
        assert result.exit_code == 0
        assert "PerCell 3" in result.output
        assert "Create experiment" in result.output
        assert "coming soon" in result.output

    def test_menu_shows_disabled_items(self, runner: CliRunner):
        result = _invoke_menu(runner, input="q\n")
        assert "Segment cells" in result.output
        assert "coming soon" in result.output

    def test_disabled_item_shows_message(self, runner: CliRunner):
        # Select disabled item "0" (Plugin manager), then quit
        result = _invoke_menu(runner, input="0\nq\n")
        assert "not yet available" in result.output

    def test_help_shows_commands(self, runner: CliRunner):
        # Help is now '?' instead of 'h'
        result = _invoke_menu(runner, input="?\nq\n")
        assert "percell3 create" in result.output
        assert "percell3 import" in result.output

    def test_invalid_option_shows_error(self, runner: CliRunner):
        result = _invoke_menu(runner, input="z\nq\n")
        assert "Invalid option" in result.output

    def test_non_tty_shows_help(self, runner: CliRunner):
        """When stdin is not a TTY, show help instead of menu."""
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output


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
        result = _invoke_menu(
            runner,
            input=f"1\n{exp_path}\nMyExp\nA test\nq\n",
        )
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert exp_path.exists()


class TestMenuSelectExperiment:
    def test_select_experiment_via_menu(
        self, runner: CliRunner, experiment_path: Path,
    ):
        result = _invoke_menu(
            runner,
            input=f"e\n{experiment_path}\nq\n",
        )
        assert result.exit_code == 0
        assert "Opened experiment" in result.output

    def test_select_nonexistent_path(self, runner: CliRunner):
        result = _invoke_menu(
            runner,
            input="e\n/nonexistent/path.percell\nq\n",
        )
        assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# Navigation tests (Phase 2A)
# ---------------------------------------------------------------------------


class TestMenuPrompt:
    """Tests for the menu_prompt() helper."""

    def test_returns_valid_choice(self):
        with patch.object(console, "input", return_value="y"):
            result = menu_prompt("Confirm?", choices=["y", "n"])
        assert result == "y"

    def test_rejects_invalid_choice(self):
        with patch.object(console, "input", side_effect=["x", "y"]):
            result = menu_prompt("Confirm?", choices=["y", "n"])
        assert result == "y"

    def test_b_raises_cancel(self):
        with patch.object(console, "input", return_value="b"):
            with pytest.raises(_MenuCancel):
                menu_prompt("Pick")

    def test_h_raises_home(self):
        with patch.object(console, "input", return_value="h"):
            with pytest.raises(_MenuHome):
                menu_prompt("Pick")

    def test_q_raises_cancel_in_subprompt(self):
        """q in a sub-prompt acts as back (cancel), not quit."""
        with patch.object(console, "input", return_value="q"):
            with pytest.raises(_MenuCancel):
                menu_prompt("Pick")

    def test_default_on_empty_input(self):
        with patch.object(console, "input", return_value=""):
            result = menu_prompt("Name", default="foo")
        assert result == "foo"

    def test_eof_raises_cancel(self):
        with patch.object(console, "input", side_effect=EOFError):
            with pytest.raises(_MenuCancel):
                menu_prompt("Pick")

    def test_freeform_without_choices(self):
        with patch.object(console, "input", return_value="/some/path"):
            result = menu_prompt("Path")
        assert result == "/some/path"


class TestHomeNavigation:
    """Test that 'h' from nested menus returns to home."""

    def test_h_from_query_returns_to_home(self, runner: CliRunner, experiment_path: Path):
        # Open experiment, enter query, press h, then q
        result = _invoke_menu(
            runner,
            input=f"e\n{experiment_path}\n7\nh\nq\n",
        )
        assert result.exit_code == 0
        # Should see the menu header twice (once before query, once after h returns home)
        assert result.output.count("PerCell 3") >= 2


# ---------------------------------------------------------------------------
# Numbered selection tests (Phase 2B)
# ---------------------------------------------------------------------------


class TestNumberedSelectOne:
    def test_single_item_auto_selects(self):
        result = numbered_select_one(["only"])
        assert result == "only"

    def test_selects_by_number(self):
        with patch.object(console, "input", return_value="2"):
            result = numbered_select_one(["a", "b", "c"])
        assert result == "b"

    def test_b_raises_cancel(self):
        with patch.object(console, "input", return_value="b"):
            with pytest.raises(_MenuCancel):
                numbered_select_one(["a", "b"])

    def test_h_raises_home(self):
        with patch.object(console, "input", return_value="h"):
            with pytest.raises(_MenuHome):
                numbered_select_one(["a", "b"])

    def test_invalid_number_reprompts(self):
        with patch.object(console, "input", side_effect=["0", "5", "1"]):
            result = numbered_select_one(["a", "b", "c"])
        assert result == "a"

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            numbered_select_one([])


class TestNumberedSelectMany:
    def test_all_keyword(self):
        with patch.object(console, "input", return_value="all"):
            result = numbered_select_many(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_space_separated(self):
        with patch.object(console, "input", return_value="1 3"):
            result = numbered_select_many(["a", "b", "c"])
        assert result == ["a", "c"]

    def test_duplicates_deduplicated(self):
        with patch.object(console, "input", return_value="2 2 1"):
            result = numbered_select_many(["a", "b", "c"])
        assert result == ["a", "b"]

    def test_out_of_range_reprompts(self):
        with patch.object(console, "input", side_effect=["0 4", "1 2"]):
            result = numbered_select_many(["a", "b", "c"])
        assert result == ["a", "b"]

    def test_non_numeric_reprompts(self):
        with patch.object(console, "input", side_effect=["abc", "2"]):
            result = numbered_select_many(["a", "b", "c"])
        assert result == ["b"]

    def test_b_raises_cancel(self):
        with patch.object(console, "input", return_value="b"):
            with pytest.raises(_MenuCancel):
                numbered_select_many(["a", "b"])

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            numbered_select_many([])


class TestPrintNumberedList:
    def test_pagination(self, capsys):
        items = [f"item_{i}" for i in range(25)]
        _print_numbered_list(items, page_size=20)
        # capsys won't capture rich console output, but at least ensure no crash
