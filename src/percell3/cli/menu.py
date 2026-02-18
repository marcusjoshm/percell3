"""Interactive menu for PerCell 3 CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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
    """Raised when user cancels an interactive operation (go back one level)."""


class _MenuHome(Exception):
    """Raised when user presses 'h' to return to the home menu."""


# ---------------------------------------------------------------------------
# Navigation-aware prompt helpers
# ---------------------------------------------------------------------------


def menu_prompt(
    prompt: str,
    *,
    choices: list[str] | None = None,
    default: str | None = None,
) -> str:
    """Prompt with universal navigation keys.

    Always accepts 'h' (home) and 'b' (back).  Validates against *choices*
    manually so that Rich doesn't reject the nav keys.

    Raises:
        _MenuHome: when user enters 'h'.
        _MenuCancel: when user enters 'b' or on EOFError.
    """
    hint = " (h=home, b=back)"
    full_prompt = prompt + hint

    while True:
        try:
            raw = console.input(f"{full_prompt}: ").strip()
        except EOFError:
            raise _MenuCancel()

        if not raw and default is not None:
            return default
        if not raw:
            continue

        lower = raw.lower()
        if lower == "h":
            raise _MenuHome()
        if lower in ("b", "q"):
            raise _MenuCancel()

        if choices is not None and raw not in choices:
            valid = ", ".join(choices)
            console.print(f"[red]Invalid choice.[/red] Options: {valid}")
            continue

        return raw


def numbered_select_one(
    items: list[str],
    prompt: str = "Select",
) -> str:
    """Display a numbered list and return the selected item.

    Auto-selects when only one option exists.

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    if not items:
        raise ValueError("numbered_select_one called with empty list")

    if len(items) == 1:
        console.print(f"  [dim](auto-selected: {items[0]})[/dim]")
        return items[0]

    _print_numbered_list(items)
    valid = [str(i) for i in range(1, len(items) + 1)]
    choice = menu_prompt(prompt, choices=valid)
    return items[int(choice) - 1]


