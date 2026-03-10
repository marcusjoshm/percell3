"""Tests for percell4.workflow.decapping_sensor — decapping sensor workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from percell4.workflow.decapping_sensor import create_decapping_workflow


class TestDecappingWorkflowCreation:
    """Test workflow factory and step structure."""

    def test_decapping_workflow_creation(self) -> None:
        """Factory creates a valid engine."""
        wf = create_decapping_workflow(
            signal_channels=["GFP", "RFP"],
            halo_channel="DAPI",
        )
        assert wf.step_count == 11

    def test_decapping_workflow_step_count(self) -> None:
        """Decapping workflow should have exactly 11 steps."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
        )
        assert wf.step_count == 11

    def test_decapping_workflow_step_names(self) -> None:
        """Verify all 11 step names."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
        )
        expected = [
            "segment",
            "measure_whole",
            "threshold_round_1",
            "threshold_round_2",
            "threshold_round_3",
            "split_halo",
            "bg_subtraction",
            "measure_bg_subtracted",
            "nan_zero",
            "measure_nan_safe",
            "export",
        ]
        assert wf.step_names == expected

    def test_decapping_workflow_dependencies(self) -> None:
        """Verify the DAG dependency structure."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
        )

        assert wf.get_step("segment").depends_on == []
        assert wf.get_step("measure_whole").depends_on == ["segment"]
        assert wf.get_step("threshold_round_1").depends_on == ["measure_whole"]
        assert wf.get_step("threshold_round_2").depends_on == ["threshold_round_1"]
        assert wf.get_step("threshold_round_3").depends_on == ["threshold_round_2"]
        assert wf.get_step("split_halo").depends_on == ["threshold_round_3"]
        assert wf.get_step("bg_subtraction").depends_on == ["split_halo"]
        assert wf.get_step("measure_bg_subtracted").depends_on == ["bg_subtraction"]
        assert wf.get_step("nan_zero").depends_on == ["measure_bg_subtracted"]
        assert wf.get_step("measure_nan_safe").depends_on == ["nan_zero"]
        assert wf.get_step("export").depends_on == ["measure_nan_safe"]

    def test_decapping_workflow_topological_order(self) -> None:
        """Topological order should match the linear chain."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
        )
        order = wf._topological_order()
        expected = [
            "segment",
            "measure_whole",
            "threshold_round_1",
            "threshold_round_2",
            "threshold_round_3",
            "split_halo",
            "bg_subtraction",
            "measure_bg_subtracted",
            "nan_zero",
            "measure_nan_safe",
            "export",
        ]
        assert order == expected

    def test_decapping_workflow_custom_rounds(self) -> None:
        """Non-default number of rounds changes step count."""
        wf_2 = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
            rounds=2,
        )
        # 2 segment/measure + 2 threshold rounds + 6 post-threshold = 10
        assert wf_2.step_count == 10

        wf_5 = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
            rounds=5,
        )
        # 2 + 5 + 6 = 13
        assert wf_5.step_count == 13

    def test_decapping_workflow_export_skip_when_no_path(self) -> None:
        """Export step has skip_if when no path is provided."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
        )
        export_step = wf.get_step("export")
        assert export_step.skip_if is not None

    def test_decapping_workflow_with_export_path(self, tmp_path: Path) -> None:
        """Export step config includes the export path."""
        out = tmp_path / "decapping_results.csv"
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
            export_path=out,
        )
        export_step = wf.get_step("export")
        assert export_step.config["export_path"] == out

    def test_decapping_workflow_with_bg_channel(self) -> None:
        """BG channel is passed to the bg_subtraction step config."""
        wf = create_decapping_workflow(
            signal_channels=["GFP"],
            halo_channel="DAPI",
            bg_channel="RFP",
        )
        bg_step = wf.get_step("bg_subtraction")
        assert bg_step.config["bg_channel"] == "RFP"

    def test_decapping_workflow_multiple_signal_channels(self) -> None:
        """Multiple signal channels are passed to the segment step."""
        wf = create_decapping_workflow(
            signal_channels=["GFP", "RFP", "Cy5"],
            halo_channel="DAPI",
        )
        seg_step = wf.get_step("segment")
        assert seg_step.config["signal_channels"] == ["GFP", "RFP", "Cy5"]
