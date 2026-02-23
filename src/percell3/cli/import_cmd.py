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
@click.option(
    "--auto", is_flag=True, default=False,
    help="Auto-import: each FOV token becomes a condition. Cannot combine with --condition.",
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
    auto: bool,
) -> None:
    """Import TIFF images into an experiment."""
    if auto and condition != "default":
        console.print(
            "[red]Error:[/red] --auto and --condition are mutually exclusive."
        )
        raise SystemExit(1)

    store = open_experiment(experiment)
    try:
        source_files: list[Path] | None = [Path(f) for f in files] if files else None

        if auto:
            _run_auto_import(
                store, source, channel_map, z_projection, yes,
                bio_rep=bio_rep,
                source_files=source_files,
            )
        else:
            _run_import(
                store, source, condition, channel_map, z_projection, yes,
                bio_rep=bio_rep,
                source_files=source_files,
            )
    finally:
        store.close()


def _run_auto_import(
    store: ExperimentStore,
    source: str,
    channel_map: tuple[str, ...],
    z_projection: str,
    yes: bool,
    bio_rep: str = "N1",
    source_files: list[Path] | None = None,
) -> None:
    """Auto-import: each FOV token becomes a condition."""
    from percell3.io import FileScanner

    scanner = FileScanner()
    scan_result = scanner.scan(Path(source), files=source_files)

    groups = build_file_groups(scan_result)
    if not groups:
        console.print("[red]No file groups found.[/red]")
        return

    condition_map, fov_names, bio_rep_map, auto_channels = build_auto_assignments(
        groups, store,
    )

    # Use user-supplied channel map if provided, otherwise auto-generated
    effective_channel_map = channel_map if channel_map else auto_channels

    # Show preview
    show_auto_preview(
        groups, condition_map, fov_names, bio_rep_map,
        effective_channel_map, z_projection,
    )

    if not yes:
        if not click.confirm("Proceed with auto-import?"):
            console.print("[yellow]Import cancelled.[/yellow]")
            return

    default_condition = next(iter(condition_map.values()), "default")
    default_bio_rep = next(iter(bio_rep_map.values()), "N1")
    _run_import(
        store, source, default_condition, effective_channel_map, z_projection,
        yes=True, bio_rep=default_bio_rep,
        condition_map=condition_map, fov_names=fov_names,
        bio_rep_map=bio_rep_map,
        source_files=source_files, scan_result=scan_result,
    )


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
    table.add_column("File group", max_width=25, overflow="ellipsis")
    table.add_column("Ch", justify="right")
    table.add_column("Z", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Shape")
    if assignments:
        table.add_column("Condition", style="cyan", max_width=20, overflow="ellipsis")
        table.add_column("Bio Rep", style="green", max_width=15, overflow="ellipsis")
        table.add_column("FOV", style="yellow", max_width=20, overflow="ellipsis")

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


def build_auto_assignments(
    groups: list[FileGroup],
    store: ExperimentStore,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], tuple[str, ...]]:
    """Auto-assign condition, bio rep, FOV name, and channels for all groups.

    Each group's token becomes a condition name (sanitized). Bio rep defaults
    to "N1", FOV name to "FOV_001". Channels are auto-named ch00, ch01, etc.

    Args:
        groups: File groups from scanning.
        store: The experiment store (checked for existing condition names).

    Returns:
        Tuple of (condition_map, fov_names, bio_rep_map, channel_maps).
    """
    from percell3.io._sanitize import sanitize_name

    existing_conditions = set(store.get_conditions())
    used_names: set[str] = set()

    condition_map: dict[str, str] = {}
    fov_names: dict[str, str] = {}
    bio_rep_map: dict[str, str] = {}

    for group in groups:
        base = sanitize_name(group.token)

        # Collision detection: check against store and already-assigned names
        candidate = base
        counter = 2
        while candidate in existing_conditions or candidate in used_names:
            candidate = f"{base}_{counter}"
            counter += 1

        condition_map[group.token] = candidate
        fov_names[group.token] = "FOV_001"
        bio_rep_map[group.token] = "N1"
        used_names.add(candidate)

    # Collect unique channel tokens across all groups, sorted
    all_channels: set[str] = set()
    for group in groups:
        all_channels.update(group.channels)

    channel_maps = tuple(
        f"{ch}:ch{ch}" for ch in sorted(all_channels)
    )

    return condition_map, fov_names, bio_rep_map, channel_maps


def show_auto_preview(
    groups: list[FileGroup],
    condition_map: dict[str, str],
    fov_names: dict[str, str],
    bio_rep_map: dict[str, str],
    channel_maps: tuple[str, ...],
    z_method: str = "mip",
) -> None:
    """Display a preview of auto-import assignments."""
    assignments = {
        g.token: (condition_map[g.token], bio_rep_map[g.token], fov_names[g.token])
        for g in groups
        if g.token in condition_map
    }
    show_file_group_table(groups, assignments=assignments)

    console.print(f"\n[bold]Auto-import settings:[/bold]")
    console.print(f"  Channels:     {', '.join(channel_maps)}")
    console.print(f"  Z-projection: {z_method}")
    console.print(f"  Bio rep:      N1")
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
