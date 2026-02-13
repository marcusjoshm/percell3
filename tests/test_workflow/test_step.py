"""Tests for WorkflowStep, dataclasses, and StepRegistry."""

from percell3.workflow.step import (
    StepInput,
    StepOutput,
    StepParameter,
    StepResult,
    StepRegistry,
    WorkflowStep,
)
from tests.test_workflow.conftest import MockStep


class TestStepDataclasses:
    def test_step_input_defaults(self):
        inp = StepInput("images")
        assert inp.name == "images"
        assert inp.required is True

    def test_step_input_optional(self):
        inp = StepInput("masks", required=False)
        assert inp.required is False

    def test_step_output(self):
        out = StepOutput("labels")
        assert out.name == "labels"

    def test_step_parameter_with_choices(self):
        param = StepParameter(
            name="model",
            type="choice",
            default="cyto3",
            choices=["cyto3", "nuclei"],
            description="Cellpose model",
        )
        assert param.choices == ["cyto3", "nuclei"]
        assert param.default == "cyto3"

    def test_step_result_defaults(self):
        result = StepResult(status="completed")
        assert result.message == ""
        assert result.outputs_produced == []
        assert result.elapsed_seconds == 0.0


class TestMockStep:
    def test_mock_step_properties(self):
        step = MockStep(
            step_name="test",
            step_inputs=[StepInput("a")],
            step_outputs=[StepOutput("b")],
        )
        assert step.name == "test"
        assert len(step.inputs) == 1
        assert len(step.outputs) == 1

    def test_mock_step_execute(self):
        step = MockStep(step_name="test")
        result = step.execute(None, {})
        assert result.status == "completed"
        assert len(step.execute_calls) == 1

    def test_can_run_default_true(self):
        step = MockStep()
        assert step.can_run(None) is True

    def test_default_parameters_empty(self):
        step = MockStep()
        assert step.parameters == []


class TestStepRegistry:
    def test_register_and_get(self):
        class MyStep(MockStep):
            @property
            def name(self) -> str:
                return "my_step"

        StepRegistry.register(MyStep)
        assert StepRegistry.get("my_step") is MyStep

    def test_get_unknown_raises(self):
        import pytest

        with pytest.raises(KeyError, match="Unknown step 'nonexistent'"):
            StepRegistry.get("nonexistent")

    def test_list_steps(self):
        class StepA(MockStep):
            @property
            def name(self) -> str:
                return "alpha"

        class StepB(MockStep):
            @property
            def name(self) -> str:
                return "beta"

        StepRegistry.register(StepA)
        StepRegistry.register(StepB)
        assert StepRegistry.list_steps() == ["alpha", "beta"]

    def test_clear(self):
        class StepC(MockStep):
            @property
            def name(self) -> str:
                return "gamma"

        StepRegistry.register(StepC)
        assert len(StepRegistry.list_steps()) == 1
        StepRegistry.clear()
        assert len(StepRegistry.list_steps()) == 0

    def test_register_as_decorator(self):
        @StepRegistry.register
        class DecoratedStep(MockStep):
            @property
            def name(self) -> str:
                return "decorated"

        assert StepRegistry.get("decorated") is DecoratedStep
