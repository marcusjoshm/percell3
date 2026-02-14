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
        MenuItem("3", "Segment cells", None, enabled=False),
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
            console.print(f"  [{item.key}] {item.label}")
        else:
            console.print(f"  [{item.key}] {item.label}  [dim](coming soon)[/dim]")


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

    # Scan for preview and interactive prompts
    from percell3.io import FileScanner
    from percell3.cli.import_cmd import _show_preview, _run_import

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

    # Delegate to shared import pipeline (yes=True since we already confirmed)
    _run_import(store, str(source), condition, channel_maps, z_method, yes=True)


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
    from percell3.cli.query import format_output

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
        ch_list = store.get_channels()
        if not ch_list:
            console.print("[dim]No channels found.[/dim]")
            return
        rows = [{"name": ch.name, "role": ch.role or "", "color": ch.color or ""}
                for ch in ch_list]
        format_output(rows, ["name", "role", "color"], "table", "Channels")

    elif choice == "2":
        region_list = store.get_regions()
        if not region_list:
            console.print("[dim]No regions found.[/dim]")
            return
        rows = [
            {
                "name": r.name,
                "condition": r.condition,
                "size": f"{r.width}x{r.height}" if r.width else "",
                "pixel_size_um": str(r.pixel_size_um) if r.pixel_size_um else "",
            }
            for r in region_list
        ]
        format_output(rows, ["name", "condition", "size", "pixel_size_um"], "table", "Regions")

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

    with console.status("[bold blue]Exporting measurements..."):
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
