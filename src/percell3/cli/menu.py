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
        MenuItem("5", "Measure channels", _measure_channels, enabled=True),
        MenuItem("6", "Apply threshold", _apply_threshold, enabled=True),
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
    """Interactively import TIFF images using table-first assignment."""
    store = state.require_experiment()

    # 1. Get source path (and optionally an explicit file list)
    source_str, source_files = _prompt_source_path()
    if source_str is None:
        raise _MenuCancel()

    source = Path(source_str)

    # Scan source
    from percell3.io import FileScanner
    from percell3.cli.import_cmd import (
        build_file_groups,
        next_fov_number,
        show_file_group_table,
        _run_import,
        _show_preview,
    )

    scanner = FileScanner()
    try:
        scan_result = scanner.scan(source, files=source_files)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    # 2. Build and display file groups
    groups = build_file_groups(scan_result)
    if not groups:
        console.print("[red]No file groups found.[/red]")
        return

    _show_preview(scan_result, str(source))
    show_file_group_table(groups)

    # 3. Channel mapping with auto-match
    channel_maps: tuple[str, ...] = ()
    if scan_result.channels:
        existing_channels = [ch.name for ch in store.get_channels()]
        maps = _auto_match_channels(scan_result.channels, existing_channels)
        if maps:
            channel_maps = tuple(maps)

    # 4. Z-projection
    z_method = "mip"
    if scan_result.z_slices:
        console.print("\n[bold]Z-projection method:[/bold]")
        z_method = numbered_select_one(
            ["mip", "sum", "mean", "keep"],
            "Z-projection method",
        )

    # 5. Assignment loop
    condition_map: dict[str, str] = {}
    fov_names: dict[str, str] = {}
    bio_rep_map: dict[str, str] = {}
    assigned: set[int] = set()

    if len(groups) == 1:
        # Single-group fast path
        g = groups[0]
        condition = _prompt_condition_for_assignment(store)
        bio_rep = _prompt_bio_rep_for_assignment(store, condition)
        next_num = next_fov_number(store, condition, bio_rep)
        condition_map[g.token] = condition
        fov_names[g.token] = f"FOV_{next_num:03d}"
        bio_rep_map[g.token] = bio_rep
    else:
        while len(assigned) < len(groups):
            # Show unassigned groups
            unassigned = [(i, g) for i, g in enumerate(groups) if i not in assigned]
            console.print(f"\nUnassigned file groups ({len(unassigned)} remaining):")
            _show_unassigned_groups(unassigned)

            # Select groups
            try:
                selection_str = menu_prompt(
                    "Select groups (numbers, 'all', or 'done')"
                )
            except _MenuCancel:
                break

            if selection_str.lower() == "done":
                break

            selected_indices = _parse_group_selection(selection_str, unassigned)
            if not selected_indices:
                continue

            # Assign condition (with back-navigation safety)
            try:
                condition = _prompt_condition_for_assignment(store)
            except _MenuCancel:
                continue

            # Assign bio rep (with back-navigation safety)
            try:
                bio_rep = _prompt_bio_rep_for_assignment(store, condition)
            except _MenuCancel:
                continue

            # Auto-number FOVs within (condition, bio_rep) scope
            existing_count = next_fov_number(store, condition, bio_rep)
            already_assigned = sum(
                1 for t, c in condition_map.items()
                if c == condition and bio_rep_map.get(t) == bio_rep
            )
            base_num = existing_count + already_assigned

            for offset, idx in enumerate(selected_indices):
                g = groups[idx]
                condition_map[g.token] = condition
                fov_names[g.token] = f"FOV_{base_num + offset:03d}"
                bio_rep_map[g.token] = bio_rep
                assigned.add(idx)

            # Show updated table with assignments
            assignments = {
                t: (condition_map[t], bio_rep_map[t], fov_names[t])
                for t in condition_map
            }
            show_file_group_table(groups, assignments=assignments)

    if not condition_map:
        console.print("[yellow]No groups assigned. Import cancelled.[/yellow]")
        return

    # 6. Show assignment summary and confirm
    _show_assignment_summary(condition_map, fov_names, bio_rep_map, groups)
    if numbered_select_one(["Yes", "No"], "Proceed with import?") != "Yes":
        console.print("[yellow]Import cancelled.[/yellow]")
        return

    # 7. Execute import
    default_condition = next(iter(condition_map.values()), "default")
    default_bio_rep = next(iter(bio_rep_map.values()), "N1")
    _run_import(
        store, str(source), default_condition, channel_maps, z_method,
        yes=True, bio_rep=default_bio_rep,
        condition_map=condition_map, fov_names=fov_names,
        bio_rep_map=bio_rep_map,
        source_files=source_files, scan_result=scan_result,
    )


