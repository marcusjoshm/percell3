"""PerCell 4 CLI — Click entry point with Rich output.

All command handlers are thin dispatchers (< 10 lines of logic).
Heavy dependencies are imported lazily to keep startup fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from percell4.cli.utils import (
    FOV_STATUS_EXPLANATIONS,
    console,
    format_uuid_short,
    make_progress,
    print_error,
    print_success,
    print_warning,
    is_interactive,
)

# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.option(
    "--experiment",
    "-e",
    type=click.Path(exists=False),
    help="Path to .percell experiment",
)
@click.pass_context
def cli(ctx: click.Context, experiment: str | None) -> None:
    """PerCell4 -- single-cell microscopy analysis."""
    ctx.ensure_object(dict)
    ctx.obj["experiment_path"] = Path(experiment) if experiment else None
    if ctx.invoked_subcommand is None:
        if is_interactive():
            from percell4.cli.menu_system import MenuState
            from percell4.cli.menu_handlers import build_main_menu

            state = MenuState(experiment_path=ctx.obj.get("experiment_path"))
            menu = build_main_menu(state)
            try:
                menu.run()
            except KeyboardInterrupt:
                pass
            finally:
                state.close()
        else:
            click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_experiment_path(ctx: click.Context) -> Path | None:
    """Extract experiment path from CLI context."""
    return ctx.obj.get("experiment_path")


def _open_store(ctx: click.Context):  # noqa: ANN201
    """Open experiment store from CLI context.

    Falls back to auto-load from recent.json if no --experiment given.
    """
    path = _get_experiment_path(ctx)
    if path is None:
        path = _try_auto_load()
    if path is None:
        raise click.UsageError(
            "No experiment specified. Use --experiment/-e or create one first."
        )
    from percell4.core.experiment_store import ExperimentStore

    return ExperimentStore.open(path)


def _try_auto_load() -> Path | None:
    """Load most recent experiment from ~/.config/percell4/recent.json."""
    recent_file = Path.home() / ".config" / "percell4" / "recent.json"
    if recent_file.exists():
        data = json.loads(recent_file.read_text())
        if data.get("recent"):
            return Path(data["recent"][0])
    return None


def _save_recent(path: Path) -> None:
    """Save experiment path to recent.json."""
    config_dir = Path.home() / ".config" / "percell4"
    config_dir.mkdir(parents=True, exist_ok=True)
    recent_file = config_dir / "recent.json"
    data = {"recent": [str(path.resolve())]}
    recent_file.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("config_toml", type=click.Path(exists=True))
@click.option("--path", "-p", type=click.Path(), default=None, help="Output .percell path")
@click.pass_context
def create(ctx: click.Context, config_toml: str, path: str | None) -> None:
    """Create a new experiment from a TOML config file."""
    from percell4.core.exceptions import ExperimentError
    from percell4.core.experiment_store import ExperimentStore

    try:
        config_path = Path(config_toml)
        if path is None:
            out_path = Path.cwd() / f"{config_path.stem}.percell"
        else:
            out_path = Path(path)
        store = ExperimentStore.create(out_path, config_path)
        _save_recent(out_path)
        exp = store.db.get_experiment()
        print_success(f"Created experiment '{exp['name']}' at {out_path}")
        store.close()
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--path", "-p", default="experiment.toml", help="Output TOML path")
@click.option("--template", is_flag=True, help="Include commented examples")
def init(path: str, template: bool) -> None:
    """Generate a default experiment.toml file."""
    out = Path(path)
    if out.exists():
        print_error(f"File already exists: {out}")
        raise SystemExit(1)

    lines = [
        '[experiment]',
        'name = "My Experiment"',
        'description = ""',
        '',
        '[[channels]]',
        'name = "DAPI"',
        'role = "nuclear"',
        'display_order = 0',
        '',
        '[[channels]]',
        'name = "GFP"',
        'role = "signal"',
        'display_order = 1',
        '',
        '[[roi_types]]',
        'name = "cell"',
    ]

    if template:
        lines.extend([
            '',
            '# -- Optional: sub-cellular ROI type --',
            '# [[roi_types]]',
            '# name = "particle"',
            '# parent_type = "cell"',
            '',
            '# -- Optional: segmentation parameters --',
            '# [op_configs.cellpose]',
            '# model_name = "cyto3"',
            '# diameter = 30',
        ])

    out.write_text("\n".join(lines) + "\n")
    print_success(f"Created {out}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show experiment status dashboard."""
    from rich.table import Table

    from percell4.core.db_types import uuid_to_str
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        exp = store.db.get_experiment()
        console.print(f"\n[bold]{exp['name']}[/bold]")
        console.print(f"  Path: {store.root}")

        channels = store.db.get_channels(exp["id"])
        console.print(f"  Channels: {', '.join(ch['name'] for ch in channels)}")

        fovs = store.db.get_fovs(exp["id"])
        if not fovs:
            console.print("  [dim]No FOVs imported yet.[/dim]")
            return

        # Status summary table
        status_counts: dict[str, int] = {}
        for fov in fovs:
            s = fov["status"]
            status_counts[s] = status_counts.get(s, 0) + 1

        table = Table(title="FOV Status Summary")
        table.add_column("Status", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Explanation", style="dim")

        for s, count in sorted(status_counts.items()):
            explanation = FOV_STATUS_EXPLANATIONS.get(s, "")
            table.add_row(s, str(count), explanation)

        console.print(table)
        console.print(f"\n  Total FOVs: {len(fovs)}")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@cli.command("import")
@click.argument("source_dir", type=click.Path(exists=True))
@click.option("--condition", "-c", default=None, help="Condition name")
@click.pass_context
def import_cmd(ctx: click.Context, source_dir: str, condition: str | None) -> None:
    """Import images from a directory."""
    from percell4.core.exceptions import ExperimentError
    from percell4.io.engine import ImportEngine
    from percell4.io.scanner import scan_directory

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        source = Path(source_dir)
        files = scan_directory(source)
        if not files:
            print_warning(f"No image files found in {source}")
            return

        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        ch_mapping = {i: ch["id"] for i, ch in enumerate(channels)}

        # Resolve condition if provided
        condition_id = None
        if condition:
            conditions = store.db.get_conditions(exp["id"])
            for c in conditions:
                if c["name"] == condition:
                    condition_id = c["id"]
                    break
            if condition_id is None:
                print_warning(f"Condition '{condition}' not found, importing without condition")

        engine = ImportEngine()
        paths = [f.path for f in files]

        with make_progress() as progress:
            task = progress.add_task("Importing...", total=len(paths))

            def on_progress(current: int, total: int, name: str) -> None:
                progress.update(task, advance=1, description=f"Importing {name}")

            fov_ids = engine.import_images(
                store, paths, ch_mapping,
                condition_id=condition_id,
                on_progress=on_progress,
            )

        print_success(f"Imported {len(fov_ids)} FOVs from {source}")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# segment
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--channel", "-c", required=True, help="Channel name to segment on")
@click.option("--roi-type", "-r", default="cell", help="ROI type to produce")
@click.option("--model", "-m", default="cyto3", help="Cellpose model name")
@click.option("--diameter", "-d", type=float, default=30.0, help="Cell diameter")
@click.pass_context
def segment(
    ctx: click.Context,
    channel: str,
    roi_type: str,
    model: str,
    diameter: float,
) -> None:
    """Run segmentation on imported FOVs."""
    from percell4.core.constants import FovStatus
    from percell4.core.exceptions import ExperimentError
    from percell4.segment._engine import SegmentationEngine
    from percell4.segment.cellpose_adapter import CellposeSegmenter

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs_by_status(exp["id"], FovStatus.imported)
        if not fovs:
            print_warning("No FOVs in 'imported' status to segment")
            return

        fov_ids = [f["id"] for f in fovs]
        params = {"model_name": model, "diameter": diameter}
        segmenter = CellposeSegmenter(model_name=model, diameter=diameter)
        engine = SegmentationEngine()

        with make_progress() as progress:
            task = progress.add_task("Segmenting...", total=len(fov_ids))

            def on_progress(current: int, total: int) -> None:
                progress.update(task, advance=1)

            seg_set_id, needed = engine.run(
                store, fov_ids, channel, roi_type, segmenter,
                parameters=params, on_progress=on_progress,
            )

        print_success(f"Segmented {len(fov_ids)} FOVs ({len(needed)} measurement jobs pending)")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def measure(ctx: click.Context) -> None:
    """Run measurements on segmented FOVs."""
    from percell4.core.constants import FovStatus
    from percell4.core.exceptions import ExperimentError
    from percell4.measure.auto_measure import run_measurements

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs_by_status(exp["id"], FovStatus.segmented)
        if not fovs:
            print_warning("No FOVs in 'segmented' status to measure")
            return

        # Build MeasurementNeeded items from active assignments
        from percell4.core.models import MeasurementNeeded

        channels = store.db.get_channels(exp["id"])
        channel_ids = [ch["id"] for ch in channels]
        needed = []

        for fov in fovs:
            assignments = store.db.get_active_assignments(fov["id"])
            for sa in assignments["segmentation"]:
                needed.append(
                    MeasurementNeeded(
                        fov_id=fov["id"],
                        roi_type_id=sa["roi_type_id"],
                        channel_ids=channel_ids,
                        reason="new_assignment",
                    )
                )

        if not needed:
            print_warning("No measurement work items found")
            return

        with make_progress() as progress:
            task = progress.add_task("Measuring...", total=len(needed))

            def on_progress(current: int, total: int) -> None:
                progress.update(task, advance=1)

            count = run_measurements(store, needed, on_progress=on_progress)

        print_success(f"Created {count} measurements across {len(fovs)} FOVs")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# threshold
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--channel", "-c", required=True, help="Channel to threshold")
@click.option("--value", "-v", type=float, default=None, help="Threshold value (omit to open viewer)")
@click.option("--method", "-m", default="manual", help="Thresholding method")
@click.pass_context
def threshold(ctx: click.Context, channel: str, value: float | None, method: str) -> None:
    """Apply an intensity threshold to a channel.

    When --value is omitted and stdin is interactive, opens the napari
    threshold viewer for live preview. Otherwise applies the threshold
    to all FOVs in batch mode.
    """
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        if value is None and is_interactive():
            # Launch napari threshold viewer
            try:
                from percell4.viewer import NAPARI_AVAILABLE, launch_viewer

                if not NAPARI_AVAILABLE:
                    print_error(
                        "napari is required for interactive thresholding. "
                        "Install with: pip install 'napari[all]'"
                    )
                    raise SystemExit(1)

                launch_viewer(store)
            except ImportError as e:
                print_error(str(e))
                raise SystemExit(1)
        elif value is not None:
            # Batch mode: apply threshold to all FOVs
            from percell4.core.constants import FovStatus
            from percell4.measure.thresholding import create_threshold_mask

            exp = store.db.get_experiment()
            fovs = store.db.get_fovs(exp["id"])
            active_fovs = [
                f for f in fovs
                if f["status"] not in ("deleted", "deleting", "error")
            ]

            if not active_fovs:
                print_warning("No active FOVs to threshold.")
                return

            count = 0
            with make_progress() as progress:
                task = progress.add_task("Thresholding...", total=len(active_fovs))
                for fov in active_fovs:
                    create_threshold_mask(
                        store,
                        fov["id"],
                        source_channel_name=channel,
                        method=method,
                        manual_value=value,
                    )
                    count += 1
                    progress.update(task, advance=1)

            print_success(f"Applied threshold {value} on {channel} to {count} FOVs")
        else:
            print_error("Provide --value for non-interactive mode.")
            raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# assignments
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def assignments(ctx: click.Context) -> None:
    """View active segmentation and mask assignments."""
    from rich.table import Table

    from percell4.core.db_types import uuid_to_str
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])

        if not fovs:
            console.print("[dim]No FOVs to show assignments for.[/dim]")
            return

        table = Table(title="Active Assignments")
        table.add_column("FOV", style="bold")
        table.add_column("Type")
        table.add_column("Target ID")
        table.add_column("Assigned By")

        for fov in fovs:
            assignments_data = store.db.get_active_assignments(fov["id"])
            fov_label = fov["auto_name"] or format_uuid_short(fov["id"])

            for sa in assignments_data["segmentation"]:
                table.add_row(
                    fov_label,
                    "segmentation",
                    format_uuid_short(sa["segmentation_set_id"]),
                    sa.get("assigned_by", ""),
                )
            for ma in assignments_data["mask"]:
                table.add_row(
                    fov_label,
                    "mask",
                    format_uuid_short(ma["threshold_mask_id"]),
                    ma.get("assigned_by", ""),
                )

        console.print(table)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("output", type=click.Path())
