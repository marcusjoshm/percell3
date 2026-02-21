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
    help="FOV display name to view.",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated channel names to load. All channels if omitted.",
)
@error_handler
def view(
    experiment: str,
    fov: str,
    channels: str | None,
) -> None:
    """Launch napari to view and edit segmentation labels."""
    from percell3.segment.viewer import launch_viewer

    store = open_experiment(experiment)
    try:
        # Find FOV by display name
        all_fovs = store.get_fovs()
        matches = [f for f in all_fovs if f.display_name == fov]
        if not matches:
            console.print(
                f"[red]Error:[/red] No FOV named '{fov}' found. "
                f"Available: {', '.join(f.display_name for f in all_fovs)}"
            )
            raise SystemExit(1)
        fov_info = matches[0]

        channel_list: list[str] | None = None
        if channels is not None:
            channel_list = [c.strip() for c in channels.split(",") if c.strip()]

        console.print(f"Opening [cyan]{fov}[/cyan] in napari...")
        console.print("[dim]Close the napari window to save any label edits.[/dim]\n")

        try:
            run_id = launch_viewer(store, fov_info.id, channel_list)
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
