"""Shared fixtures for workflow tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from percell3.workflow.step import (
    StepInput,
    StepOutput,
    StepParameter,
    StepResult,
    StepRegistry,
    WorkflowStep,
)


class MockStep(WorkflowStep):
    """Configurable mock step for testing."""

    def __init__(
        self,
        step_name: str = "mock",
        step_inputs: list[StepInput] | None = None,
        step_outputs: list[StepOutput] | None = None,
        step_params: list[StepParameter] | None = None,
        result_status: str = "completed",
        result_message: str = "",
    ):
        self._name = step_name
        self._inputs = step_inputs or []
        self._outputs = step_outputs or []
        self._params = step_params or []
        self._result_status = result_status
        self._result_message = result_message
        self.execute_calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> list[StepInput]:
        return self._inputs

    @property
    def outputs(self) -> list[StepOutput]:
        return self._outputs

    @property
    def parameters(self) -> list[StepParameter]:
        return self._params

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        self.execute_calls.append({"store": store, "params": params})
        return StepResult(
            status=self._result_status,
            message=self._result_message,
            outputs_produced=[o.name for o in self._outputs],
        )


class FailingStep(WorkflowStep):
    """Step that always fails with an exception."""

    def __init__(self, step_name: str = "failing"):
        self._name = step_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def inputs(self) -> list[StepInput]:
        return []

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("error_output")]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        return StepResult(
            status="failed",
            message="Step failed intentionally",
        )


@dataclass
class MockStore:
    """Minimal mock that satisfies WorkflowState's requirement for a db_path."""

    db_path: Path


@pytest.fixture
def mock_store(tmp_path: Path) -> MockStore:
    """Create a MockStore with a temporary database path."""
    return MockStore(db_path=tmp_path / "test.db")


@pytest.fixture(autouse=True)
def _clean_registry():
    """Save and restore the step registry around each test."""
    saved = dict(StepRegistry._registry)
    StepRegistry.clear()
    yield
    StepRegistry._registry.clear()
    StepRegistry._registry.update(saved)


def register_defaults() -> None:
    """Re-register all built-in steps. Call in tests that need them."""
    from percell3.workflow.defaults import (
        Classify, ExportCsv, ImportLif, ImportTiff,
        Measure, RunPlugin, Segment, Threshold,
    )
    for cls in (ImportLif, ImportTiff, Segment, Measure,
                Threshold, Classify, RunPlugin, ExportCsv):
        StepRegistry.register(cls)


def make_mock_step(
    name: str,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
) -> MockStep:
    """Convenience factory for creating MockStep with string input/output names."""
    return MockStep(
        step_name=name,
        step_inputs=[StepInput(n) for n in (inputs or [])],
        step_outputs=[StepOutput(n) for n in (outputs or [])],
    )
