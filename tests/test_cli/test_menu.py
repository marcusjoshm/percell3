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
    _particle_workflow,
    _print_numbered_list,
    _show_header,
    _threshold_fov,
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
        # Main menu shows categories; send 'q' to quit immediately
        result = _invoke_menu(runner, input="q\n")
        assert result.exit_code == 0
        assert "PerCell 3" in result.output
        assert "Setup" in result.output

    def test_menu_shows_categories(self, runner: CliRunner):
        result = _invoke_menu(runner, input="q\n")
        assert "Setup" in result.output
        assert "Import" in result.output
        assert "Segment" in result.output
        assert "Analyze" in result.output
        assert "View" in result.output
        assert "Data" in result.output
        assert "Workflows" in result.output
        assert "Plugins" in result.output

    def test_plugins_menu_requires_experiment(self, runner: CliRunner):
        # Selecting Plugins (8) without an experiment should show error
        result = _invoke_menu(runner, input="8\n\nq\n")
        assert "No experiment" in result.output

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
        # Main→Setup(1)→Create(1)→path→name→desc→Enter gate→Back(3)→quit
        result = _invoke_menu(
            runner,
            input=f"1\n1\n{exp_path}\nMyExp\nA test\n\n3\nq\n",
        )
        assert result.exit_code == 0
        assert "Created experiment" in result.output
        assert exp_path.exists()


class TestMenuSelectExperiment:
    def test_select_experiment_via_menu(
        self, runner: CliRunner, experiment_path: Path,
    ):
        # Main→Setup(1)→Select(2)→path→Enter gate→Back(3)→quit
        result = _invoke_menu(
            runner,
            input=f"1\n2\n{experiment_path}\n\n3\nq\n",
        )
        assert result.exit_code == 0
        assert "Opened experiment" in result.output

    def test_select_nonexistent_path(self, runner: CliRunner):
        # Main→Setup(1)→Select(2)→path→Enter gate→Back(3)→quit
        result = _invoke_menu(
            runner,
            input="1\n2\n/nonexistent/path.percell\n\n3\nq\n",
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

    def test_h_from_data_query_returns_to_home(self, runner: CliRunner, experiment_path: Path):
        # Main→Setup(1)→Select(2)→path→Enter→Back(3)
        # →Data(6)→Query(1)→press h→back at main→quit
        result = _invoke_menu(
            runner,
            input=f"1\n2\n{experiment_path}\n\n3\n6\n1\nh\nq\n",
        )
        assert result.exit_code == 0
        # Should see PerCell 3 multiple times (main menu redraws)
        assert result.output.count("PerCell 3") >= 2

    def test_b_from_sub_menu_returns_to_parent(self, runner: CliRunner):
        # Main→Setup(1)→Back(3)→quit
        result = _invoke_menu(runner, input="1\n3\nq\n")
        assert result.exit_code == 0

    def test_b_key_from_sub_menu_returns_to_parent(self, runner: CliRunner):
        # Main→Setup(1)→press b→quit
        result = _invoke_menu(runner, input="1\nb\nq\n")
        assert result.exit_code == 0


class TestSubMenuNavigation:
    """Test two-tier navigation structure."""

    def test_setup_sub_menu(self, runner: CliRunner):
        # Main→Setup(1) should show Create/Select/Back, then Back(3)→quit
        result = _invoke_menu(runner, input="1\n3\nq\n")
        assert result.exit_code == 0
        assert "Create experiment" in result.output
        assert "Select experiment" in result.output

    def test_data_sub_menu(self, runner: CliRunner):
        # Main→Data(6) should show Query/Edit/Export/Back, then Back(4)→quit
        result = _invoke_menu(runner, input="6\n4\nq\n")
        assert result.exit_code == 0
        assert "Query experiment" in result.output
        assert "Edit experiment" in result.output
        assert "Export to CSV" in result.output

    def test_analyze_sub_menu(self, runner: CliRunner):
        # Main→Analyze(4) should show Measure/Threshold/Back, then Back(3)→quit
        result = _invoke_menu(runner, input="4\n3\nq\n")
        assert result.exit_code == 0
        assert "Measure channels" in result.output
        assert "Apply threshold" in result.output


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


class TestWorkflowMenu:
    def test_workflows_menu_shows_particle_analysis(self, runner: CliRunner):
        """Workflows sub-menu should list 'Particle analysis' as an enabled item."""
        # Main menu → 7 (Workflows) → b (back) → q (quit)
        result = _invoke_menu(runner, input="7\nb\nq\n")
        assert result.exit_code == 0
        assert "Particle analysis" in result.output

    def test_workflow_requires_experiment(self, runner: CliRunner):
        """Workflow should prompt for experiment when none is loaded."""
        # Main menu → 7 (Workflows) → 1 (Particle analysis) → expect experiment prompt
        # Since no experiment is loaded and we don't provide a path, it should cancel
        result = _invoke_menu(runner, input="7\n1\nb\nb\nq\n")
        assert result.exit_code == 0
        assert "No experiment selected" in result.output

    def test_workflow_no_channels_early_exit(self, runner: CliRunner, experiment: ExperimentStore):
        """Workflow should exit early with message when no channels exist."""
        exp_path = str(experiment.path)
        # Main menu → 7 (Workflows) → 1 → select experiment path → expect "No channels"
        # Setup → Select → path → Enter → back to main → Workflows → Particle analysis
        result = _invoke_menu(
            runner,
            input=f"1\n2\n{exp_path}\n\nb\n7\n1\n\nb\nq\n",
        )
        assert "No channels found" in result.output

    def test_workflow_no_fovs_early_exit(
        self, runner: CliRunner, experiment: ExperimentStore,
    ):
        """Workflow should exit early when experiment has channels but no FOVs."""
        experiment.add_channel("DAPI")
        exp_path = str(experiment.path)
        result = _invoke_menu(
            runner,
            input=f"1\n2\n{exp_path}\n\nb\n7\n1\n\nb\nq\n",
        )
        assert "No FOVs found" in result.output


class TestThresholdFov:
    def test_threshold_fov_skips_on_no_measurements(
        self, experiment_with_data: ExperimentStore,
    ):
        """_threshold_fov returns (0, 0) when grouping metric has no measurements."""
        store = experiment_with_data
        fovs = store.get_fovs()
        fov_info = fovs[0]
        # No cells exist yet, so CellGrouper should raise ValueError
        processed, particles = _threshold_fov(
            store, fov_info, "GFP", "GFP", "mean_intensity",
        )
        assert processed == 0
        assert particles == 0
