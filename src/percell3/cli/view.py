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
    "-f", "--fov", required=True,
    help="FOV name to view.",
)
@click.option(
    "--condition", default=None,
    help="Condition name (auto-detected if only one exists).",
)
@click.option(
    "--bio-rep", default=None,
    help="Biological replicate name (auto-detected if only one exists).",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated channel names to load. All channels if omitted.",
)
@error_handler
def view(
    experiment: str,
    fov: str,
    condition: str | None,
    bio_rep: str | None,
    channels: str | None,
) -> None:
    """Launch napari to view and edit segmentation labels."""
    from percell3.segment.viewer import launch_viewer

    store = open_experiment(experiment)
    try:
        # Auto-detect condition if only one exists
        if condition is None:
            fovs = store.get_fovs()
            conditions = sorted({f.condition for f in fovs})
            if len(conditions) == 1:
                condition = conditions[0]
            elif len(conditions) == 0:
                console.print("[red]Error:[/red] No FOVs found in experiment.")
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

        console.print(f"Opening [cyan]{fov}[/cyan] ({condition}) in napari...")
        console.print("[dim]Close the napari window to save any label edits.[/dim]\n")

        try:
            run_id = launch_viewer(store, fov, condition, channel_list, bio_rep=bio_rep)
        except ImportError as exc:
            console.print(
                f"[red]Error:[/red] napari could not be loaded: {exc}\n"
                "Install with: [bold]pip install 'percell3[napari]'[/bold]"
            )
            raise SystemExit(1)

        if run_id is not None:
            console.print(f"\n[green]Labels saved[/green] (run_id={run_id})")
        else:
            console.print("\n[dim]No changes detected.[/dim]")
    finally:
        store.close()
