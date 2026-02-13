"""Tests for WorkflowEngine."""

import pytest

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.engine import StepStatus, WorkflowEngine, WorkflowResult
from percell3.workflow.state import WorkflowState
from percell3.workflow.step import StepResult
from tests.test_workflow.conftest import FailingStep, MockStep, make_mock_step


class TestEngineRun:
    def test_run_all_steps(self, mock_store):
        dag = WorkflowDAG()
        step_a = make_mock_step("a", outputs=["x"])
        step_b = make_mock_step("b", inputs=["x"], outputs=["y"])
        step_c = make_mock_step("c", inputs=["y"])
        dag.add_step(step_a)
        dag.add_step(step_b)
        dag.add_step(step_c)
        dag.auto_connect()

        engine = WorkflowEngine(mock_store, dag)
        result = engine.run()

        assert result.steps_completed == 3
        assert result.steps_failed == 0
        assert result.steps_skipped == 0
        assert len(step_a.execute_calls) == 1
        assert len(step_b.execute_calls) == 1
        assert len(step_c.execute_calls) == 1

    def test_execution_order_respected(self, mock_store):
        """Steps execute in topological order."""
        dag = WorkflowDAG()
        execution_order: list[str] = []

        class TrackingStep(MockStep):
            def execute(self, store, params, progress_callback=None):
                execution_order.append(self.name)
                return StepResult(status="completed")

        dag.add_step(TrackingStep(step_name="c", step_inputs=[make_mock_step("_", inputs=["y"]).inputs[0]]))
        dag.add_step(TrackingStep(step_name="a", step_outputs=[make_mock_step("_", outputs=["x"]).outputs[0]]))
        dag.add_step(TrackingStep(step_name="b",
                                   step_inputs=[make_mock_step("_", inputs=["x"]).inputs[0]],
                                   step_outputs=[make_mock_step("_", outputs=["y"]).outputs[0]]))
        dag.auto_connect()

        engine = WorkflowEngine(mock_store, dag)
        engine.run()

        assert execution_order.index("a") < execution_order.index("b")
        assert execution_order.index("b") < execution_order.index("c")

    def test_skip_completed_steps(self, mock_store):
        dag = WorkflowDAG()
        step_a = make_mock_step("a")
        step_b = make_mock_step("b")
        dag.add_step(step_a)
        dag.add_step(step_b)

        engine = WorkflowEngine(mock_store, dag)

        # First run: all complete
        result1 = engine.run()
        assert result1.steps_completed == 2

        # Second run: should skip both
        step_a.execute_calls.clear()
        step_b.execute_calls.clear()
        result2 = engine.run()
        assert result2.steps_skipped == 2
        assert result2.steps_completed == 0
        assert len(step_a.execute_calls) == 0

    def test_stop_on_failure(self, mock_store):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a", outputs=["x"]))
        dag.add_step(FailingStep(step_name="b"))
        step_c = make_mock_step("c")
        dag.add_step(step_c)
        dag.connect("a", "b")
        dag.connect("b", "c")

        engine = WorkflowEngine(mock_store, dag)
        result = engine.run()

        assert result.steps_completed == 1  # a
        assert result.steps_failed == 1     # b
        assert result.steps_skipped == 1    # c (predecessor failed)
        assert len(step_c.execute_calls) == 0

    def test_force_rerun(self, mock_store):
        dag = WorkflowDAG()
        step_a = make_mock_step("a")
        dag.add_step(step_a)

        engine = WorkflowEngine(mock_store, dag)

        # First run
        engine.run()
        assert len(step_a.execute_calls) == 1

        # Force re-run
        result = engine.run(force=True)
        assert result.steps_completed == 1
        assert result.steps_skipped == 0
        assert len(step_a.execute_calls) == 2

    def test_invalid_dag_raises(self, mock_store):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))
        dag.connect("a", "b")
        dag.connect("b", "a")

        engine = WorkflowEngine(mock_store, dag)
        with pytest.raises(ValueError, match="validation failed"):
            engine.run()

    def test_progress_callback(self, mock_store):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("step1"))
        dag.add_step(make_mock_step("step2"))

        events: list[tuple[str, str]] = []
        engine = WorkflowEngine(mock_store, dag)
        engine.run(progress_callback=lambda name, msg: events.append((name, msg)))

        assert len(events) == 2
        assert all(msg == "completed" for _, msg in events)

    def test_exception_in_step_becomes_failure(self, mock_store):
        class ExplodingStep(MockStep):
            def execute(self, store, params, progress_callback=None):
                raise RuntimeError("boom")

        dag = WorkflowDAG()
        dag.add_step(ExplodingStep(step_name="bomb"))

        engine = WorkflowEngine(mock_store, dag)
        result = engine.run()

        assert result.steps_failed == 1
        assert "boom" in result.step_results["bomb"].message


class TestRunStep:
    def test_run_single_step(self, mock_store):
        dag = WorkflowDAG()
        step = make_mock_step("only")
        dag.add_step(step)

        engine = WorkflowEngine(mock_store, dag)
        result = engine.run_step("only")
        assert result.status == "completed"
        assert len(step.execute_calls) == 1

    def test_run_step_skips_if_completed(self, mock_store):
        dag = WorkflowDAG()
        step = make_mock_step("once")
        dag.add_step(step)

        engine = WorkflowEngine(mock_store, dag)
        engine.run_step("once")
        result = engine.run_step("once")
        assert result.status == "skipped"
        assert len(step.execute_calls) == 1

    def test_run_step_force(self, mock_store):
        dag = WorkflowDAG()
        step = make_mock_step("redo")
        dag.add_step(step)

        engine = WorkflowEngine(mock_store, dag)
        engine.run_step("redo")
        result = engine.run_step("redo", force=True)
        assert result.status == "completed"
        assert len(step.execute_calls) == 2


class TestStatus:
    def test_all_pending(self, mock_store):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("a"))
        dag.add_step(make_mock_step("b"))

        engine = WorkflowEngine(mock_store, dag)
        status = engine.status()
        assert status == {"a": StepStatus.PENDING, "b": StepStatus.PENDING}

    def test_mixed_status(self, mock_store):
        dag = WorkflowDAG()
        dag.add_step(make_mock_step("ok", outputs=["x"]))
        dag.add_step(FailingStep(step_name="bad"))
        dag.add_step(make_mock_step("waiting"))
        dag.connect("ok", "bad")
        dag.connect("bad", "waiting")

        engine = WorkflowEngine(mock_store, dag)
        engine.run()

        status = engine.status()
        assert status["ok"] == StepStatus.COMPLETED
        assert status["bad"] == StepStatus.FAILED
        # "waiting" was skipped at runtime, but state records nothing → PENDING
        assert status["waiting"] == StepStatus.PENDING
