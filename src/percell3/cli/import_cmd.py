"""percell3 import — import TIFF images into an experiment."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.table import Table

from percell3.cli.utils import console, error_handler, make_progress, open_experiment

if TYPE_CHECKING:
    from percell3.core import ExperimentStore
    from percell3.io import ChannelMapping, ScanResult


@click.command("import")
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "-e", "--experiment", required=True, type=click.Path(),
    help="Path to the .percell experiment.",
)
@click.option(
    "-c", "--condition", default="default",
    help="Condition name for imported images.",
)
@click.option(
    "--channel-map", multiple=True,
    help="Channel mapping, e.g. '00:DAPI'. Can be repeated.",
)
@click.option(
    "--z-projection",
    type=click.Choice(["mip", "sum", "mean", "keep"]),
    default="mip",
    help="Z-stack projection method.",
)
@click.option(
    "--auto-conditions", is_flag=True,
    help="Auto-detect conditions from region names.",
)
@click.option(
    "--files", multiple=True, type=click.Path(exists=True),
    help="Specific TIFF files to import (instead of scanning directory).",
)
@click.option(
    "--yes", "-y", is_flag=True,
    help="Skip confirmation prompt.",
)
@error_handler
def import_cmd(
    source: str,
    experiment: str,
    condition: str,
    channel_map: tuple[str, ...],
    z_projection: str,
    auto_conditions: bool,
    files: tuple[str, ...],
    yes: bool,
) -> None:
    """Import TIFF images into an experiment."""
    store = open_experiment(experiment)
    try:
        condition_map: dict[str, str] = {}
        region_names: dict[str, str] = {}
        source_files: list[Path] | None = [Path(f) for f in files] if files else None

        if auto_conditions:
            from percell3.io import FileScanner, detect_conditions

            scanner = FileScanner()
            scan_result = scanner.scan(Path(source), files=source_files)
            detection = detect_conditions(scan_result.regions)
            if detection is not None:
                condition_map = dict(detection.condition_map)
                region_names = dict(detection.region_name_map)
                console.print(
                    f"Auto-detected {len(detection.conditions)} conditions: "
                    f"{', '.join(detection.conditions)}"
                )
            else:
                console.print(
                    "[yellow]No conditions detected, using single condition.[/yellow]"
                )

        _run_import(
            store, source, condition, channel_map, z_projection, yes,
            condition_map=condition_map, region_names=region_names,
            source_files=source_files,
        )
    finally:
        store.close()


def _run_import(
    store: ExperimentStore,
    source: str,
    condition: str,
    channel_map: tuple[str, ...],
    z_projection: str,
    yes: bool,
    condition_map: dict[str, str] | None = None,
    region_names: dict[str, str] | None = None,
    source_files: list[Path] | None = None,
    scan_result: ScanResult | None = None,
) -> None:
    """Core import logic shared by CLI and interactive menu."""
    from percell3.io import (
        ChannelMapping,
        FileScanner,
        ImportEngine,
        ImportPlan,
        TokenConfig,
        ZTransform,
    )

    # Scan source directory (or explicit file list) — skip if already scanned
    if scan_result is None:
        scanner = FileScanner()
        scan_result = scanner.scan(Path(source), files=source_files)

    # Show preview
    _show_preview(scan_result, source)

    # Confirm
    if not yes:
        if not click.confirm("Proceed with import?"):
            console.print("[yellow]Import cancelled.[/yellow]")
            return

    # Build channel mappings
    mappings = _parse_channel_maps(channel_map)

    # Build import plan
    plan = ImportPlan(
        source_path=Path(source),
        condition=condition,
        channel_mappings=mappings,
        region_names=region_names or {},
        z_transform=ZTransform(method=z_projection),
        pixel_size_um=scan_result.pixel_size_um,
        token_config=TokenConfig(),
        condition_map=condition_map or {},
        source_files=source_files,
    )

    # Execute with progress
    engine = ImportEngine()
    with make_progress() as progress:
        task = progress.add_task("Importing images...", total=None)

        def on_progress(current: int, total: int, region_name: str) -> None:
            progress.update(task, total=total, completed=current,
                            description=f"Importing {region_name}")

        result = engine.execute(plan, store, progress_callback=on_progress)

    # Show result
    console.print(f"\n[green]Import complete![/green]")
    console.print(f"  Regions imported: {result.regions_imported}")
    console.print(f"  Channels registered: {result.channels_registered}")
    console.print(f"  Images written: {result.images_written}")
    if result.skipped:
        console.print(f"  Skipped: {result.skipped}")
    if result.warnings:
        for w in result.warnings:
            console.print(f"  [yellow]Warning:[/yellow] {w}")
    console.print(f"  Elapsed: {result.elapsed_seconds}s")


def _show_preview(scan_result: ScanResult, source: str) -> None:
    """Display a preview table of what will be imported."""
    console.print(f"\n[bold]Scan results for[/bold] {source}\n")

    table = Table(show_header=True)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Files found", str(len(scan_result.files)))
    table.add_row("Channels", ", ".join(scan_result.channels) or "none")
    table.add_row("Regions", ", ".join(scan_result.regions) or "default")
    table.add_row("Timepoints", ", ".join(scan_result.timepoints) or "none")
    table.add_row("Z-slices", ", ".join(scan_result.z_slices) or "none")

    if scan_result.files:
        first = scan_result.files[0]
        table.add_row("Image shape", f"{first.shape[0]} x {first.shape[1]}")
        table.add_row("Data type", first.dtype)

    if scan_result.pixel_size_um:
        table.add_row("Pixel size", f"{scan_result.pixel_size_um} \u00b5m")

    console.print(table)

    if scan_result.warnings:
        for w in scan_result.warnings:
            console.print(f"  [yellow]Warning:[/yellow] {w}")
    console.print()


def _parse_channel_maps(maps: tuple[str, ...]) -> list[ChannelMapping]:
    """Parse channel map strings like '00:DAPI' into ChannelMapping objects."""
    from percell3.io import ChannelMapping

    mappings: list[ChannelMapping] = []
    for m in maps:
        if ":" not in m:
            console.print(
                f"[red]Error:[/red] Invalid channel map '{m}'. "
                "Expected format: 'token:name' (e.g., '00:DAPI')"
            )
            raise SystemExit(1)
        token, name = m.split(":", 1)
        mappings.append(ChannelMapping(token_value=token.strip(), name=name.strip()))
    return mappings
