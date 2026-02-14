"""Interactive menu for PerCell 3 CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from rich.prompt import Prompt

from percell3.cli.utils import console, make_progress, open_experiment

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


# Menu item: (key, label, handler_or_None, enabled)
MenuItem = tuple[str, str, Callable[["MenuState"], None] | None, bool]


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
        ("1", "Create experiment", _create_experiment, True),
        ("2", "Import images", _import_images, True),
        ("3", "Segment cells", None, False),
        ("4", "Measure channels", None, False),
        ("5", "Apply threshold", None, False),
        ("6", "Query experiment", _query_experiment, True),
        ("7", "Export to CSV", _export_csv, True),
        ("8", "Run workflow", _run_workflow, True),
        ("9", "Plugin manager", None, False),
        ("e", "Select experiment", _select_experiment, True),
        ("h", "Help", _show_help, True),
        ("q", "Quit", None, True),
    ]

    try:
        while state.running:
            _show_header(state)
            _show_menu(menu_items)

            choice = Prompt.ask("\nSelect an option", default="q")

            if choice == "q":
                break

            # Find matching menu item
            handler = None
            for key, label, fn, enabled in menu_items:
                if key == choice:
                    if not enabled:
                        console.print(
                            f"\n[yellow]{label} is not yet available.[/yellow]"
                        )
                        console.print(
                            "[dim]This feature is under development.[/dim]\n"
                        )
                    elif fn is not None:
                        handler = fn
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
    for key, label, _, enabled in items:
        if enabled:
            console.print(f"  [{key}] {label}")
        else:
            console.print(f"  [{key}] {label}  [dim](coming soon)[/dim]")


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

    # Get source path
    source_str = _prompt_source_path()
    if source_str is None:
        raise _MenuCancel()

    source = Path(source_str)

    # Scan and preview
    from percell3.io import FileScanner, ImportPlan, ImportEngine, ZTransform, TokenConfig
    from percell3.cli.import_cmd import _show_preview, _parse_channel_maps

    scanner = FileScanner()
    try:
        scan_result = scanner.scan(source)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    _show_preview(scan_result, str(source))

    # Condition
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

    # Build plan and execute
    mappings = _parse_channel_maps(channel_maps)
    plan = ImportPlan(
        source_path=source,
        condition=condition,
        channel_mappings=mappings,
        region_names={},
        z_transform=ZTransform(method=z_method),
        pixel_size_um=scan_result.pixel_size_um,
        token_config=TokenConfig(),
    )

    engine = ImportEngine()
    with make_progress() as progress:
        task = progress.add_task("Importing...", total=None)

        def on_progress(current: int, total: int, region_name: str) -> None:
            progress.update(task, total=total, completed=current,
                            description=f"Importing {region_name}")

        result = engine.execute(plan, store, progress_callback=on_progress)

    console.print(f"\n[green]Import complete![/green]")
    console.print(f"  Regions: {result.regions_imported}, Images: {result.images_written}")
    if result.warnings:
        for w in result.warnings:
            console.print(f"  [yellow]Warning:[/yellow] {w}")


def _prompt_source_path() -> str | None:
    """Prompt for source path, with optional folder picker."""
    console.print("\n[bold]Import source[/bold]")
    console.print("  [1] Type path")
    console.print("  [2] Browse for folder")
    console.print("  [b] Back")

    choice = Prompt.ask("Select", choices=["1", "2", "b"], default="1")

    if choice == "b":
        return None

    if choice == "2":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            folder = filedialog.askdirectory(title="Select TIFF directory")
            root.destroy()
            if folder:
                return folder
            console.print("[dim]No folder selected.[/dim]")
            return None
        except ImportError:
            console.print(
                "[yellow]tkinter not available.[/yellow] "
                "Please type the path instead."
            )
            # Fall through to type path

    path_str = Prompt.ask("Path to TIFF directory")
    return path_str if path_str else None


def _query_experiment(state: MenuState) -> None:
    """Interactively query the experiment."""
    store = state.require_experiment()

    console.print("\n[bold]Query[/bold]")
    console.print("  [1] Channels")
    console.print("  [2] Regions")
    console.print("  [3] Conditions")
    console.print("  [b] Back")

    choice = Prompt.ask("Select", choices=["1", "2", "3", "b"], default="1")

    if choice == "b":
        raise _MenuCancel()

    if choice == "1":
        from percell3.cli.query import channels
        from click import Context
        # Call the underlying logic directly
        ch_list = store.get_channels()
        if not ch_list:
            console.print("[dim]No channels found.[/dim]")
            return
        from rich.table import Table
        table = Table(show_header=True, title="Channels")
        table.add_column("Name", style="bold")
        table.add_column("Role")
        table.add_column("Color")
        for ch in ch_list:
            table.add_row(ch.name, ch.role or "", ch.color or "")
        console.print(table)

    elif choice == "2":
        region_list = store.get_regions()
        if not region_list:
            console.print("[dim]No regions found.[/dim]")
            return
        from rich.table import Table
        table = Table(show_header=True, title="Regions")
        table.add_column("Name", style="bold")
        table.add_column("Condition")
        table.add_column("Size")
        for r in region_list:
            size = f"{r.width}x{r.height}" if r.width else ""
            table.add_row(r.name, r.condition, size)
        console.print(table)

    elif choice == "3":
        cond_list = store.get_conditions()
        if not cond_list:
            console.print("[dim]No conditions found.[/dim]")
            return
        from rich.table import Table
        table = Table(show_header=True, title="Conditions")
        table.add_column("Name", style="bold")
        for c in cond_list:
            table.add_row(c)
        console.print(table)


def _export_csv(state: MenuState) -> None:
    """Interactively export measurements to CSV."""
    store = state.require_experiment()

    output_str = Prompt.ask("Output CSV path (or 'b' to go back)")
    if output_str.lower() == "b":
        raise _MenuCancel()

    out_path = Path(output_str).expanduser()
    store.export_csv(out_path)
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
    console.print("    percell3 query channels -e <exp> Query channels")
    console.print("    percell3 export <out> -e <exp>  Export to CSV")
    console.print("    percell3 workflow list          List workflows")
    console.print("    percell3 --help                 Full help text\n")