def _prompt_condition_for_assignment(store: ExperimentStore) -> str:
    """Prompt for condition name, showing existing conditions as pick list.

    Creates the condition in the store if it doesn't exist yet, so
    downstream queries (bio reps, FOV numbering) can reference it.
    """
    from percell3.core.exceptions import DuplicateError

    existing = store.get_conditions()
    if existing:
        options = existing + ["(new condition)"]
        console.print("\n[bold]Conditions:[/bold]")
        choice = numbered_select_one(options, "Condition")
        if choice == "(new condition)":
            while True:
                name = menu_prompt("New condition name")
                try:
                    store.add_condition(name)
                except DuplicateError:
                    pass
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
                    continue
                return name
        return choice
    while True:
        name = menu_prompt("Condition name")
        try:
            store.add_condition(name)
        except DuplicateError:
            pass
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            continue
        return name


def _prompt_bio_rep_for_assignment(store: ExperimentStore, condition: str) -> str:
    """Prompt for bio rep, showing existing bio reps for the chosen condition."""
    existing = store.get_bio_reps(condition=condition)
    if existing:
        options = existing + ["(new bio rep)"]
        console.print(f"\n[bold]Bio reps for '{condition}':[/bold]")
        choice = numbered_select_one(options, "Biological replicate")
        if choice == "(new bio rep)":
            return menu_prompt("New bio rep name", default="N1")
        return choice
    return menu_prompt("Biological replicate", default="N1")


def _show_unassigned_groups(unassigned: list[tuple[int, object]]) -> None:
    """Print unassigned groups as a numbered list."""
    for i, (_, g) in enumerate(unassigned, 1):
        console.print(f"  \\[{i}] {g.token}")


def _parse_group_selection(
    selection: str,
    unassigned: list[tuple[int, object]],
) -> list[int]:
    """Parse user selection into list of original group indices.

    Returns empty list on invalid input (caller should re-prompt).
    """
    if selection.lower() == "all":
        return [idx for idx, _ in unassigned]

    parts = selection.split()
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        console.print("[red]Enter numbers separated by spaces, 'all', or 'done'.[/red]")
        return []

    if any(n < 1 or n > len(unassigned) for n in nums):
        console.print(f"[red]Numbers must be 1-{len(unassigned)}.[/red]")
        return []

    # Map 1-based selection to original indices
    return [unassigned[n - 1][0] for n in nums]


def _show_assignment_summary(
    condition_map: dict[str, str],
    fov_names: dict[str, str],
    bio_rep_map: dict[str, str],
    groups: list[object],
) -> None:
    """Display final assignment summary before confirmation."""
    from rich.table import Table as RichTable

    console.print("\n[bold]Assignment Summary[/bold]\n")

    table = RichTable(show_header=True)
    table.add_column("File group")
    table.add_column("Condition", style="cyan")
    table.add_column("Bio Rep", style="green")
    table.add_column("FOV Name", style="yellow")

    for g in groups:
        if g.token in condition_map:
            table.add_row(
                g.token,
                condition_map[g.token],
                bio_rep_map.get(g.token, "N1"),
                fov_names.get(g.token, g.token),
            )
        else:
            table.add_row(g.token, "[dim]skipped[/dim]", "", "")

    console.print(table)


# ---------------------------------------------------------------------------
# Segmentation helpers
# ---------------------------------------------------------------------------


def _build_model_list() -> list[str]:
    """Return ordered list of Cellpose models with cpsam first."""
    from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS

    rest = sorted(KNOWN_CELLPOSE_MODELS - {"cpsam"})
    return ["cpsam"] + rest


