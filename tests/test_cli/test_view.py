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
        fov = experiment_with_data.get_fovs()[0]

        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", False):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", fov.display_name,
            ])

        assert result.exit_code != 0
        assert "napari could not be loaded" in result.output
        assert "pip install" in result.output

    def test_view_launches_viewer(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """View command finds FOV by display_name and calls launch_viewer."""
        exp_path = str(experiment_with_data.path)
        fov = experiment_with_data.get_fovs()[0]

        mock_launch = MagicMock(return_value=None)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", fov.display_name,
            ])

        assert result.exit_code == 0, result.output
        assert "No changes detected" in result.output
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args
        assert call_args[0][1] == fov.id  # fov_id
        assert call_args[0][2] is None  # no channel filter

    def test_view_reports_saved_run_id(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """When labels are edited, report the run_id."""
        exp_path = str(experiment_with_data.path)
        fov = experiment_with_data.get_fovs()[0]

        mock_launch = MagicMock(return_value=42)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", fov.display_name,
            ])

        assert result.exit_code == 0, result.output
        assert "Labels saved" in result.output
        assert "run_id=42" in result.output

    def test_view_with_channels_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """--channels should be split and passed through."""
        exp_path = str(experiment_with_data.path)
        fov = experiment_with_data.get_fovs()[0]

        mock_launch = MagicMock(return_value=None)
        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True), \
             patch("percell3.segment.viewer.launch_viewer", mock_launch):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", fov.display_name,
                "--channels", "DAPI,GFP",
            ])

        assert result.exit_code == 0, result.output
        call_args = mock_launch.call_args
        assert call_args[0][2] == ["DAPI", "GFP"]

    def test_unknown_fov_errors(
        self, runner: CliRunner, experiment_with_data: ExperimentStore,
    ) -> None:
        """Non-existent FOV display_name should error with helpful message."""
        exp_path = str(experiment_with_data.path)

        with patch("percell3.segment.viewer.NAPARI_AVAILABLE", True):
            result = runner.invoke(cli, [
                "view", "-e", exp_path, "-f", "nonexistent_fov",
            ])

        assert result.exit_code != 0
        assert "No FOV named" in result.output
