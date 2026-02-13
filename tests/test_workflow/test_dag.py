"""Tests for WorkflowDAG."""

import pytest

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.step import StepInput, StepOutput
from tests.test_workflow.conftest import MockStep, make_mock_step


class TestAddStep:
    def test_add_step(self):
        dag = WorkflowDAG()
        step = make_mock_step("import", outputs=["images"])
        dag.add_step(step)
        assert "import" in dag.step_names

    def test_add_step_with_params(self):
        dag = WorkflowDAG()
        step = make_mock_step("import")
        dag.add_step(step, {"path": "/data/exp.lif"})
        assert dag.get_params("import") == {"path": "/data/exp.lif"}

    def test_add_duplicate_raises(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("import"))
        with pytest.raises(ValueError, match="already exists"):
            dag.add_step(make_mock_step("import"))


class TestConnect:
    def test_explicit_connect(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))
        dag.connect("a", "b")
        assert ("a", "b") in dag.edges

    def test_connect_unknown_step_raises(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        with pytest.raises(KeyError):
            dag.connect("a", "nonexistent")

    def test_connect_self_raises(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        with pytest.raises(ValueError, match="itself"):
            dag.connect("a", "a")

    def test_duplicate_edge_ignored(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))
        dag.connect("a", "b")
        dag.connect("a", "b")  # no error, no duplicate
        assert dag.edges.count(("a", "b")) == 1


class TestAutoConnect:
    def test_auto_connect_linear(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("import", outputs=["images"]))
        dag.add_step(make_mock_step("segment", inputs=["images"], outputs=["labels"]))
        dag.add_step(make_mock_step("measure", inputs=["labels"], outputs=["measurements"]))
        dag.auto_connect()

        assert ("import", "segment") in dag.edges
        assert ("segment", "measure") in dag.edges

    def test_auto_connect_fan_out(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("import", outputs=["images"]))
        dag.add_step(make_mock_step("segment", inputs=["images"]))
        dag.add_step(make_mock_step("threshold", inputs=["images"]))
        dag.auto_connect()

        assert ("import", "segment") in dag.edges
        assert ("import", "threshold") in dag.edges

    def test_auto_connect_no_match(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a", outputs=["x"]))
        dag.add_step(make_mock_step("b", inputs=["y"]))
        dag.auto_connect()
        assert len(dag.edges) == 0


class TestValidate:
    def test_valid_dag(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a", outputs=["x"]))
        dag.add_step(make_mock_step("b", inputs=["x"], outputs=["y"]))
        dag.add_step(make_mock_step("c", inputs=["y"]))
        dag.auto_connect()
        assert dag.validate() == []

    def test_dag_rejects_cycle(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a", inputs=["z"], outputs=["x"]))
        dag.add_step(make_mock_step("b", inputs=["x"], outputs=["y"]))
        dag.add_step(make_mock_step("c", inputs=["y"], outputs=["z"]))
        dag.auto_connect()

        errors = dag.validate()
        assert any("cycle" in e.lower() for e in errors)

    def test_orphaned_step_error(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a", inputs=["nonexistent_data"]))
        errors = dag.validate()
        assert any("unsatisfied" in e.lower() for e in errors)

    def test_step_with_optional_input_no_error(self):
        dag = WorkflowDAG()
        step = MockStep(
            step_name="flexible",
            step_inputs=[StepInput("maybe", required=False)],
        )
        dag.add_step(step)
        assert dag.validate() == []


class TestExecutionOrder:
    def test_linear_order(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("c", inputs=["y"]))
        dag.add_step(make_mock_step("a", outputs=["x"]))
        dag.add_step(make_mock_step("b", inputs=["x"], outputs=["y"]))
        dag.auto_connect()

        order = dag.execution_order()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_execution_order_spec_example(self):
        """Test from acceptance-tests.md."""
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("measure", inputs=["labels"], outputs=["measurements"]))
        dag.add_step(make_mock_step("import", outputs=["images"]))
        dag.add_step(make_mock_step("segment", inputs=["images"], outputs=["labels"]))
        dag.auto_connect()

        order = dag.execution_order()
        assert order.index("import") < order.index("segment")
        assert order.index("segment") < order.index("measure")

    def test_cycle_raises_on_execution_order(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))
        dag.connect("a", "b")
        dag.connect("b", "a")

        with pytest.raises(ValueError, match="cycle"):
            dag.execution_order()

    def test_independent_steps_all_present(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("x"))
        dag.add_step(make_mock_step("y"))
        dag.add_step(make_mock_step("z"))
        order = dag.execution_order()
        assert set(order) == {"x", "y", "z"}


class TestGetStep:
    def test_get_step(self):
        dag = WorkflowDAG()
        step = make_mock_step("my_step")
        dag.add_step(step)
        assert dag.get_step("my_step") is step

    def test_get_unknown_step_raises(self):
        dag = WorkflowDAG()
        with pytest.raises(KeyError):
            dag.get_step("missing")


class TestGetPredecessors:
    def test_predecessors(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))
        dag.add_step(make_mock_step("c"))
        dag.connect("a", "c")
        dag.connect("b", "c")
        assert set(dag.get_predecessors("c")) == {"a", "b"}

    def test_no_predecessors(self):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("root"))
        assert dag.get_predecessors("root") == []