def numbered_select_many(
    items: list[str],
    prompt: str = "Select (space-separated, or 'all')",
) -> list[str]:
    """Display a numbered list and return selected items.

    Supports space-separated numbers and 'all'.

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    if not items:
        raise ValueError("numbered_select_many called with empty list")

    _print_numbered_list(items)

    while True:
        raw = menu_prompt(prompt)

        if raw.lower() == "all":
            return list(items)

        parts = raw.split()
        try:
            indices = list({int(p) for p in parts})  # deduplicate
        except ValueError:
            console.print("[red]Enter numbers separated by spaces, or 'all'.[/red]")
            continue

        if any(i < 1 or i > len(items) for i in indices):
            console.print(f"[red]Numbers must be 1-{len(items)}.[/red]")
            continue

        if not indices:
            continue

        indices.sort()
        return [items[i - 1] for i in indices]


def _print_numbered_list(items: list[str], *, page_size: int = 20) -> None:
    """Print items as a numbered list, paginating if needed."""
    show = items if len(items) <= page_size else items[:page_size]
    for i, item in enumerate(show, 1):
        console.print(f"  \\[{i}] {item}")
    if len(items) > page_size:
        remaining = len(items) - page_size
        console.print(f"  [dim]... and {remaining} more (enter number to select)[/dim]")


def _try_auto_load(state: MenuState) -> None:
    """Try to auto-load the most recent experiment. Never raises."""
    try:
        from percell3.cli._recent import load_recent

        recent = load_recent()
        if recent:
            path = Path(recent[0])
            if path.exists():
                state.set_experiment(path)
                console.print(f"[dim]Auto-loaded: {path}[/dim]")
    except Exception as e:
        console.print(f"[dim]Could not auto-load last experiment: {e}[/dim]")


def run_interactive_menu() -> None:
    """Run the interactive menu loop."""
    state = MenuState()

    # Auto-load last-used experiment
    _try_auto_load(state)

    menu_items: list[MenuItem] = [
        MenuItem("1", "Create experiment", _create_experiment, enabled=True),
        MenuItem("2", "Import images", _import_images, enabled=True),
        MenuItem("3", "Segment cells", _segment_cells, enabled=True),
        MenuItem("4", "View in napari", _view_napari, enabled=True),
        MenuItem("5", "Measure channels", None, enabled=False),
        MenuItem("6", "Apply threshold", None, enabled=False),
        MenuItem("7", "Query experiment", _query_experiment, enabled=True),
        MenuItem("8", "Edit experiment", _edit_experiment, enabled=True),
        MenuItem("9", "Export to CSV", _export_csv, enabled=True),
        MenuItem("w", "Run workflow", _run_workflow, enabled=True),
        MenuItem("0", "Plugin manager", None, enabled=False),
        MenuItem("e", "Select experiment", _select_experiment, enabled=True),
        MenuItem("?", "Help", _show_help, enabled=True),
        MenuItem("q", "Quit", None, enabled=True),
    ]

    valid_keys = [item.key for item in menu_items]

    try:
        while state.running:
            _show_header(state)
            _show_menu(menu_items)

            try:
                choice = console.input("\nSelect an option: ").strip()
            except EOFError:
                break

            if not choice:
                choice = "q"
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
                except _MenuHome:
                    # Return to top of the main menu loop.
                    continue
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
    """Prompt user to select an existing experiment, with recent history."""
    from percell3.cli._recent import add_to_recent, load_recent

    recent = load_recent()

    if recent:
        console.print("\n[bold]Recent experiments:[/bold]")
        for i, p in enumerate(recent, 1):
            console.print(f"  \\[{i}] {p}")
        console.print(f"  \\[n] Enter new path")

        valid = [str(i) for i in range(1, len(recent) + 1)] + ["n"]
        choice = menu_prompt("Select", choices=valid)

        if choice == "n":
            path_str = menu_prompt("Path to .percell experiment")
        else:
            path_str = recent[int(choice) - 1]
    else:
        path_str = menu_prompt("Path to .percell experiment")

    path = Path(path_str).expanduser()
    if not path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {path}")
        return
    try:
        state.set_experiment(path)
        add_to_recent(path)
        console.print(f"[green]Opened experiment at {path}[/green]\n")
    except Exception as e:
        console.print(f"[red]Error opening experiment:[/red] {e}")


def _create_experiment(state: MenuState) -> None:
    """Interactively create a new experiment."""
    path_str = menu_prompt("Path for new experiment")

    path = Path(path_str).expanduser()
    name = menu_prompt("Experiment name", default="")
    description = menu_prompt("Description", default="")

    try:
        from percell3.core import ExperimentStore
        from percell3.core.exceptions import ExperimentError
        from percell3.cli._recent import add_to_recent

        store = ExperimentStore.create(path, name=name, description=description)
        console.print(f"[green]Created experiment at {path}[/green]\n")
        # Set as current
        state.experiment_path = path
        if state.store:
            state.store.close()
        state.store = store
        add_to_recent(path)
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

        if menu_prompt(
            "Use detected conditions?", choices=["y", "n"], default="y"
        ) == "y":
            condition_map = dict(detection.condition_map)
            fov_names = dict(detection.fov_name_map)
        else:
            condition = menu_prompt("Condition name", default="default")
    else:
        condition = menu_prompt("Condition name", default="default")

    # Channel mapping with auto-match
    channel_maps: tuple[str, ...] = ()
    if scan_result.channels:
        existing_channels = [ch.name for ch in store.get_channels()]
        maps = _auto_match_channels(scan_result.channels, existing_channels)
        if maps:
            channel_maps = tuple(maps)

    # Z-projection
    z_method = "mip"
    if scan_result.z_slices:
        z_method = menu_prompt(
            "Z-projection method",
            choices=["mip", "sum", "mean", "keep"],
            default="mip",
        )

    # Biological replicate
    bio_rep = _prompt_bio_rep(store)

    # Confirm
    if menu_prompt("Proceed with import?", choices=["y", "n"], default="y") != "y":
        console.print("[yellow]Import cancelled.[/yellow]")
        return

    # Delegate to shared import pipeline (yes=True since we already confirmed).
    # Pass scan_result to avoid a redundant second scan.
    _run_import(
        store, str(source), condition, channel_maps, z_method, yes=True,
        bio_rep=bio_rep,
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
    ch_names = [ch.name for ch in channels]
    channel = numbered_select_one(ch_names, "Channel to segment")

    # Model selection
    console.print("\n[bold]Model:[/bold] cpsam (Cellpose-SAM, default for Cellpose 4.x)")
    model = menu_prompt("Model", default="cpsam")

    # Diameter
    diam_str = menu_prompt("Cell diameter in pixels (blank = auto-detect)", default="")
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
        console.print("\n[bold]Conditions:[/bold]")
        _print_numbered_list(conditions)
        cond_str = menu_prompt("Condition filter (number, or blank = all)", default="")
        if cond_str:
            try:
                idx = int(cond_str)
                if 1 <= idx <= len(conditions):
                    condition = conditions[idx - 1]
                else:
                    console.print("[red]Invalid number.[/red]")
                    return
            except ValueError:
                condition = cond_str

    # Biological replicate filter
    bio_rep = _prompt_bio_rep(store)

    # Optional FOV filter
    fov_filter_list: list[str] | None = None
    all_fovs = store.get_fovs(condition=condition, bio_rep=bio_rep)
    if len(all_fovs) > 1:
        names = [f.name for f in all_fovs]
        console.print(f"\n[bold]FOVs ({len(names)}):[/bold]")
        _print_numbered_list(names)
        filter_str = menu_prompt(
            "FOV filter (space-separated numbers, 'all', or blank = all)",
            default="",
        )
        if filter_str and filter_str.lower() != "all":
            parts = filter_str.split()
            try:
                indices = sorted({int(p) for p in parts})
                fov_filter_list = [names[i - 1] for i in indices if 1 <= i <= len(names)]
            except ValueError:
                # Treat as comma-separated names for backward compat
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

    if menu_prompt("\nProceed?", choices=["y", "n"], default="y") != "y":
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
            bio_rep=bio_rep,
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


def _view_napari(state: MenuState) -> None:
    """Launch napari to view and edit segmentation labels."""
    store = state.require_experiment()

    # Select biological replicate
    bio_rep = _prompt_bio_rep(store)

    # Select condition
    conditions = store.get_conditions()
    if not conditions:
        console.print("[red]No conditions found.[/red] Import images first.")
        return

    console.print("\n[bold]Conditions:[/bold]")
    condition = numbered_select_one(conditions, "Condition")

    # Select FOV
    fovs = store.get_fovs(condition=condition, bio_rep=bio_rep)
    if not fovs:
        console.print(f"[red]No FOVs found for condition {condition!r}.[/red]")
        return

    fov_names = [f.name for f in fovs]
    console.print(f"\n[bold]FOVs ({len(fov_names)}):[/bold]")
    fov = numbered_select_one(fov_names, "FOV to view")

    console.print(f"\nOpening [cyan]{fov}[/cyan] ({condition}) in napari...")
    console.print("[dim]Close the napari window to save any label edits.[/dim]\n")

    from percell3.segment.viewer import launch_viewer

    try:
        run_id = launch_viewer(store, fov, condition, bio_rep=bio_rep)
    except ImportError as exc:
        console.print(
            f"[red]napari could not be loaded:[/red] {exc}\n"
            "Install with: [bold]pip install 'percell3[napari]'[/bold]"
        )
        return

    if run_id is not None:
        console.print(f"\n[green]Labels saved[/green] (run_id={run_id})")
    else:
        console.print("\n[dim]No changes detected.[/dim]")
    console.print()


def _prompt_bio_rep(store: ExperimentStore) -> str:
    """Prompt for biological replicate. Auto-resolves when only 1 exists."""
    reps = store.get_bio_reps()
    if len(reps) <= 1:
        return reps[0] if reps else "N1"
    console.print("\n[bold]Biological replicates:[/bold]")
    return numbered_select_one(reps, "Biological replicate")


def _auto_match_channels(
    discovered: list[str],
    existing: list[str],
) -> list[str]:
    """Auto-match discovered channel tokens to existing channels.

    Returns a list of 'token:name' mapping strings (empty if no renames needed).
    Case-insensitive matching. Unmatched tokens get a numbered pick list.
    """
    if not existing:
        # First import — fall back to freeform rename prompt
        console.print(f"\nDiscovered channels: {', '.join(discovered)}")
        if menu_prompt("Rename channels?", choices=["y", "n"], default="n") == "y":
            maps = []
            for ch in discovered:
                new_name = menu_prompt(f"  Name for channel '{ch}'", default=ch)
                maps.append(f"{ch}:{new_name}")
            return maps
        return []

    # Build case-insensitive lookup
    lower_map = {name.lower(): name for name in existing}

    maps: list[str] = []
    assigned: set[str] = set()

    console.print("\n[bold]Channel mapping:[/bold]")
    for token in discovered:
        match = lower_map.get(token.lower())
        if match and match not in assigned:
            console.print(f"  [auto] {token} → {match}")
            if token != match:
                maps.append(f"{token}:{match}")
            assigned.add(match)
        else:
            # Unmatched — let user pick from existing or create new
            available = [ch for ch in existing if ch not in assigned]
            if available:
                console.print(f"\n  Channel '{token}' — pick an existing channel or create new:")
                options = available + ["(new channel)"]
                _print_numbered_list(options)
                valid = [str(i) for i in range(1, len(options) + 1)]
                choice = menu_prompt(f"  Map '{token}' to", choices=valid)
                idx = int(choice) - 1
                if idx == len(available):
                    # New channel
                    new_name = menu_prompt(f"  Name for channel '{token}'", default=token)
                    if new_name != token:
                        maps.append(f"{token}:{new_name}")
                    assigned.add(new_name)
                else:
                    name = available[idx]
                    maps.append(f"{token}:{name}")
                    assigned.add(name)
            else:
                # All existing channels already assigned — create new
                new_name = menu_prompt(f"  Name for channel '{token}'", default=token)
                if new_name != token:
                    maps.append(f"{token}:{new_name}")
                assigned.add(new_name)

    # Validate: no two tokens mapped to the same name
    target_names = []
    for m in maps:
        target_names.append(m.split(":", 1)[1])
    # Also include tokens that weren't remapped
    for token in discovered:
        if not any(m.startswith(f"{token}:") for m in maps):
            target_names.append(token)
    if len(target_names) != len(set(target_names)):
        console.print("[red]Error: Two channels mapped to the same name.[/red]")
        console.print("Please re-run import with different channel assignments.")
        raise _MenuCancel()

    return maps


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

    choice = menu_prompt("Select", choices=["1", "2", "3"], default="1")

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

    path_str = menu_prompt("Path to TIFF directory")
    return (path_str, None) if path_str else (None, None)


def _query_experiment(state: MenuState) -> None:
    """Interactively query the experiment."""
    from percell3.cli.query import format_output

    store = state.require_experiment()

    console.print("\n[bold]Query[/bold]")
    console.print("  \\[1] Channels")
    console.print("  \\[2] FOVs")
    console.print("  \\[3] Conditions")
    console.print("  \\[4] Biological replicates")

    choice = menu_prompt("Select", choices=["1", "2", "3", "4"], default="1")

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
                "bio_rep": f.bio_rep,
                "size": f"{f.width}x{f.height}" if f.width else "",
                "pixel_size_um": str(f.pixel_size_um) if f.pixel_size_um else "",
            }
            for f in fov_list
        ]
        format_output(
            rows, ["name", "condition", "bio_rep", "size", "pixel_size_um"],
            "table", "FOVs",
        )

    elif choice == "3":
        cond_list = store.get_conditions()
        if not cond_list:
            console.print("[dim]No conditions found.[/dim]")
            return
        rows = [{"name": c} for c in cond_list]
        format_output(rows, ["name"], "table", "Conditions")

    elif choice == "4":
        rep_list = store.get_bio_reps()
        if not rep_list:
            console.print("[dim]No biological replicates found.[/dim]")
            return
        rows = [{"name": r} for r in rep_list]
        format_output(rows, ["name"], "table", "Biological Replicates")


def _edit_experiment(state: MenuState) -> None:
    """Sub-menu for renaming experiment entities."""
    store = state.require_experiment()

    console.print("\n[bold]Edit[/bold]")
    console.print("  \\[1] Rename experiment")
    console.print("  \\[2] Rename condition")
    console.print("  \\[3] Rename FOV")
    console.print("  \\[4] Rename channel")
    console.print("  \\[5] Rename bio-rep")

    choice = menu_prompt("Select", choices=["1", "2", "3", "4", "5"])

    if choice == "1":
        new_name = menu_prompt("New experiment name")
        store.rename_experiment(new_name)
        console.print(f"[green]Experiment renamed to '{new_name}'[/green]")

    elif choice == "2":
        conditions = store.get_conditions()
        if not conditions:
            console.print("[dim]No conditions found.[/dim]")
            return
        console.print("\n[bold]Conditions:[/bold]")
        old = numbered_select_one(conditions, "Condition to rename")
        new_name = menu_prompt(f"New name for '{old}'")
        store.rename_condition(old, new_name)
        console.print(f"[green]Condition '{old}' → '{new_name}'[/green]")

    elif choice == "3":
        # Need to select condition + bio-rep to disambiguate FOV
        conditions = store.get_conditions()
        if not conditions:
            console.print("[dim]No conditions found.[/dim]")
            return
        console.print("\n[bold]Conditions:[/bold]")
        condition = numbered_select_one(conditions, "Condition")
        bio_rep = _prompt_bio_rep(store)
        fovs = store.get_fovs(condition=condition, bio_rep=bio_rep)
        if not fovs:
            console.print("[dim]No FOVs found.[/dim]")
            return
        fov_names = [f.name for f in fovs]
        console.print(f"\n[bold]FOVs ({len(fov_names)}):[/bold]")
        old = numbered_select_one(fov_names, "FOV to rename")
        new_name = menu_prompt(f"New name for '{old}'")
        store.rename_fov(old, new_name, condition, bio_rep=bio_rep)
        console.print(f"[green]FOV '{old}' → '{new_name}'[/green]")

    elif choice == "4":
        channels = [ch.name for ch in store.get_channels()]
        if not channels:
            console.print("[dim]No channels found.[/dim]")
            return
        console.print("\n[bold]Channels:[/bold]")
        old = numbered_select_one(channels, "Channel to rename")
        new_name = menu_prompt(f"New name for '{old}'")
        store.rename_channel(old, new_name)
        console.print(f"[green]Channel '{old}' → '{new_name}'[/green]")

    elif choice == "5":
        reps = store.get_bio_reps()
        if not reps:
            console.print("[dim]No biological replicates found.[/dim]")
            return
        console.print("\n[bold]Biological replicates:[/bold]")
        old = numbered_select_one(reps, "Bio-rep to rename")
        new_name = menu_prompt(f"New name for '{old}'")
        store.rename_bio_rep(old, new_name)
        console.print(f"[green]Bio-rep '{old}' → '{new_name}'[/green]")


def _export_csv(state: MenuState) -> None:
    """Interactively export measurements to CSV."""
    store = state.require_experiment()

    output_str = menu_prompt("Output CSV path")

    out_path = Path(output_str).expanduser()

    if out_path.exists():
        if menu_prompt("File exists. Overwrite?", choices=["y", "n"], default="n") != "y":
            console.print("[yellow]Export cancelled.[/yellow]")
            return

    # Optional channel/metric filters
    ch_filter = menu_prompt("Channels to export (comma-separated, blank = all)", default="")
    met_filter = menu_prompt("Metrics to export (comma-separated, blank = all)", default="")

    ch_list = [c.strip() for c in ch_filter.split(",") if c.strip()] or None
    met_list = [m.strip() for m in met_filter.split(",") if m.strip()] or None

    with console.status("[bold blue]Exporting measurements..."):
        store.export_csv(out_path, channels=ch_list, metrics=met_list)
    console.print(f"[green]Exported measurements to {out_path}[/green]")


def _run_workflow(state: MenuState) -> None:
    """Interactively run a workflow."""
    console.print("\n[bold]Available Workflows[/bold]")
    console.print("  \\[1] complete — Import -> Segment -> Measure -> Export")
    console.print("  \\[2] measure_only — Re-measure with different channels")

    choice = menu_prompt("Select", choices=["1", "2"])

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
