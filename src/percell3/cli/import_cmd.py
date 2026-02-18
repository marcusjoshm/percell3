"""percell3 import — import TIFF images into an experiment."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.table import Table

from percell3.cli.utils import console, error_handler, make_progress, open_experiment

if TYPE_CHECKING:
    from percell3.core import ExperimentStore
    from percell3.io import ChannelMapping, ScanResult
    from percell3.io.models import DiscoveredFile


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
    "-b", "--bio-rep", default="N1",
    help="Biological replicate name (default: N1).",
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
    bio_rep: str,
    channel_map: tuple[str, ...],
    z_projection: str,
    files: tuple[str, ...],
    yes: bool,
) -> None:
    """Import TIFF images into an experiment."""
    store = open_experiment(experiment)
    try:
        source_files: list[Path] | None = [Path(f) for f in files] if files else None
        _run_import(
            store, source, condition, channel_map, z_projection, yes,
            bio_rep=bio_rep,
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
    bio_rep: str = "N1",
    condition_map: dict[str, str] | None = None,
    fov_names: dict[str, str] | None = None,
    bio_rep_map: dict[str, str] | None = None,
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
        fov_names=fov_names or {},
        z_transform=ZTransform(method=z_projection),
        pixel_size_um=scan_result.pixel_size_um,
        token_config=TokenConfig(),
        bio_rep=bio_rep,
        condition_map=condition_map or {},
        bio_rep_map=bio_rep_map or {},
        source_files=source_files,
    )

    # Execute with progress
    engine = ImportEngine()
    with make_progress() as progress:
        task = progress.add_task("Importing images...", total=None)

        def on_progress(current: int, total: int, fov_name: str) -> None:
            progress.update(task, total=total, completed=current,
                            description=f"Importing {fov_name}")

        result = engine.execute(plan, store, progress_callback=on_progress)

    # Show result
    console.print(f"\n[green]Import complete![/green]")
    console.print(f"  FOVs imported: {result.fovs_imported}")
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
    table.add_row("FOVs", ", ".join(scan_result.fovs) or "default")
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


@dataclass
class FileGroup:
    """A group of files sharing the same FOV token."""

    token: str
    files: list[DiscoveredFile]
    channels: list[str]
    z_slices: list[str]
    shape: tuple[int, ...]


def build_file_groups(scan_result: ScanResult) -> list[FileGroup]:
    """Group discovered files by FOV token.

    Returns:
        List of FileGroup instances, sorted by token name.
    """
    groups: dict[str, list[DiscoveredFile]] = defaultdict(list)
    for f in scan_result.files:
        token = f.tokens.get("fov", "default")
        groups[token].append(f)

    result = []
    for token in sorted(groups):
        files = groups[token]
        channels = sorted({f.tokens.get("channel", "0") for f in files})
        z_slices = sorted({f.tokens["z_slice"] for f in files if "z_slice" in f.tokens})
        shape = files[0].shape
        result.append(FileGroup(
            token=token,
            files=files,
            channels=channels,
            z_slices=z_slices,
            shape=shape,
        ))
    return result


def show_file_group_table(
    groups: list[FileGroup],
    assignments: dict[str, tuple[str, str, str]] | None = None,
) -> None:
    """Display numbered table of file groups with optional assignment info.

    Args:
        groups: List of file groups to display.
        assignments: Optional dict mapping token -> (condition, bio_rep, fov_name).
    """
    table = Table(show_header=True, title="File Groups")
    table.add_column("#", style="bold", width=4)
    table.add_column("File group")
    table.add_column("Ch", justify="right")
    table.add_column("Z", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Shape")
    if assignments:
        table.add_column("Condition", style="cyan")
        table.add_column("Bio Rep", style="green")
        table.add_column("FOV", style="yellow")

    for i, g in enumerate(groups, 1):
        shape_str = f"{g.shape[0]} x {g.shape[1]}" if len(g.shape) >= 2 else str(g.shape)
        row = [
            str(i),
            g.token,
            str(len(g.channels)),
            str(len(g.z_slices)) if g.z_slices else "-",
            str(len(g.files)),
            shape_str,
        ]
        if assignments:
            if g.token in assignments:
                cond, bio, fov = assignments[g.token]
                row.extend([cond, bio, fov])
            else:
                row.extend(["-", "-", "-"])
        table.add_row(*row)

    console.print(table)


def next_fov_number(store: ExperimentStore, condition: str, bio_rep: str) -> int:
    """Return next FOV number for the given (condition, bio_rep) scope.

    Args:
        store: The experiment store to query.
        condition: Condition name.
        bio_rep: Biological replicate name.

    Returns:
        The next sequential FOV number (1-based).
    """
    existing = store.get_fovs(condition=condition, bio_rep=bio_rep)
    return len(existing) + 1


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