@click.option("--roi-type", default=None, help="Filter by ROI type name")
@click.option("--overwrite", is_flag=True, help="Overwrite existing file")
@click.pass_context
def export(ctx: click.Context, output: str, roi_type: str | None, overwrite: bool) -> None:
    """Export measurements to CSV."""
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        out_path = Path(output)
        if out_path.exists() and not overwrite:
            print_error(f"Output file already exists: {out_path}\nUse --overwrite to replace.")
            raise SystemExit(1)

        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])

        # Filter by ROI type if requested
        if roi_type:
            roi_types = store.db.get_roi_type_definitions(exp["id"])
            rt_match = None
            for rt in roi_types:
                if rt["name"] == roi_type:
                    rt_match = rt
                    break
            if rt_match is None:
                print_error(f"ROI type '{roi_type}' not found")
                raise SystemExit(1)

        fov_ids = [f["id"] for f in fovs if f["status"] not in ("deleted", "deleting", "error")]
        if not fov_ids:
            print_warning("No FOVs with exportable data")
            return

        count = store.export_measurements_csv(fov_ids, out_path)
        print_success(f"Exported {count} measurement rows to {out_path}")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# export-prism
# ---------------------------------------------------------------------------


@cli.command("export-prism")
@click.argument("output_dir", type=click.Path())
@click.option("--overwrite", is_flag=True, help="Overwrite existing files")
@click.pass_context
def export_prism(ctx: click.Context, output_dir: str, overwrite: bool) -> None:
    """Export per-channel/metric CSVs for Prism import."""
    import csv

    from percell4.core.constants import SCOPE_DISPLAY
    from percell4.core.db_types import uuid_to_str
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exp = store.db.get_experiment()
        fovs = store.db.get_fovs(exp["id"])
        fov_ids = [f["id"] for f in fovs if f["status"] not in ("deleted", "deleting", "error")]

        if not fov_ids:
            print_warning("No FOVs with exportable data")
            return

        # Collect all measurements
        all_rows: list[dict] = []
        for fov_id in fov_ids:
            measurements = store.db.get_active_measurements(fov_id)
            for m in measurements:
                all_rows.append(m)

        if not all_rows:
            print_warning("No measurements to export")
            return

        # Group by (channel, metric, scope) and write separate CSVs
        groups: dict[tuple, list] = {}
        channels = store.db.get_channels(exp["id"])
        ch_lookup = {ch["id"]: ch["name"] for ch in channels}

        for m in all_rows:
            ch_name = ch_lookup.get(m["channel_id"], "unknown")
            scope = SCOPE_DISPLAY.get(m["scope"], m["scope"])
            key = (ch_name, m["metric"], scope)
            groups.setdefault(key, []).append(m["value"])

        file_count = 0
        for (ch_name, metric, scope), values in sorted(groups.items()):
            fname = f"{ch_name}_{metric}_{scope}.csv"
            fpath = out_dir / fname
            if fpath.exists() and not overwrite:
                print_warning(f"Skipping {fname} (exists, use --overwrite)")
                continue
            with open(fpath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([f"{ch_name}_{metric}_{scope}"])
                for v in values:
                    writer.writerow([v])
            file_count += 1

        print_success(f"Exported {file_count} Prism CSV files to {out_dir}")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.pass_context
def merge(ctx: click.Context, source: str) -> None:
    """Merge another .percell experiment into this one."""
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        source_path = Path(source)
        # merge_experiment expects the path to the .db file
        db_path = source_path / "experiment.db" if source_path.is_dir() else source_path
        result = store.merge_experiment(db_path)

        console.print(f"\n[bold]Merge complete[/bold]")
        if result.get("warnings"):
            for w in result["warnings"]:
                print_warning(w)

        print_success(f"Merged {source_path} into {store.root}")
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--fov", default=None, help="FOV name or short UUID to view")
@click.pass_context
def view(ctx: click.Context, fov: str | None) -> None:
    """Open experiment in napari viewer."""
    from percell4.core.exceptions import ExperimentError

    try:
        store = _open_store(ctx)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)

    try:
        fov_id: bytes | None = None
        if fov is not None:
            # Try to resolve FOV by name or short UUID
            exp = store.db.get_experiment()
            fovs = store.db.get_fovs(exp["id"])
            fov_lower = fov.lower()
            for f in fovs:
                auto_name = f["auto_name"] or ""
                if auto_name.lower() == fov_lower:
                    fov_id = f["id"]
                    break
                from percell4.core.db_types import uuid_to_str
                if uuid_to_str(f["id"]).startswith(fov_lower):
                    fov_id = f["id"]
                    break
            if fov_id is None:
                print_error(f"FOV '{fov}' not found")
                raise SystemExit(1)

        from percell4.viewer import launch_viewer

        launch_viewer(store, fov_id=fov_id)
    except ImportError as e:
        print_error(str(e))
        raise SystemExit(1)
    except ExperimentError as e:
        print_error(str(e))
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# plugins
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--run", "-r", default=None, help="Run a plugin by name")
@click.pass_context
def plugins(ctx: click.Context, run: str | None) -> None:
    """List available plugins or run one by name."""
    from rich.table import Table

    from percell4.plugins.registry import PluginRegistry

    registry = PluginRegistry()

    if run is None:
        # List mode
        plugin_list = registry.list_plugins()
        if not plugin_list:
            console.print("[dim]No plugins found.[/dim]")
            return

        table = Table(title="Available Plugins")
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Description")

        for p in plugin_list:
            table.add_row(p["name"], p["type"], p["description"])

        console.print(table)
    else:
        # Run mode
        from percell4.core.exceptions import ExperimentError

        try:
            store = _open_store(ctx)
        except ExperimentError as e:
            print_error(str(e))
            raise SystemExit(1)

        try:
            plugin = registry.get_plugin(run)
            exp = store.db.get_experiment()
            fovs = store.db.get_fovs(exp["id"])
            fov_ids = [f["id"] for f in fovs if f["status"] not in ("deleted", "deleting", "error")]

            if not fov_ids:
                print_warning("No FOVs to process")
                return

            result = plugin.run(store, fov_ids)
            print_success(
                f"Plugin '{run}' completed: "
                f"{result.fovs_processed} FOVs, "
                f"{result.measurements_added} measurements"
            )
        except ExperimentError as e:
            print_error(str(e))
            raise SystemExit(1)
        finally:
            store.close()
