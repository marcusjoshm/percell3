"""Tests for WorkflowState."""

import pytest

from percell3.workflow.state import WorkflowState, StepExecution
from percell3.workflow.step import StepResult


class TestWorkflowState:
    def test_record_and_retrieve(self, mock_store):
        state = WorkflowState(mock_store)
        result = StepResult(status="completed", message="OK", elapsed_seconds=1.5)
        state.record_step("import", {"path": "/data"}, result)

        last = state.last_run("import")
        assert last is not None
        assert last.status == "completed"
        assert last.message == "OK"
        assert last.elapsed_seconds == 1.5
        assert last.parameters == {"path": "/data"}

    def test_is_completed(self, mock_store):
        state = WorkflowState(mock_store)
        assert state.is_completed("import") is False

        result = StepResult(status="completed")
        state.record_step("import", {}, result)
        assert state.is_completed("import") is True

    def test_is_completed_after_failure(self, mock_store):
        state = WorkflowState(mock_store)
        # First run succeeds
        state.record_step("step_a", {}, StepResult(status="completed"))
        assert state.is_completed("step_a") is True

        # Second run fails — last_run is now "failed"
        state.record_step("step_a", {}, StepResult(status="failed"))
        assert state.is_completed("step_a") is False

    def test_step_history_order(self, mock_store):
        state = WorkflowState(mock_store)
        state.record_step("step_a", {"v": 1}, StepResult(status="completed"))
        state.record_step("step_a", {"v": 2}, StepResult(status="failed"))
        state.record_step("step_a", {"v": 3}, StepResult(status="completed"))

        history = state.get_step_history("step_a")
        assert len(history) == 3
        # Newest first
        assert history[0].parameters == {"v": 3}
        assert history[2].parameters == {"v": 1}

    def test_last_run_returns_none_if_never_run(self, mock_store):
        state = WorkflowState(mock_store)
        assert state.last_run("never_run") is None

    def test_empty_history(self, mock_store):
        state = WorkflowState(mock_store)
        assert state.get_step_history("nonexistent") == []

    def test_persistence_across_connections(self, mock_store):
        """State persists when a new WorkflowState reads the same DB."""
        state1 = WorkflowState(mock_store)
        state1.record_step("persist_me", {}, StepResult(status="completed"))

        # Create new WorkflowState pointing to same DB
        state2 = WorkflowState(mock_store)
        assert state2.is_completed("persist_me") is True

    def test_from_db_path(self, tmp_path):
        db_path = tmp_path / "direct.db"
        state = WorkflowState.from_db_path(db_path)
        state.record_step("test", {}, StepResult(status="completed"))
        assert state.is_completed("test") is True

        # Verify it persisted
        state2 = WorkflowState.from_db_path(db_path)
        assert state2.is_completed("test") is True