def _show_fov_status_table(
    fovs: list,
    seg_summary: dict[int, tuple[int, str | None]],
) -> None:
    """Display a numbered table of FOVs with segmentation status."""
    from rich.table import Table

    table = Table(show_header=True, title="FOVs in experiment")
    table.add_column("#", style="bold", width=4)
    table.add_column("FOV")
    table.add_column("Condition")
    table.add_column("Bio Rep")
    table.add_column("Shape")
    table.add_column("Cells", justify="right")
    table.add_column("Model")

    for i, f in enumerate(fovs, 1):
        cell_count, model_name = seg_summary.get(f.id, (0, None))
        shape = f"{f.width} x {f.height}" if f.width and f.height else "-"
        table.add_row(
            str(i),
            f.name,
            f.condition,
            f.bio_rep,
            shape,
            str(cell_count) if cell_count > 0 else "-",
            model_name or "-",
        )

    console.print(table)


def _select_fovs_from_table(fovs: list) -> list:
    """Prompt user to select FOVs by number from the displayed table.

    Supports space-separated numbers, 'all', and blank (= all).
    """
    while True:
        raw = menu_prompt(
            "Select FOVs (numbers, 'all', or blank=all)", default="all"
        )
        if raw.lower() == "all":
            return list(fovs)

        parts = raw.split()
        try:
            indices = sorted({int(p) for p in parts})
        except ValueError:
            console.print("[red]Enter numbers separated by spaces, or 'all'.[/red]")
            continue

        if any(i < 1 or i > len(fovs) for i in indices):
            console.print(f"[red]Numbers must be 1-{len(fovs)}.[/red]")
            continue

        if not indices:
            continue

        return [fovs[i - 1] for i in indices]


def _segment_cells(state: MenuState) -> None:
    """Interactively run cell segmentation with table-first FOV selection."""
    store = state.require_experiment()

    # 1. Channel selection
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    console.print("\n[bold]Available channels:[/bold]")
    ch_names = [ch.name for ch in channels]
    channel = numbered_select_one(ch_names, "Channel to segment")

    # 2. Check FOVs exist (early exit)
    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    # 3. Model selection (numbered list)
    models = _build_model_list()
    console.print("\n[bold]Segmentation model:[/bold]")
    model = numbered_select_one(models, "Model")

    # 4. Diameter
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

    # 5. FOV status table + selection
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)

    if len(all_fovs) == 1:
        console.print(f"  [dim](auto-selected: {all_fovs[0].name})[/dim]")
        selected_fovs = all_fovs
    else:
        selected_fovs = _select_fovs_from_table(all_fovs)

    # 6. Confirmation with re-segmentation warning
    reseg_fovs = [
        f for f in selected_fovs
        if seg_summary.get(f.id, (0, None))[0] > 0
    ]

    console.print(f"\n[bold]Segmentation settings:[/bold]")
    console.print(f"  Channel:  {channel}")
    console.print(f"  Model:    {model}")
    console.print(f"  Diameter: {diameter or 'auto-detect'}")
    console.print(f"  FOVs:     {len(selected_fovs)} selected")

    if reseg_fovs:
        console.print(
            f"  [yellow]Re-segment:[/yellow] {len(reseg_fovs)} FOV(s) "
            "with existing cells will be replaced"
        )
        for f in reseg_fovs[:5]:
            count = seg_summary[f.id][0]
            console.print(f"    - {f.name}/{f.condition} ({count} cells)")
        if len(reseg_fovs) > 5:
            console.print(f"    ... and {len(reseg_fovs) - 5} more")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Segmentation cancelled.[/yellow]")
        return

    # 7. Run segmentation
    from percell3.segment import SegmentationEngine

    engine = SegmentationEngine()
    fov_names = [f.name for f in selected_fovs]

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
            fovs=fov_names,
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

    # Auto-measure all channels on the just-segmented FOVs
    if result.cell_count > 0:
        try:
            all_channels = store.get_channels()
            ch_names = [ch.name for ch in all_channels]
            console.print(f"\n[bold]Auto-measuring {len(ch_names)} channels...[/bold]")

            from percell3.measure.measurer import Measurer as _AutoMeasurer

            auto_measurer = _AutoMeasurer()
            total_auto = 0

            with make_progress() as auto_progress:
                auto_task = auto_progress.add_task(
                    "Measuring...", total=len(selected_fovs),
                )
                for ai, fov_info in enumerate(selected_fovs):
                    count = auto_measurer.measure_fov(
                        store,
                        fov=fov_info.name,
                        condition=fov_info.condition,
                        channels=ch_names,
                        bio_rep=fov_info.bio_rep,
                    )
                    total_auto += count
                    auto_progress.update(
                        auto_task, completed=ai + 1,
                        description=f"Measuring {fov_info.name}",
                    )

            n_metrics = len(_AutoMeasurer()._metrics.list_metrics())
            console.print(
                f"  Measured {n_metrics} metrics x {len(ch_names)} channels "
                f"for {result.cell_count} cells"
            )
        except Exception as exc:
            console.print(
                f"  [yellow]Auto-measure warning:[/yellow] {exc}"
            )

    console.print()


