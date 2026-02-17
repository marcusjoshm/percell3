"""percell3 workflow — manage and run workflows."""

from __future__ import annotations

from dataclasses import dataclass

import click

from percell3.cli.utils import console, error_handler, open_experiment


@dataclass(frozen=True)
class WorkflowPreset:
    """A named workflow configuration."""

    description: str
    factory_name: str


_PRESETS: dict[str, WorkflowPreset] = {
    "complete": WorkflowPreset(
        description="Import -> Segment -> Measure -> Export",
        factory_name="complete_analysis_workflow",
    ),
    "measure_only": WorkflowPreset(
        description="Re-measure with different channels (assumes labels exist)",
        factory_name="measure_only_workflow",
    ),
}


@click.group()
def workflow() -> None:
    """Manage and run workflows."""


@workflow.command("list")
@click.option("--steps", is_flag=True, help="Also list registered step types.")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "csv"]),
              default="table", help="Output format.")
@error_handler
def workflow_list(steps: bool, fmt: str) -> None:
    """List available preset workflows and step types."""
    from percell3.cli.query import format_output

    rows = [{"name": name, "description": preset.description}
            for name, preset in _PRESETS.items()]
    format_output(rows, ["name", "description"], fmt, "Preset Workflows")

    if steps:
        from percell3.workflow import StepRegistry

        step_names = StepRegistry.list_steps()
        step_rows = [{"name": s} for s in step_names]
        format_output(step_rows, ["name"], fmt, "Registered Step Types")


@workflow.command("run")
@click.argument("name")
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "--force", is_flag=True,
    help="Force re-run of already completed steps.",
)
@error_handler
def workflow_run(name: str, experiment: str, force: bool) -> None:
    """Run a preset workflow by name."""
    if name not in _PRESETS:
        available = ", ".join(_PRESETS.keys())
        console.print(
            f"[red]Error:[/red] Unknown workflow '{name}'. "
            f"Available: {available}"
        )
        raise SystemExit(1)

    store = open_experiment(experiment)
    try:
        # The factories have different signatures; handle each
        if name == "complete":
            console.print(
                "[yellow]Note:[/yellow] The 'complete' workflow requires "
                "segment and measure modules which are not yet available."
            )
            console.print("Use individual commands (create, import, query) instead.\n")
            return
        elif name == "measure_only":
            console.print(
                "[yellow]Note:[/yellow] The 'measure_only' workflow requires "
                "the measure module which is not yet available."
            )
            return
    finally:
        store.close()
