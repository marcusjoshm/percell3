"""Tests for percell4.workflow.engine — DAG validation and execution."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from percell4.workflow.engine import WorkflowEngine, WorkflowStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_handler(store: Any, context: dict[str, Any], **kwargs: Any) -> str:
    """A trivial handler that records its call in context."""
    context.setdefault("call_order", []).append(kwargs.get("step_id", "?"))
    return "ok"


def _failing_handler(store: Any, context: dict[str, Any], **kwargs: Any) -> None:
    """A handler that always raises."""
    raise RuntimeError("deliberate failure")


# ---------------------------------------------------------------------------
# DAG validation tests
# ---------------------------------------------------------------------------


class TestDagValidation:
    """Validate that the engine detects invalid DAGs at construction time."""

    def test_dag_validation_detects_cycle(self) -> None:
        """Mutually-dependent steps should be rejected as a cycle."""
        steps = [
            WorkflowStep(
                name="a",
                description="step A",
                handler=_noop_handler,
                depends_on=["b"],
            ),
            WorkflowStep(
                name="b",
                description="step B",
                handler=_noop_handler,
                depends_on=["a"],
            ),
        ]
        with pytest.raises(ValueError, match="cycle"):
            WorkflowEngine(steps)

    def test_dag_validation_detects_self_cycle(self) -> None:
        """A step that depends on itself should be rejected."""
        steps = [
            WorkflowStep(
                name="a",
                description="step A",
                handler=_noop_handler,
                depends_on=["a"],
            ),
        ]
        with pytest.raises(ValueError, match="cycle"):
            WorkflowEngine(steps)

    def test_dag_validation_missing_dependency(self) -> None:
        """Referencing a non-existent step should raise."""
        steps = [
            WorkflowStep(
                name="a",
                description="step A",
                handler=_noop_handler,
                depends_on=["nonexistent"],
            ),
        ]
        with pytest.raises(ValueError, match="does not exist"):
            WorkflowEngine(steps)

    def test_dag_validation_accepts_valid_dag(self) -> None:
        """A well-formed linear DAG should be accepted."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["b"],
            ),
        ]
        engine = WorkflowEngine(steps)
        assert engine.step_count == 3

    def test_dag_validation_accepts_diamond(self) -> None:
        """A diamond dependency graph should be accepted."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="d", description="D", handler=_noop_handler,
                depends_on=["b", "c"],
            ),
        ]
        engine = WorkflowEngine(steps)
        assert engine.step_count == 4


class TestTopologicalOrder:
    """Verify that steps are ordered correctly."""

    def test_topological_order_linear(self) -> None:
        """Linear chain a -> b -> c should produce [a, b, c]."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["b"],
            ),
        ]
        engine = WorkflowEngine(steps)
        order = engine._topological_order()
        assert order == ["a", "b", "c"]

    def test_topological_order_diamond(self) -> None:
        """Diamond: a -> {b, c} -> d.  b and c can be in either order."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["a"],
            ),
            WorkflowStep(
                name="d", description="D", handler=_noop_handler,
                depends_on=["b", "c"],
            ),
        ]
        engine = WorkflowEngine(steps)
        order = engine._topological_order()
        assert order[0] == "a"
        assert order[-1] == "d"
        assert set(order[1:3]) == {"b", "c"}

    def test_topological_order_independent(self) -> None:
        """Independent steps (no edges) can appear in any order."""
        steps = [
            WorkflowStep(name="x", description="X", handler=_noop_handler),
            WorkflowStep(name="y", description="Y", handler=_noop_handler),
            WorkflowStep(name="z", description="Z", handler=_noop_handler),
        ]
        engine = WorkflowEngine(steps)
        order = engine._topological_order()
        assert set(order) == {"x", "y", "z"}


class TestRun:
    """Test WorkflowEngine.run() execution."""

    def test_run_executes_in_order(self) -> None:
        """Handlers execute in topological order, sharing context."""
        steps = [
            WorkflowStep(
                name="a", description="A", handler=_noop_handler,
                config={"step_id": "a"},
            ),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"], config={"step_id": "b"},
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["b"], config={"step_id": "c"},
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()
        context: dict[str, Any] = {}

        results = engine.run(mock_store, context)

        assert context["call_order"] == ["a", "b", "c"]
        assert results["a"]["status"] == "completed"
        assert results["b"]["status"] == "completed"
        assert results["c"]["status"] == "completed"

    def test_run_skip_condition(self) -> None:
        """Steps with skip_if returning True should be skipped."""
        steps = [
            WorkflowStep(
                name="a", description="A", handler=_noop_handler,
                config={"step_id": "a"},
            ),
            WorkflowStep(
                name="b", description="B", handler=_noop_handler,
                depends_on=["a"], config={"step_id": "b"},
                skip_if=lambda s, c: True,
            ),
            WorkflowStep(
                name="c", description="C", handler=_noop_handler,
                depends_on=["b"], config={"step_id": "c"},
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()
        context: dict[str, Any] = {}

        results = engine.run(mock_store, context)

        assert results["b"]["status"] == "skipped"
        assert context["call_order"] == ["a", "c"]

    def test_run_step_failure_propagates(self) -> None:
        """A failing step should propagate the exception."""
        steps = [
            WorkflowStep(
                name="good", description="Good", handler=_noop_handler,
                config={"step_id": "good"},
            ),
            WorkflowStep(
                name="bad", description="Bad", handler=_failing_handler,
                depends_on=["good"],
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()

        with pytest.raises(RuntimeError, match="deliberate failure"):
            engine.run(mock_store)

    def test_run_failure_records_status(self) -> None:
        """After a failure, the result dict has status=failed before re-raise."""
        results_container: list[dict] = []

        def capture_handler(store: Any, context: dict, **kw: Any) -> None:
            raise ValueError("boom")

        steps = [
            WorkflowStep(
                name="explode", description="Boom", handler=capture_handler,
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()

        with pytest.raises(ValueError, match="boom"):
            engine.run(mock_store)

    def test_context_passed_between_steps(self) -> None:
        """One step can write to context, another can read it."""
        def writer(store: Any, context: dict, **kw: Any) -> str:
            context["shared_value"] = 42
            return "wrote"

        def reader(store: Any, context: dict, **kw: Any) -> int:
            return context["shared_value"]

        steps = [
            WorkflowStep(name="write", description="Writer", handler=writer),
            WorkflowStep(
                name="read", description="Reader", handler=reader,
                depends_on=["write"],
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()
        context: dict[str, Any] = {}

        results = engine.run(mock_store, context)

        assert results["read"]["result"] == 42
        assert context["shared_value"] == 42

    def test_callbacks_invoked(self) -> None:
        """on_step_start and on_step_complete callbacks are called."""
        steps = [
            WorkflowStep(
                name="a", description="Step A", handler=_noop_handler,
                config={"step_id": "a"},
            ),
            WorkflowStep(
                name="b", description="Step B", handler=_noop_handler,
                depends_on=["a"], config={"step_id": "b"},
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()

        start_calls: list[tuple[str, str]] = []
        complete_calls: list[tuple[str, str]] = []

        results = engine.run(
            mock_store,
            on_step_start=lambda n, d: start_calls.append((n, d)),
            on_step_complete=lambda n, s: complete_calls.append((n, s)),
        )

        assert ("a", "Step A") in start_calls
        assert ("b", "Step B") in start_calls
        assert ("a", "completed") in complete_calls
        assert ("b", "completed") in complete_calls

    def test_elapsed_time_recorded(self) -> None:
        """Each step result should include non-negative elapsed time."""
        steps = [
            WorkflowStep(
                name="a", description="A", handler=_noop_handler,
                config={"step_id": "a"},
            ),
        ]
        engine = WorkflowEngine(steps)
        mock_store = MagicMock()

        results = engine.run(mock_store)

        assert "elapsed" in results["a"]
        assert results["a"]["elapsed"] >= 0

    def test_get_step(self) -> None:
        """get_step returns the correct step."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
        ]
        engine = WorkflowEngine(steps)
        step = engine.get_step("a")
        assert step.name == "a"
        assert step.description == "A"

    def test_get_step_missing_raises(self) -> None:
        """get_step raises KeyError for unknown step."""
        steps = [
            WorkflowStep(name="a", description="A", handler=_noop_handler),
        ]
        engine = WorkflowEngine(steps)
        with pytest.raises(KeyError, match="not in workflow"):
            engine.get_step("nonexistent")