def _view_napari(state: MenuState) -> None:
    """Launch napari to view and edit segmentation labels."""
    store = state.require_experiment()

    # Select condition first (bio reps are scoped per condition)
    conditions = store.get_conditions()
    if not conditions:
        console.print("[red]No conditions found.[/red] Import images first.")
        return

    console.print("\n[bold]Conditions:[/bold]")
    condition = numbered_select_one(conditions, "Condition")

    # Select biological replicate (scoped to condition)
    bio_rep = _prompt_bio_rep(store, condition=condition)

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


def _measure_channels(state: MenuState) -> None:
    """Interactively measure cells — whole-cell or mask-based modes."""
    store = state.require_experiment()

    # Prerequisites
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    cell_count = store.get_cell_count()
    if cell_count == 0:
        console.print("[red]No cells found.[/red] Run segmentation first.")
        return

    # Mode selection
    console.print("\n[bold]Measurement mode:[/bold]")
    modes = [
        "Whole cell (all channels, all metrics)",
        "Inside threshold mask",
        "Outside threshold mask",
        "Both inside + outside mask",
    ]
    mode = numbered_select_one(modes, "Mode")

    if mode.startswith("Whole"):
        _measure_whole_cell(store, channels, all_fovs)
    else:
        # Determine scopes
        if "Inside" in mode:
            scopes = ["mask_inside"]
        elif "Outside" in mode:
            scopes = ["mask_outside"]
        else:
            scopes = ["mask_inside", "mask_outside"]
        _measure_masked(store, channels, all_fovs, scopes)


def _measure_whole_cell(store, channels, all_fovs) -> None:
    """Run whole-cell measurement across all channels."""
    # Channel selection
    ch_names = [ch.name for ch in channels]
    console.print("\n[bold]Channels to measure:[/bold]")
    selected_channels = numbered_select_many(ch_names, "Channels (numbers, 'all')")

    # FOV selection
    seg_summary = store.get_fov_segmentation_summary()
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red]")
        return

    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    # Confirmation
    console.print(f"\n[bold]Measurement settings:[/bold]")
    console.print(f"  Mode:     Whole cell")
    console.print(f"  Channels: {', '.join(selected_channels)}")
    console.print(f"  FOVs:     {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Measurement cancelled.[/yellow]")
        return

    # Run BatchMeasurer
    from percell3.measure.batch import BatchMeasurer

    batch = BatchMeasurer()

    # Filter to selected FOV conditions for per-FOV measurement
    with make_progress() as progress:
        task = progress.add_task("Measuring...", total=len(selected_fovs))

        from percell3.measure.measurer import Measurer

        measurer = Measurer()
        total_measurements = 0

        for i, fov_info in enumerate(selected_fovs):
            count = measurer.measure_fov(
                store,
                fov=fov_info.name,
                condition=fov_info.condition,
                channels=selected_channels,
                bio_rep=fov_info.bio_rep,
            )
            total_measurements += count
            progress.update(
                task, completed=i + 1,
                description=f"Measuring {fov_info.name}",
            )

    console.print(f"\n[green]Measurement complete[/green]")
    console.print(f"  FOVs:         {len(selected_fovs)}")
    console.print(f"  Channels:     {len(selected_channels)}")
    console.print(f"  Measurements: {total_measurements}")
    console.print()


