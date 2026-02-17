"""Tests for built-in steps and preset workflows."""

from pathlib import Path

import pytest

from percell3.workflow.step import StepRegistry
from percell3.workflow.defaults import (
    Classify,
    ExportCsv,
    ImportLif,
    ImportTiff,
    Measure,
    RunPlugin,
    Segment,
    Threshold,
    complete_analysis_workflow,
    measure_only_workflow,
)
from tests.test_workflow.conftest import register_defaults


@pytest.fixture(autouse=True)
def _with_defaults():
    """Ensure built-in steps are registered for every test in this module."""
    register_defaults()


class TestBuiltInSteps:
    def test_all_steps_registered(self):
        expected = {
            "import_lif", "import_tiff", "segment", "measure",
            "threshold", "classify", "run_plugin", "export_csv",
        }
        assert set(StepRegistry.list_steps()) == expected

    def test_import_lif_metadata(self):
        step = ImportLif()
        assert step.name == "import_lif"
        assert len(step.inputs) == 0
        assert {o.name for o in step.outputs} == {"images", "channels", "regions"}
        assert any(p.name == "path" for p in step.parameters)

    def test_import_tiff_metadata(self):
        step = ImportTiff()
        assert step.name == "import_tiff"
        assert len(step.inputs) == 0

    def test_segment_metadata(self):
        step = Segment()
        assert step.name == "segment"
        assert {i.name for i in step.inputs} == {"images", "channels"}
        assert {o.name for o in step.outputs} == {"labels", "cells"}
        model_param = next(p for p in step.parameters if p.name == "model")
        assert "cpsam" in model_param.choices

    def test_measure_metadata(self):
        step = Measure()
        assert step.name == "measure"
        assert {i.name for i in step.inputs} == {"images", "labels", "cells"}
        assert step.outputs[0].name == "measurements"

    def test_export_csv_metadata(self):
        step = ExportCsv()
        assert step.name == "export_csv"
        assert step.inputs[0].name == "measurements"
        assert len(step.outputs) == 0

    def test_threshold_metadata(self):
        step = Threshold()
        assert step.name == "threshold"
        assert step.inputs[0].name == "images"
        assert step.outputs[0].name == "masks"

    def test_classify_metadata(self):
        step = Classify()
        assert {i.name for i in step.inputs} == {"labels", "masks"}

    def test_run_plugin_metadata(self):
        step = RunPlugin()
        assert step.name == "run_plugin"
        assert step.inputs[0].required is False


class TestPresetWorkflows:
    def test_complete_analysis_lif(self):
        dag = complete_analysis_workflow(
            source_path=Path("data/exp.lif"),
            channel_seg="DAPI",
            channels_measure=["GFP", "RFP"],
        )
        order = dag.execution_order()
        assert order[0] == "import_lif"
        assert order.index("segment") < order.index("measure")
        assert order[-1] == "export_csv"

    def test_complete_analysis_tiff(self):
        dag = complete_analysis_workflow(
            source_path=Path("data/tiffs/"),
            source_format="tiff",
            channel_seg="DAPI",
        )
        order = dag.execution_order()
        assert order[0] == "import_tiff"

    def test_complete_analysis_valid(self):
        dag = complete_analysis_workflow(
            source_path=Path("data/exp.lif"),
            channel_seg="DAPI",
        )
        errors = dag.validate()
        assert errors == []

    def test_measure_only_workflow(self):
        dag = measure_only_workflow(channels=["GFP", "Cy5"])
        order = dag.execution_order()
        assert "measure" in order
        assert "export_csv" in order
        assert order.index("measure") < order.index("export_csv")

    def test_measure_only_params(self):
        dag = measure_only_workflow(channels=["GFP", "Cy5"])
        params = dag.get_params("measure")
        assert params["channels"] == "GFP,Cy5"

    def test_complete_workflow_has_4_steps(self):
        dag = complete_analysis_workflow(
            source_path=Path("data/exp.lif"),
            channel_seg="DAPI",
        )
        assert len(dag.step_names) == 4
