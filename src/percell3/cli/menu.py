"""Interactive menu for PerCell 3 CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from rich.prompt import Prompt

from percell3.cli.utils import console, make_progress, open_experiment

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


@dataclass(frozen=True)
class MenuItem:
    """A single entry in the interactive menu."""

    key: str
    label: str
    handler: Callable[[MenuState], None] | None
    enabled: bool


class MenuState:
    """Holds state across the interactive menu session."""

    def __init__(self) -> None:
        self.experiment_path: Path | None = None
        self.store: ExperimentStore | None = None
        self.running = True

    def set_experiment(self, path: Path) -> None:
        """Open an experiment and set it as current."""
        from percell3.core import ExperimentStore

        if self.store:
            self.store.close()
        self.store = ExperimentStore.open(path)
        self.experiment_path = path

    def close(self) -> None:
        """Clean up resources."""
        if self.store:
            self.store.close()
            self.store = None

    def require_experiment(self) -> ExperimentStore:
        """Get the current experiment or prompt to select one.

        Returns:
            The open ExperimentStore.
        """
        if self.store is None:
            console.print("[yellow]No experiment selected.[/yellow]")
            _select_experiment(self)
            if self.store is None:
                raise _MenuCancel()
        return self.store


class _MenuCancel(Exception):
    """Raised when user cancels an interactive operation."""


def run_interactive_menu() -> None:
    """Run the interactive menu loop."""
    state = MenuState()

    menu_items: list[MenuItem] = [
        MenuItem("1", "Create experiment", _create_experiment, enabled=True),
        MenuItem("2", "Import images", _import_images, enabled=True),
        MenuItem("3", "Segment cells", _segment_cells, enabled=True),
        MenuItem("4", "Measure channels", None, enabled=False),
        MenuItem("5", "Apply threshold", None, enabled=False),
        MenuItem("6", "Query experiment", _query_experiment, enabled=True),
        MenuItem("7", "Export to CSV", _export_csv, enabled=True),
        MenuItem("8", "Run workflow", _run_workflow, enabled=True),
        MenuItem("9", "Plugin manager", None, enabled=False),
        MenuItem("e", "Select experiment", _select_experiment, enabled=True),
        MenuItem("h", "Help", _show_help, enabled=True),
        MenuItem("q", "Quit", None, enabled=True),
    ]

    try:
        while state.running:
            _show_header(state)
            _show_menu(menu_items)

            try:
                choice = Prompt.ask("\nSelect an option", default="q")
            except EOFError:
                # Non-interactive (piped stdin) — exit cleanly.
                break

            if choice == "q":
                break

            # Find matching menu item
            handler = None
            for item in menu_items:
                if item.key == choice:
                    if not item.enabled:
                        console.print(
                            f"\n[yellow]{item.label} is not yet available.[/yellow]"
                        )
                        console.print(
                            "[dim]This feature is under development.[/dim]\n"
                        )
                    elif item.handler is not None:
                        handler = item.handler
                    break
            else:
                console.print(f"[red]Invalid option: {choice}[/red]")
                continue

            if handler:
                from percell3.core.exceptions import ExperimentError

                try:
                    handler(state)
                except _MenuCancel:
                    console.print("[dim]Cancelled.[/dim]")
                except ExperimentError as e:
                    console.print(f"[red]Error:[/red] {e}")
                except Exception as e:
                    console.print(f"[red]Internal error:[/red] {e}")
    finally:
        state.close()


def _show_header(state: MenuState) -> None:
    """Display the menu header with experiment context."""
    console.print("\n[bold]PerCell 3[/bold] — Single-Cell Microscopy Analysis\n")
    if state.experiment_path:
        name = state.store.name if state.store else ""
        label = f"{name} ({state.experiment_path})" if name else str(state.experiment_path)
        console.print(f"  Experiment: [cyan]{label}[/cyan]\n")
    else:
        console.print("  Experiment: [dim]None selected[/dim]\n")


def _show_menu(items: list[MenuItem]) -> None:
    """Render the menu items."""
    for item in items:
        if item.enabled:
            console.print(f"  \\[{item.key}] {item.label}")
        else:
            console.print(f"  \\[{item.key}] {item.label}  [dim](coming soon)[/dim]")


# --- Menu handlers ---


def _select_experiment(state: MenuState) -> None:
    """Prompt user to select an existing experiment."""
    path_str = Prompt.ask("Path to .percell experiment (or 'b' to go back)")
    if path_str.lower() == "b":
        raise _MenuCancel()

    path = Path(path_str).expanduser()
    if not path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {path}")
        return
    try:
        state.set_experiment(path)
        console.print(f"[green]Opened experiment at {path}[/green]\n")
    except Exception as e:
        console.print(f"[red]Error opening experiment:[/red] {e}")


def _create_experiment(state: MenuState) -> None:
    """Interactively create a new experiment."""
    path_str = Prompt.ask("Path for new experiment (or 'b' to go back)")
    if path_str.lower() == "b":
        raise _MenuCancel()

    path = Path(path_str).expanduser()
    name = Prompt.ask("Experiment name", default="")
    description = Prompt.ask("Description", default="")

    try:
        from percell3.core import ExperimentStore
        from percell3.core.exceptions import ExperimentError

        store = ExperimentStore.create(path, name=name, description=description)
        console.print(f"[green]Created experiment at {path}[/green]\n")
        # Set as current
        state.experiment_path = path
        if state.store:
            state.store.close()
        state.store = store
    except ExperimentError as e:
        console.print(f"[red]Error:[/red] {e}")


def _import_images(state: MenuState) -> None:
    """Interactively import TIFF images."""
    store = state.require_experiment()

    # Get source path (and optionally an explicit file list)
    source_str, source_files = _prompt_source_path()
    if source_str is None:
        raise _MenuCancel()

    source = Path(source_str)

    # Scan for preview and interactive prompts
    from percell3.io import FileScanner, detect_conditions
    from percell3.cli.import_cmd import _show_preview, _run_import

    scanner = FileScanner()
    try:
        scan_result = scanner.scan(source, files=source_files)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    _show_preview(scan_result, str(source))

    # Condition auto-detection
    condition = "default"
    condition_map: dict[str, str] = {}
    fov_names: dict[str, str] = {}

    detection = detect_conditions(scan_result.fovs)
    if detection is not None:
        console.print(f"\n[bold]Detected conditions[/bold] (pattern: {detection.pattern_used}):")
        # Group FOVs by condition for display
        cond_fovs: dict[str, list[str]] = {}
        for fov_token, cond in sorted(detection.condition_map.items()):
            site = detection.fov_name_map[fov_token]
            cond_fovs.setdefault(cond, []).append(site)
        for cond_name, sites in sorted(cond_fovs.items()):
            console.print(f"  {cond_name}: {', '.join(sorted(sites))}")

        if Prompt.ask(
            "Use detected conditions?", choices=["y", "n"], default="y"
        ) == "y":
            condition_map = dict(detection.condition_map)
            fov_names = dict(detection.fov_name_map)
        else:
            condition = Prompt.ask("Condition name", default="default")
    else:
        condition = Prompt.ask("Condition name", default="default")

    # Channel mapping
    channel_maps: tuple[str, ...] = ()
    if scan_result.channels:
        console.print(f"\nDiscovered channels: {', '.join(scan_result.channels)}")
        if Prompt.ask("Rename channels?", choices=["y", "n"], default="n") == "y":
            maps = []
            for ch in scan_result.channels:
                new_name = Prompt.ask(f"  Name for channel '{ch}'", default=ch)
                maps.append(f"{ch}:{new_name}")
            channel_maps = tuple(maps)

    # Z-projection
    z_method = "mip"
    if scan_result.z_slices:
        z_method = Prompt.ask(
            "Z-projection method",
            choices=["mip", "sum", "mean", "keep"],
            default="mip",
        )

    # Confirm
    if Prompt.ask("Proceed with import?", choices=["y", "n"], default="y") != "y":
        console.print("[yellow]Import cancelled.[/yellow]")
        return

    # Delegate to shared import pipeline (yes=True since we already confirmed).
    # Pass scan_result to avoid a redundant second scan.
    _run_import(
        store, str(source), condition, channel_maps, z_method, yes=True,
        condition_map=condition_map, fov_names=fov_names,
        source_files=source_files, scan_result=scan_result,
    )


def _segment_cells(state: MenuState) -> None:
    """Interactively run cell segmentation."""
    store = state.require_experiment()

    # Show available channels
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    console.print("\n[bold]Available channels:[/bold]")
    for ch in channels:
        role_str = f"  ({ch.role})" if ch.role else ""
        console.print(f"  {ch.name}{role_str}")

    channel = Prompt.ask(
        "Channel to segment",
        choices=[ch.name for ch in channels],
    )

    # Model selection
    console.print("\n[bold]Model:[/bold] cpsam (Cellpose-SAM, default for Cellpose 4.x)")
    model = Prompt.ask("Model", default="cpsam")

    # Diameter
    diam_str = Prompt.ask("Cell diameter in pixels (blank = auto-detect)", default="")
    diameter: float | None = None
    if diam_str:
        try:
            diameter = float(diam_str)
            if diameter <= 0:
                console.print("[red]Diameter must be positive.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid diameter: {diam_str}[/red]")
            return

    # Optional condition filter
    conditions = store.get_conditions()
    condition: str | None = None
    if len(conditions) > 1:
        console.print(f"\n[bold]Conditions:[/bold] {', '.join(conditions)}")
        cond_str = Prompt.ask("Condition filter (blank = all)", default="")
        if cond_str:
            condition = cond_str

    # Optional FOV filter
    fov_filter_list: list[str] | None = None
    all_fovs = store.get_fovs(condition=condition)
    if len(all_fovs) > 1:
        console.print(f"\n[bold]FOVs ({len(all_fovs)}):[/bold] ", end="")
        names = [f.name for f in all_fovs]
        if len(names) <= 10:
            console.print(", ".join(names))
        else:
            console.print(", ".join(names[:10]) + f" ... ({len(names)} total)")
        filter_str = Prompt.ask(
            "FOV filter (comma-separated, blank = all)", default=""
        )
        if filter_str:
            fov_filter_list = [f.strip() for f in filter_str.split(",") if f.strip()]

    # Confirm
    console.print(f"\n[bold]Segmentation settings:[/bold]")
    console.print(f"  Channel:  {channel}")
    console.print(f"  Model:    {model}")
    console.print(f"  Diameter: {diameter or 'auto-detect'}")
    if condition:
        console.print(f"  Condition: {condition}")
    if fov_filter_list:
        console.print(f"  FOVs:     {', '.join(fov_filter_list)}")
    else:
        console.print(f"  FOVs:     all ({len(all_fovs)})")

    if Prompt.ask("\nProceed?", choices=["y", "n"], default="y") != "y":
        console.print("[yellow]Segmentation cancelled.[/yellow]")
        return

    # Run segmentation
    from percell3.segment import SegmentationEngine

    engine = SegmentationEngine()

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
            fovs=fov_filter_list,
            condition=condition,
            progress_callback=on_progress,
        )

    console.print()
    console.print("[green]Segmentation complete[/green]")
    console.print(f"  FOVs processed: {result.fovs_processed}")
    console.print(f"  Total cells found: {result.cell_count}")
    console.print(f"  Elapsed: {result.elapsed_seconds:.1f}s")

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
        for w in result.warnings:
            console.print(f"  [dim]- {w}[/dim]")
    console.print()


def _prompt_source_path() -> tuple[str | None, list[Path] | None]:
    """Prompt for source path, with optional folder/file picker.

    Returns:
        Tuple of (source_path_string, optional_file_list).
        source_path is None when user cancels.
        file_list is None when scanning a directory (not explicit files).
    """
    console.print("\n[bold]Import source[/bold]")
    console.print("  \\[1] Type path")
    console.print("  \\[2] Browse for folder")
    console.print("  \\[3] Browse for files")
    console.print("  \\[b] Back")

    choice = Prompt.ask("Select", choices=["1", "2", "3", "b"], default="1")

    if choice == "b":
        return None, None

    if choice == "2":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            folder = filedialog.askdirectory(title="Select TIFF directory")
            root.destroy()
            if folder:
                return folder, None
            console.print("[dim]No folder selected.[/dim]")
            return None, None
        except ImportError:
            console.print(
                "[yellow]tkinter not available.[/yellow] "
                "Please type the path instead."
            )
            # Fall through to type path

    if choice == "3":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            files = filedialog.askopenfilenames(
                title="Select TIFF files",
                filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")],
            )
            root.destroy()
            if files:
                file_paths = [Path(f) for f in files]
                parent = file_paths[0].parent
                console.print(
                    f"  Selected {len(file_paths)} files from {parent}"
                )
                return str(parent), file_paths
            console.print("[dim]No files selected.[/dim]")
            return None, None
        except ImportError:
            console.print(
                "[yellow]tkinter not available.[/yellow] "
                "Please type the path instead."
            )
            # Fall through to type path

    path_str = Prompt.ask("Path to TIFF directory")
    return (path_str, None) if path_str else (None, None)


def _query_experiment(state: MenuState) -> None:
    """Interactively query the experiment."""
    from percell3.cli.query import format_output

    store = state.require_experiment()

    console.print("\n[bold]Query[/bold]")
    console.print("  [1] Channels")
    console.print("  [2] FOVs")
    console.print("  [3] Conditions")
    console.print("  [b] Back")

    choice = Prompt.ask("Select", choices=["1", "2", "3", "b"], default="1")

    if choice == "b":
        raise _MenuCancel()

    if choice == "1":
        ch_list = store.get_channels()
        if not ch_list:
            console.print("[dim]No channels found.[/dim]")
            return
        rows = [{"name": ch.name, "role": ch.role or "", "color": ch.color or ""}
                for ch in ch_list]
        format_output(rows, ["name", "role", "color"], "table", "Channels")

    elif choice == "2":
        fov_list = store.get_fovs()
        if not fov_list:
            console.print("[dim]No FOVs found.[/dim]")
            return
        rows = [
            {
                "name": f.name,
                "condition": f.condition,
                "size": f"{f.width}x{f.height}" if f.width else "",
                "pixel_size_um": str(f.pixel_size_um) if f.pixel_size_um else "",
            }
            for f in fov_list
        ]
        format_output(rows, ["name", "condition", "size", "pixel_size_um"], "table", "FOVs")

    elif choice == "3":
        cond_list = store.get_conditions()
        if not cond_list:
            console.print("[dim]No conditions found.[/dim]")
            return
        rows = [{"name": c} for c in cond_list]
        format_output(rows, ["name"], "table", "Conditions")


def _export_csv(state: MenuState) -> None:
    """Interactively export measurements to CSV."""
    store = state.require_experiment()

    output_str = Prompt.ask("Output CSV path (or 'b' to go back)")
    if output_str.lower() == "b":
        raise _MenuCancel()

    out_path = Path(output_str).expanduser()

    if out_path.exists():
        if Prompt.ask("File exists. Overwrite?", choices=["y", "n"], default="n") != "y":
            console.print("[yellow]Export cancelled.[/yellow]")
            return

    # Optional channel/metric filters
    ch_filter = Prompt.ask("Channels to export (comma-separated, blank = all)", default="")
    met_filter = Prompt.ask("Metrics to export (comma-separated, blank = all)", default="")

    ch_list = [c.strip() for c in ch_filter.split(",") if c.strip()] or None
    met_list = [m.strip() for m in met_filter.split(",") if m.strip()] or None

    with console.status("[bold blue]Exporting measurements..."):
        store.export_csv(out_path, channels=ch_list, metrics=met_list)
    console.print(f"[green]Exported measurements to {out_path}[/green]")


def _run_workflow(state: MenuState) -> None:
    """Interactively run a workflow."""
    console.print("\n[bold]Available Workflows[/bold]")
    console.print("  [1] complete — Import -> Segment -> Measure -> Export")
    console.print("  [2] measure_only — Re-measure with different channels")
    console.print("  [b] Back")

    choice = Prompt.ask("Select", choices=["1", "2", "b"], default="b")

    if choice == "b":
        raise _MenuCancel()

    if choice == "1":
        console.print(
            "\n[yellow]The 'complete' workflow requires segment and measure "
            "modules which are not yet available.[/yellow]"
        )
        console.print("Use individual commands (create, import, query) instead.\n")
    elif choice == "2":
        console.print(
            "\n[yellow]The 'measure_only' workflow requires the measure "
            "module which is not yet available.[/yellow]"
        )


def _show_help(state: MenuState) -> None:
    """Show help information."""
    console.print("\n[bold]PerCell 3 Help[/bold]\n")
    console.print("  PerCell 3 is a single-cell microscopy analysis platform.")
    console.print("  Use the numbered menu to navigate, or run commands directly:\n")
    console.print("    percell3 create <path>          Create a new experiment")
    console.print("    percell3 import <src> -e <exp>  Import TIFF images")
    console.print("    percell3 segment -e <exp> -c CH Segment cells")
    console.print("    percell3 query channels -e <exp> Query channels")
    console.print("    percell3 export <out> -e <exp>  Export to CSV")
    console.print("    percell3 workflow list          List workflows")
    console.print("    percell3 --help                 Full help text\n")
