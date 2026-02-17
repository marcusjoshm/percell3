"""Tests for percell3 view CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore


class TestViewCommand:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["view", "--help"])
        assert result.exit_code == 0
        assert "Launch napari" in result.output
        assert "--fov" in result.output
        assert "--experiment" in result.output

    def test_top_level_help_lists_view(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "view" in result.output

    def test_missing_experiment(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["view", "-e", "/nonexistent", "-f", "fov1"])
        assert result.exit_code != 0

    def test_missing_fov_option(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """--fov is required."""
        exp_path = str(experiment_with_data.path)
        result = runner.invoke(cli, ["view", "-e", exp_path])
        assert result.exit_code != 0
        assert "fov" in result.output.lower() or "Missing" in result.output

    def test_napari_not_installed_shows_message(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """When napari is missing, show install instructions."""
        exp_path = str(experiment_with_data.path)

        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", False):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "fov1",
            ])

        assert result.exit_code != 0
        assert "napari could not be loaded" in result.output
        assert "pip install" in result.output

    def test_auto_detect_single_condition(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """When only one condition exists, auto-detect it."""
        exp_path = str(experiment_with_data.path)

        mock_launch = MagicMock(return_value=None)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "fov1",
            ])

        assert result.exit_code == 0, result.output
        assert "No changes detected" in result.output
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == "fov1"
        assert call_args[0][2] == "control"  # auto-detected

    def test_view_with_explicit_condition(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """Explicit --condition should be passed through."""
        exp_path = str(experiment_with_data.path)

        mock_launch = MagicMock(return_value=None)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "fov1",
                "--condition", "control",
            ])

        assert result.exit_code == 0, result.output
        call_args = mock_launch.call_args
        assert call_args[0][2] == "control"

    def test_view_reports_saved_run_id(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """When labels are edited, report the run_id."""
        exp_path = str(experiment_with_data.path)

        mock_launch = MagicMock(return_value=42)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "fov1",
            ])

        assert result.exit_code == 0, result.output
        assert "Labels saved" in result.output
        assert "run_id=42" in result.output

    def test_view_with_channels_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """--channels should be split and passed through."""
        exp_path = str(experiment_with_data.path)

        mock_launch = MagicMock(return_value=None)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "fov1",
                "--channels", "DAPI,GFP",
            ])

        assert result.exit_code == 0, result.output
        call_args = mock_launch.call_args
        assert call_args[0][3] == ["DAPI", "GFP"]

    def test_multiple_conditions_without_flag_errors(
        self, runner: CliRunner, tmp_path: Path,
    ) -> None:
        """Multiple conditions without --condition should error with helpful message."""
        store = ExperimentStore.create(tmp_path / "multi.percell")
        store.add_channel("DAPI")
        store.add_condition("control")
        store.add_condition("treated")
        store.add_fov("r1", "control", width=64, height=64)
        store.add_fov("r2", "treated", width=64, height=64)
        store.write_image("r1", "control", "DAPI", np.zeros((64, 64), dtype=np.uint16))
        store.write_image("r2", "treated", "DAPI", np.zeros((64, 64), dtype=np.uint16))
        store.close()

        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True):
            result = runner.invoke(cli, [
                "view", "-e", str(tmp_path / "multi.percell"), "-f", "r1",
            ])

        assert result.exit_code != 0
        assert "Multiple conditions" in result.output