def _measure_masked(store, channels, all_fovs, scopes: list[str]) -> None:
    """Run mask-based measurement using threshold masks."""
    # Check for threshold runs
    threshold_runs = store.get_threshold_runs()
    if not threshold_runs:
        console.print(
            "[red]No threshold runs found.[/red] "
            "Run 'Apply threshold' (menu 6) first."
        )
        return

    # Group threshold runs by channel, pick most recent per channel
    runs_by_channel: dict[str, dict] = {}
    for run in threshold_runs:
        runs_by_channel[run["channel"]] = run  # last wins = most recent

    # Select threshold channel
    thresh_channels = list(runs_by_channel.keys())
    console.print("\n[bold]Threshold channels available:[/bold]")
    threshold_channel = numbered_select_one(thresh_channels, "Threshold channel")
    selected_run = runs_by_channel[threshold_channel]
    threshold_run_id = selected_run["id"]

    # Select measurement channels
    ch_names = [ch.name for ch in channels]
    console.print("\n[bold]Channels to measure:[/bold]")
    selected_channels = numbered_select_many(ch_names, "Channels (numbers, 'all')")

    # FOV selection — only FOVs with cells
    seg_summary = store.get_fov_segmentation_summary()
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red]")
        return

    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    scope_label = " + ".join(s.replace("mask_", "") for s in scopes)
    console.print(f"\n[bold]Measurement settings:[/bold]")
    console.print(f"  Mode:      Mask-based ({scope_label})")
    console.print(f"  Threshold: {threshold_channel} (run #{threshold_run_id})")
    console.print(f"  Channels:  {', '.join(selected_channels)}")
    console.print(f"  FOVs:      {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Measurement cancelled.[/yellow]")
        return

    # Run masked measurement per FOV
    from percell3.measure.measurer import Measurer

    measurer = Measurer()
    total_measurements = 0
    fovs_processed = 0
    warnings: list[str] = []

    with make_progress() as progress:
        task = progress.add_task("Measuring...", total=len(selected_fovs))

        for i, fov_info in enumerate(selected_fovs):
            try:
                count = measurer.measure_fov_masked(
                    store,
                    fov=fov_info.name,
                    condition=fov_info.condition,
                    channels=selected_channels,
                    threshold_channel=threshold_channel,
                    threshold_run_id=threshold_run_id,
                    scopes=scopes,
                    bio_rep=fov_info.bio_rep,
                )
                total_measurements += count
                fovs_processed += 1
            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                warnings.append(f"{fov_info.name}: {exc}")

            progress.update(
                task, completed=i + 1,
                description=f"Measuring {fov_info.name}",
            )

    console.print(f"\n[green]Masked measurement complete[/green]")
    console.print(f"  FOVs:         {fovs_processed}")
    console.print(f"  Channels:     {len(selected_channels)}")
    console.print(f"  Scopes:       {scope_label}")
    console.print(f"  Measurements: {total_measurements}")

    if warnings:
        console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
        for w in warnings:
            console.print(f"  [dim]- {w}[/dim]")
    console.print()


