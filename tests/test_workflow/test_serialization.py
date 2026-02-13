"""Tests for WorkflowSerializer (YAML round-trip)."""

from pathlib import Path

import pytest

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.serialization import WorkflowSerializer
from percell3.workflow.step import StepRegistry
from percell3.workflow.defaults import (
    ImportLif,
    Segment,
    Measure,
    ExportCsv,
    complete_analysis_workflow,
)
from tests.test_workflow.conftest import register_defaults


@pytest.fixture(autouse=True)
def _with_defaults():
    """Ensure built-in steps are registered for every test in this module."""
    register_defaults()


class TestWorkflowSerializer:
    def test_round_trip(self, tmp_path):
        dag = complete_analysis_workflow(
            source_path=Path("data/exp.lif"),
            channel_seg="DAPI",
            channels_measure=["GFP"],
        )

        yaml_path = tmp_path / "workflow.yaml"
        serializer = WorkflowSerializer()
        serializer.save(dag, yaml_path)

        loaded = serializer.load(yaml_path)
        assert loaded.execution_order() == dag.execution_order()

    def test_params_preserved(self, tmp_path):
        dag = WorkflowDAG()
        dag.add_step(ImportLif(), {"path": "/data/my_exp.lif", "condition": "ctrl"})

        yaml_path = tmp_path / "params.yaml"
        serializer = WorkflowSerializer()
        serializer.save(dag, yaml_path)

        loaded = serializer.load(yaml_path)
        assert loaded.get_params("import_lif") == {
            "path": "/data/my_exp.lif",
            "condition": "ctrl",
        }

    def test_edges_preserved(self, tmp_path):
        dag = WorkflowDAG()
        dag.add_step(ImportLif())
        dag.add_step(Segment())
        dag.connect("import_lif", "segment")

        yaml_path = tmp_path / "edges.yaml"
        serializer = WorkflowSerializer()
        serializer.save(dag, yaml_path)

        loaded = serializer.load(yaml_path)
        assert ("import_lif", "segment") in loaded.edges

    def test_load_missing_file_raises(self, tmp_path):
        serializer = WorkflowSerializer()
        with pytest.raises(FileNotFoundError):
            serializer.load(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml_raises(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("not_steps: true\n")

        serializer = WorkflowSerializer()
        with pytest.raises(ValueError, match="missing 'steps'"):
            serializer.load(bad_yaml)

    def test_load_unknown_step_raises(self, tmp_path):
        yaml_path = tmp_path / "unknown.yaml"
        yaml_path.write_text(
            "steps:\n  - name: nonexistent_step\n"
        )

        serializer = WorkflowSerializer()
        with pytest.raises(KeyError, match="nonexistent_step"):
            serializer.load(yaml_path)
