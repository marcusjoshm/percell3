"""percell3 view — launch napari to view and edit segmentation labels."""

from __future__ import annotations

import click

from percell3.cli.utils import console, error_handler, open_experiment


@click.command()
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "-r", "--region", required=True,
    help="Region name to view.",
)
@click.option(
    "--condition", default=None,
    help="Condition name (auto-detected if only one exists).",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated channel names to load. All channels if omitted.",
)
@error_handler
def view(
    experiment: str,
    region: str,
    condition: str | None,
    channels: str | None,
) -> None:
    """Launch napari to view and edit segmentation labels."""
    from percell3.segment.viewer import launch_viewer

    store = open_experiment(experiment)
    try:
        # Auto-detect condition if only one exists
        if condition is None:
            regions = store.get_regions()
            conditions = sorted({r.condition for r in regions})
            if len(conditions) == 1:
                condition = conditions[0]
            elif len(conditions) == 0:
                console.print("[red]Error:[/red] No regions found in experiment.")
                raise SystemExit(1)
            else:
                console.print(
                    "[red]Error:[/red] Multiple conditions found. "
                    f"Use --condition to specify one of: {', '.join(conditions)}"
                )
                raise SystemExit(1)

        channel_list: list[str] | None = None
        if channels is not None:
            channel_list = [c.strip() for c in channels.split(",") if c.strip()]

        console.print(f"Opening [cyan]{region}[/cyan] ({condition}) in napari...")
        console.print("[dim]Close the napari window to save any label edits.[/dim]\n")

        try:
            run_id = launch_viewer(store, region, condition, channel_list)
        except ImportError:
            console.print(
                "[red]Error:[/red] napari is not installed.\n"
                "Install with: [bold]pip install 'percell3[napari]'[/bold]"
            )
            raise SystemExit(1)

        if run_id is not None:
            console.print(f"\n[green]Labels saved[/green] (run_id={run_id})")
        else:
            console.print("\n[dim]No changes detected.[/dim]")
    finally:
        store.close()