def _apply_threshold(state: MenuState) -> None:
    """Interactively run cell grouping + threshold QC + particle analysis."""
    store = state.require_experiment()

    # 1. Check prerequisites
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    cell_count = store.get_cell_count()
    if cell_count == 0:
        console.print("[red]No cells found.[/red] Run segmentation first.")
        return

    # 2. Grouping channel + metric selection
    ch_names = [ch.name for ch in channels]
    console.print("\n[bold]Step 1: Cell Grouping[/bold]")
    console.print("\n[bold]Channel for grouping metric:[/bold]")
    grouping_channel = numbered_select_one(ch_names, "Grouping channel")

    metrics = ["mean_intensity", "median_intensity", "integrated_intensity", "area_pixels"]
    console.print("\n[bold]Metric for grouping:[/bold]")
    grouping_metric = numbered_select_one(metrics, "Grouping metric")

    # 3. Threshold channel selection
    console.print("\n[bold]Step 2: Threshold Channel[/bold]")
    console.print(f"  [dim]Default: same as grouping ({grouping_channel})[/dim]")
    threshold_ch_options = ch_names + [f"(same as grouping: {grouping_channel})"]
    console.print("\n[bold]Channel to threshold:[/bold]")
    threshold_channel = numbered_select_one(threshold_ch_options, "Threshold channel")
    if threshold_channel.startswith("(same"):
        threshold_channel = grouping_channel

    # 4. FOV selection
    console.print("\n[bold]Step 3: Select FOVs[/bold]")
    seg_summary = store.get_fov_segmentation_summary()
    # Filter to FOVs that have cells
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red]")
        return

    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    # 5. Confirmation
    console.print(f"\n[bold]Thresholding settings:[/bold]")
    console.print(f"  Grouping:    {grouping_channel} / {grouping_metric}")
    console.print(f"  Threshold:   {threshold_channel} (Otsu)")
    console.print(f"  FOVs:        {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Thresholding cancelled.[/yellow]")
        return

    # 6. Run per-FOV
    from percell3.measure.cell_grouper import CellGrouper
    from percell3.measure.particle_analyzer import ParticleAnalyzer
    from percell3.measure.thresholding import ThresholdEngine

    grouper = CellGrouper()
    engine = ThresholdEngine()
    analyzer = ParticleAnalyzer()

    total_particles = 0
    fovs_processed = 0
    skip_remaining_fovs = False

    for fov_info in selected_fovs:
        if skip_remaining_fovs:
            break

        fov = fov_info.name
        condition = fov_info.condition
        bio_rep = fov_info.bio_rep

        console.print(f"\n[bold]{'='*60}[/bold]")
        console.print(f"[bold]FOV: {fov} ({condition}/{bio_rep})[/bold]")

        # 6a. Group cells
        try:
            grouping_result = grouper.group_cells(
                store, fov=fov, condition=condition,
                channel=grouping_channel, metric=grouping_metric,
                bio_rep=bio_rep,
            )
        except ValueError as e:
            console.print(f"  [yellow]Skipping: {e}[/yellow]")
            continue

        console.print(f"  Groups found: {grouping_result.n_groups}")
        for i, (tag, mean) in enumerate(
            zip(grouping_result.tag_names, grouping_result.group_means)
        ):
            n_cells = int((grouping_result.group_labels == i).sum())
            console.print(f"    {tag}: {n_cells} cells (mean={mean:.1f})")

        # 6b. Read images and labels for this FOV
        import numpy as np
        labels = store.read_labels(fov, condition, bio_rep=bio_rep)
        image = store.read_image_numpy(
            fov, condition, threshold_channel, bio_rep=bio_rep,
        )

        accepted_groups: list[tuple[str, list[int], int]] = []  # (tag, cell_ids, run_id)
        skip_remaining_groups = False

        for i, tag_name in enumerate(grouping_result.tag_names):
            if skip_remaining_groups:
                break

            group_cell_ids = [
                cid for cid, label in zip(
                    grouping_result.cell_ids, grouping_result.group_labels
                )
                if label == i
            ]
            if not group_cell_ids:
                continue

            # Get label values for this group
            cells_df = store.get_cells(condition=condition, bio_rep=bio_rep, fov=fov)
            group_cells = cells_df[cells_df["id"].isin(group_cell_ids)]
            label_values = group_cells["label_value"].tolist()

            from percell3.measure.threshold_viewer import (
                compute_masked_otsu,
                create_group_image,
            )

            group_image, cell_mask = create_group_image(image, labels, label_values)

            # Compute initial Otsu
            try:
                initial_thresh = compute_masked_otsu(group_image, cell_mask)
            except ValueError:
                console.print(f"  [yellow]{tag_name}: no pixels to threshold, skipping[/yellow]")
                continue

            # Launch napari viewer
            group_display = f"{tag_name} (mean={grouping_result.group_means[i]:.1f})"
            console.print(f"\n  Opening napari for {group_display}...")
            console.print(f"  [dim]Initial Otsu threshold: {initial_thresh:.1f}[/dim]")

            try:
                from percell3.measure.threshold_viewer import launch_threshold_viewer

                decision = launch_threshold_viewer(
                    group_image, cell_mask,
                    group_name=group_display,
                    fov_name=fov,
                    initial_threshold=initial_thresh,
                )
            except (ImportError, RuntimeError) as exc:
                console.print(f"  [red]napari error:[/red] {exc}")
                console.print("  [dim]Falling back to auto-accept with Otsu threshold.[/dim]")
                # Auto-accept fallback
                from percell3.measure.threshold_viewer import ThresholdDecision
                decision = ThresholdDecision(
                    accepted=True, threshold_value=initial_thresh,
                )

            if decision.skip_remaining:
                console.print(f"  [yellow]Skipping remaining groups for {fov}[/yellow]")
                skip_remaining_groups = True
                continue

            if not decision.accepted:
                console.print(f"  [dim]Skipped {tag_name}[/dim]")
                continue

            # Store threshold result
            result = engine.threshold_group(
                store, fov=fov, condition=condition, channel=threshold_channel,
                cell_ids=group_cell_ids,
                labels=labels, image=image,
                threshold_value=decision.threshold_value,
                roi=decision.roi,
                group_tag=tag_name,
                bio_rep=bio_rep,
            )
            console.print(
                f"  [green]Accepted {tag_name}[/green]: "
                f"threshold={result.threshold_value:.1f}, "
                f"positive={result.positive_fraction:.1%}"
            )
            accepted_groups.append((tag_name, group_cell_ids, result.threshold_run_id))

        # 6c. Particle analysis for accepted groups
        if accepted_groups:
            console.print(f"\n  [bold]Particle analysis...[/bold]")

            for tag_name, group_cell_ids, thr_run_id in accepted_groups:
                pa_result = analyzer.analyze_fov(
                    store, fov=fov, condition=condition,
                    channel=threshold_channel,
                    threshold_run_id=thr_run_id,
                    cell_ids=group_cell_ids,
                    bio_rep=bio_rep,
                )

                # Store results
                if pa_result.particles:
                    store.add_particles(pa_result.particles)
                if pa_result.summary_measurements:
                    store.add_measurements(pa_result.summary_measurements)
                store.write_particle_labels(
                    fov, condition, threshold_channel,
                    pa_result.particle_label_image,
                    bio_rep=bio_rep,
                )

                console.print(
                    f"    {tag_name}: {pa_result.total_particles} particles "
                    f"in {pa_result.cells_analyzed} cells"
                )
                total_particles += pa_result.total_particles
        else:
            console.print(f"  [dim]No groups accepted — skipping particle analysis.[/dim]")

        fovs_processed += 1

    # 7. Summary
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[green]Thresholding complete[/green]")
    console.print(f"  FOVs processed: {fovs_processed}")
    console.print(f"  Total particles: {total_particles}")
    console.print()


