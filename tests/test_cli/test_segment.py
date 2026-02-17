"""Tests for percell3 segment CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from click.testing import CliRunner

from percell3.cli.main import cli
from percell3.core import ExperimentStore
from percell3.segment.base_segmenter import BaseSegmenter, SegmentationParams


class _MockSegmenter(BaseSegmenter):
    """A mock segmenter for CLI testing — returns 2 synthetic cells."""

    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        labels = np.zeros(image.shape[:2], dtype=np.int32)
        h, w = labels.shape
        labels[h // 8 : h // 4, w // 8 : w // 4] = 1
        labels[h * 3 // 4 : h * 7 // 8, w * 3 // 4 : w * 7 // 8] = 2
        return labels


class TestSegmentCommand:
    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["segment", "--help"])
        assert result.exit_code == 0
        assert "Run cell segmentation" in result.output
        assert "--channel" in result.output
        assert "--model" in result.output
        assert "--diameter" in result.output

    def test_missing_experiment(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["segment", "-e", "/nonexistent", "-c", "DAPI"])
        assert result.exit_code != 0

    def test_missing_channel_option(self, runner: CliRunner, tmp_path: Path) -> None:
        """--channel is required."""
        store = ExperimentStore.create(tmp_path / "test.percell")
        store.close()
        result = runner.invoke(cli, ["segment", "-e", str(tmp_path / "test.percell")])
        assert result.exit_code != 0
        assert "channel" in result.output.lower() or "Missing" in result.output

    def test_segment_success(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """Segment with mocked backend: should report cells found."""
        store = experiment_with_data
        exp_path = str(store.path)

        with patch(
            "percell3.segment.cellpose_adapter.CellposeAdapter",
            return_value=_MockSegmenter(),
        ):
            result = runner.invoke(cli, [
                "segment", "-e", exp_path, "-c", "DAPI", "--model", "cyto3",
            ])

        assert result.exit_code == 0, result.output
        assert "Segmentation complete" in result.output
        assert "FOVs processed: 1" in result.output
        assert "Total cells found: 2" in result.output

    def test_segment_with_diameter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """--diameter option should be accepted."""
        store = experiment_with_data
        exp_path = str(store.path)

        with patch(
            "percell3.segment.cellpose_adapter.CellposeAdapter",
            return_value=_MockSegmenter(),
        ):
            result = runner.invoke(cli, [
                "segment", "-e", exp_path, "-c", "DAPI", "--diameter", "30.0",
            ])

        assert result.exit_code == 0, result.output
        assert "Segmentation complete" in result.output

    def test_segment_invalid_channel(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """Non-existent channel should error gracefully."""
        store = experiment_with_data
        exp_path = str(store.path)

        result = runner.invoke(cli, [
            "segment", "-e", exp_path, "-c", "nonexistent",
        ])

        assert result.exit_code != 0
        assert "Error" in result.output

    def test_segment_with_condition_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """--condition filter should be passed through."""
        store = experiment_with_data
        exp_path = str(store.path)

        with patch(
            "percell3.segment.cellpose_adapter.CellposeAdapter",
            return_value=_MockSegmenter(),
        ):
            result = runner.invoke(cli, [
                "segment", "-e", exp_path, "-c", "DAPI",
                "--condition", "control",
            ])

        assert result.exit_code == 0, result.output
        assert "Segmentation complete" in result.output

    def test_segment_with_fov_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """--fovs filter should be parsed as comma-separated."""
        store = experiment_with_data
        exp_path = str(store.path)

        with patch(
            "percell3.segment.cellpose_adapter.CellposeAdapter",
            return_value=_MockSegmenter(),
        ):
            result = runner.invoke(cli, [
                "segment", "-e", exp_path, "-c", "DAPI",
                "--fovs", "fov1",
            ])

        assert result.exit_code == 0, result.output
        assert "FOVs processed: 1" in result.output

    def test_segment_nonexistent_fov_filter(
        self, runner: CliRunner, experiment_with_data: ExperimentStore
    ) -> None:
        """Filtering to a non-existent FOV should error."""
        store = experiment_with_data
        exp_path = str(store.path)

        with patch(
            "percell3.segment.cellpose_adapter.CellposeAdapter",
            return_value=_MockSegmenter(),
        ):
            result = runner.invoke(cli, [
                "segment", "-e", exp_path, "-c", "DAPI",
                "--fovs", "nonexistent",
            ])

        assert result.exit_code != 0
        assert "Error" in result.output

    def test_help_shows_segment(self, runner: CliRunner) -> None:
        """Top-level help should list the segment command."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "segment" in result.output
