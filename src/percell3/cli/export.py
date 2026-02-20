"""percell3 export — export measurements to CSV."""

from __future__ import annotations

from pathlib import Path

import click

from percell3.cli.utils import console, error_handler, open_experiment


@click.command()
@click.argument("output", type=click.Path())
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "--overwrite", is_flag=True,
    help="Overwrite output file if it exists.",
)
@click.option(
    "--channels", default=None,
    help="Comma-separated list of channels to export.",
)
@click.option(
    "--metrics", default=None,
    help="Comma-separated list of metrics to export.",
)
@click.option(
    "--include-particles", is_flag=True,
    help="Also export per-particle data to a companion CSV.",
)
@error_handler
def export(
    output: str,
    experiment: str,
    overwrite: bool,
    channels: str | None,
    metrics: str | None,
    include_particles: bool,
) -> None:
    """Export measurements to CSV."""
    store = open_experiment(experiment)
    try:
        out_path = Path(output).expanduser()

        # Reject directory paths
        if out_path.is_dir():
            console.print(
                f"[red]Error:[/red] Output path is a directory: {out_path}\n"
                f"Provide a file path, e.g. {out_path / 'measurements.csv'}"
            )
            raise SystemExit(1)

        # Check parent directory exists
        if not out_path.parent.exists():
            console.print(
                f"[red]Error:[/red] Parent directory does not exist: {out_path.parent}"
            )
            raise SystemExit(1)

        # Check overwrite
        if out_path.exists() and not overwrite:
            console.print(
                f"[red]Error:[/red] Output file already exists: {out_path}\n"
                "Use --overwrite to replace it."
            )
            raise SystemExit(1)

        # Parse filter lists
        ch_list = [c.strip() for c in channels.split(",")] if channels else None
        met_list = [m.strip() for m in metrics.split(",")] if metrics else None

        # Check particle companion file overwrite
        if include_particles:
            particle_path = out_path.with_name(
                f"{out_path.stem}_particles{out_path.suffix}"
            )
            if particle_path.exists() and not overwrite:
                console.print(
                    f"[red]Error:[/red] Particle file already exists: {particle_path}\n"
                    "Use --overwrite to replace it."
                )
                raise SystemExit(1)

        with console.status("[bold blue]Exporting measurements..."):
            store.export_csv(out_path, channels=ch_list, metrics=met_list)

        console.print(f"[green]Exported measurements to {out_path}[/green]")

        if include_particles:
            with console.status("[bold blue]Exporting particle data..."):
                store.export_particles_csv(
                    particle_path, channels=ch_list, metrics=met_list,
                )
            console.print(
                f"[green]Exported particle data to {particle_path}[/green]"
            )
    finally:
        store.close()
