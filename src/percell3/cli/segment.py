"""percell3 segment — run cell segmentation on experiment FOVs."""

from __future__ import annotations

import click

from percell3.cli.utils import console, error_handler, make_progress, open_experiment


@click.command()
@click.option(
    "-e", "--experiment", required=True, type=click.Path(exists=True),
    help="Path to the .percell experiment.",
)
@click.option(
    "-c", "--channel", required=True,
    help="Channel name to segment (e.g., DAPI).",
)
@click.option(
    "--model", default="cpsam", show_default=True,
    type=click.Choice(sorted([
        "cpsam", "cyto", "cyto2", "cyto3", "nuclei",
        "tissuenet", "livecell",
        "tissuenet_cp3", "livecell_cp3",
        "deepbacs_cp3", "cyto2_cp3",
        "yeast_PhC_cp3", "yeast_BF_cp3",
        "bact_phase_cp3", "bact_fluor_cp3",
        "plant_cp3",
    ]), case_sensitive=False),
    help="Cellpose model name.",
)
@click.option(
    "--diameter", type=float, default=None,
    help="Expected cell diameter in pixels. Auto-detect if omitted.",
)
@click.option(
    "--fovs", default=None,
    help="Comma-separated FOV names to segment. All FOVs if omitted.",
)
@click.option(
    "--condition", default=None,
    help="Only segment FOVs in this condition.",
)
@click.option(
    "-b", "--bio-rep", default=None,
    help="Only segment FOVs in this biological replicate.",
)
@error_handler
def segment(
    experiment: str,
    channel: str,
    model: str,
    diameter: float | None,
    fovs: str | None,
    condition: str | None,
    bio_rep: str | None,
) -> None:
    """Run cell segmentation on experiment FOVs."""
    from percell3.segment import SegmentationEngine

    store = open_experiment(experiment)
    try:
        engine = SegmentationEngine()

        fov_list: list[str] | None = None
        if fovs is not None:
            fov_list = [f.strip() for f in fovs.split(",") if f.strip()]

        with make_progress() as progress:
            task = progress.add_task("Segmenting...", total=None)

            def on_progress(current: int, total: int, fov_name: str) -> None:
                progress.update(
                    task, total=total, completed=current,
                    description=f"Segmenting {fov_name}",
                )

            result = engine.run(
                store,
                channel=channel,
                model=model,
                diameter=diameter,
                fovs=fov_list,
                condition=condition,
                bio_rep=bio_rep,
                progress_callback=on_progress,
            )

        # Summary
        console.print()
        console.print(f"[green]Segmentation complete[/green]")
        console.print(f"  FOVs processed: {result.fovs_processed}")
        console.print(f"  Total cells found: {result.cell_count}")
        console.print(f"  Elapsed: {result.elapsed_seconds:.1f}s")

        if result.warnings:
            console.print()
            console.print(f"[yellow]Warnings ({len(result.warnings)}):[/yellow]")
            for w in result.warnings:
                console.print(f"  [dim]- {w}[/dim]")
    finally:
        store.close()