def _prompt_bio_rep(store: ExperimentStore, condition: str | None = None) -> str:
    """Prompt for biological replicate. Auto-resolves when only 1 exists."""
    reps = store.get_bio_reps(condition=condition)
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
        if numbered_select_one(["No", "Yes"], "Rename channels?") == "Yes":
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
        # Optional condition filter for bio reps
        cond_filter = None
        cond_list = store.get_conditions()
        if len(cond_list) > 1:
            console.print("\n[bold]Conditions:[/bold]")
            _print_numbered_list(cond_list)
            cond_str = menu_prompt("Condition filter (number, or blank = all)", default="")
            if cond_str:
                try:
                    idx = int(cond_str)
                    if 1 <= idx <= len(cond_list):
                        cond_filter = cond_list[idx - 1]
                except ValueError:
                    cond_filter = cond_str

        rep_list = store.get_bio_reps(condition=cond_filter)
        if not rep_list:
            console.print("[dim]No biological replicates found.[/dim]")
            return
        rows = [{"name": r} for r in rep_list]
        title = f"Biological Replicates ({cond_filter})" if cond_filter else "Biological Replicates"
        format_output(rows, ["name"], "table", title)


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
        # Bio reps are scoped per condition — select condition first
        conditions = store.get_conditions()
        if not conditions:
            console.print("[dim]No conditions found.[/dim]")
            return
        console.print("\n[bold]Conditions:[/bold]")
        cond = numbered_select_one(conditions, "Condition")
        reps = store.get_bio_reps(condition=cond)
        if not reps:
            console.print("[dim]No biological replicates found.[/dim]")
            return
        console.print("\n[bold]Biological replicates:[/bold]")
        old = numbered_select_one(reps, "Bio-rep to rename")
        new_name = menu_prompt(f"New name for '{old}'")
        store.rename_bio_rep(old, new_name, condition=cond)
        console.print(f"[green]Bio-rep '{old}' → '{new_name}'[/green]")


def _export_csv(state: MenuState) -> None:
    """Interactively export measurements to CSV."""
    store = state.require_experiment()

    output_str = menu_prompt("Output CSV path")

    out_path = Path(output_str).expanduser()

    if out_path.exists():
        if numbered_select_one(["No", "Yes"], "File exists. Overwrite?") != "Yes":
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
