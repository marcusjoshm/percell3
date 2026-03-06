"""Interactive menu for PerCell 3 CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from percell3.cli.menu_system import Menu, MenuItem
from percell3.cli.utils import console, make_progress, open_experiment

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


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


def _flush_stdin() -> None:
    """Discard any buffered stdin data (e.g. trailing newlines from paste)."""
    import select
    import sys

    try:
        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.read(1)
    except Exception:
        pass  # Not all platforms support select on stdin


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
    _flush_stdin()

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
    prompt: str = "Select (numbers, 'all', or blank=all)",
) -> list[str]:
    """Display a numbered list and return selected items.

    Supports space-separated numbers, 'all', and blank (= all).

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    if not items:
        raise ValueError("numbered_select_many called with empty list")

    _print_numbered_list(items)

    while True:
        raw = menu_prompt(prompt, default="all")

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


def _print_numbered_list(items: list[str], *, page_size: int = 999) -> None:
    """Print items as a numbered list, paginating if needed."""
    show = items if len(items) <= page_size else items[:page_size]
    for i, item in enumerate(show, 1):
        console.print(f"  \\[{i}] {item}")
    if len(items) > page_size:
        remaining = len(items) - page_size
        console.print(f"  [dim]... and {remaining} more (enter number to select)[/dim]")


_PREFIX_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")


def _prompt_prefix(
    fov_names: list[str],
    suffix_example: str = "",
) -> str:
    """Prompt for a naming prefix, validate, and show a preview.

    Args:
        fov_names: Display names of the FOVs that will be named.
        suffix_example: Example suffix appended after the FOV name (e.g. ``"g1"``).

    Returns:
        The validated prefix string.

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    max_fov_len = max(len(n) for n in fov_names) if fov_names else 0

    while True:
        raw = menu_prompt("Naming prefix (e.g. 'Round1')")

        if not _PREFIX_RE.match(raw):
            console.print(
                "[red]Invalid prefix.[/red] "
                "Use letters, digits, underscores, or hyphens (1-50 chars, "
                "start with letter or digit)."
            )
            continue

        # Check composed name length
        sep = "_"
        suffix_part = f"{sep}{suffix_example}" if suffix_example else ""
        max_len = len(raw) + len(sep) + max_fov_len + len(suffix_part)
        if max_len > 255:
            console.print(
                f"[red]Prefix too long.[/red] Composed name would be {max_len} "
                f"chars (max 255). Use a shorter prefix."
            )
            continue

        # Preview
        preview_fov = fov_names[0] if fov_names else "FOV"
        preview = f"{raw}{sep}{preview_fov}{suffix_part}"
        console.print(f"  [dim]Preview: {preview}[/dim]")
        return raw


def _prompt_path(
    prompt: str,
    *,
    mode: str = "dir",
    title: str | None = None,
) -> str:
    """Prompt for a path with an optional native file picker.

    Args:
        prompt: Text prompt to display.
        mode: "dir" for folder picker, "file" for open file, "save" for save dialog.
        title: Dialog title for the native picker.

    Returns:
        The selected path string.

    Raises:
        _MenuHome / _MenuCancel via menu_prompt.
    """
    console.print(f"\n[bold]{prompt}[/bold]")
    console.print("  \\[1] Type path")
    console.print("  \\[2] Browse")

    choice = menu_prompt("Select", choices=["1", "2"], default="1")

    if choice == "2":
        try:
            import tkinter as tk
            from tkinter import filedialog

            # Reuse a single hidden root to avoid broken dialogs on
            # subsequent calls (multiple Tk() instances corrupt state).
            if not hasattr(_prompt_path, "_tk_root") or not _prompt_path._tk_root.winfo_exists():
                _prompt_path._tk_root = tk.Tk()
                _prompt_path._tk_root.withdraw()
            root = _prompt_path._tk_root

            dialog_title = title or prompt
            root.lift()
            root.focus_force()
            if mode == "dir":
                result = filedialog.askdirectory(title=dialog_title, parent=root)
            elif mode == "save":
                result = filedialog.asksaveasfilename(
                    title=dialog_title,
                    parent=root,
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                )
            else:
                result = filedialog.askopenfilename(title=dialog_title, parent=root)
            if result:
                console.print(f"  [dim]Selected: {result}[/dim]")
                return result
            console.print("[dim]No selection made.[/dim]")
            raise _MenuCancel()
        except ImportError:
            console.print(
                "[yellow]tkinter not available.[/yellow] "
                "Please type the path instead."
            )

    return menu_prompt("Path")


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

    try:
        Menu("MAIN MENU", [
            MenuItem("1", "Setup", "Create and select experiments", _setup_menu),
            MenuItem("2", "Import", "Import LIF, TIFF, or CZI images", _import_menu),
            MenuItem("3", "Segment", "Single-cell segmentation with Cellpose", _segment_menu),
            MenuItem("4", "Analyze", "Measure, threshold, and analyze cells", _analyze_menu),
            MenuItem("5", "View", "View images and masks in napari", _view_menu),
            MenuItem("6", "Data", "Query, edit, and export experiment data", _data_menu),
            MenuItem("7", "Workflows", "Run automated analysis pipelines", _workflows_menu),
            MenuItem("8", "Plugins", "Extend functionality with plugins", _plugins_menu),
        ], state, show_banner=True).run()
    except KeyboardInterrupt:
        pass
    finally:
        state.close()


# ---------------------------------------------------------------------------
# Category sub-menus
# ---------------------------------------------------------------------------


def _setup_menu(state: MenuState) -> None:
    Menu("SETUP", [
        MenuItem("1", "Create experiment", "Create a new .percell experiment", _create_experiment),
        MenuItem("2", "Select experiment", "Open an existing experiment", _select_experiment),
    ], state, return_home=True).run()
    raise _MenuCancel()


def _import_menu(state: MenuState) -> None:
    Menu("IMPORT", [
        MenuItem("1", "Import images", "Load LIF, TIFF, or CZI files", _import_images),
        MenuItem("2", "Import from PerCell project", "Copy FOVs from another .percell experiment", _import_from_percell),
    ], state, return_home=True).run()
    raise _MenuCancel()


def _segment_menu(state: MenuState) -> None:
    Menu("SEGMENT", [
        MenuItem("1", "Segment cells", "Run Cellpose segmentation", _segment_cells),
    ], state).run()
    raise _MenuCancel()


def _analyze_menu(state: MenuState) -> None:
    Menu("ANALYZE", [
        MenuItem("1", "Measure channels", "Measure fluorescence intensities per cell", _measure_channels),
        MenuItem("2", "Grouped intensity thresholding", "Otsu thresholding and particle detection", _apply_threshold),
        MenuItem("3", "Config management", "Manage measurement configurations", _config_management_menu),
    ], state).run()
    raise _MenuCancel()


def _view_menu(state: MenuState) -> None:
    Menu("VIEW", [
        MenuItem("1", "View in napari", "Open images and masks in napari viewer", _view_napari),
    ], state).run()
    raise _MenuCancel()


def _data_menu(state: MenuState) -> None:
    Menu("DATA", [
        MenuItem("1", "Query experiment", "Inspect experiment data", _query_menu),
        MenuItem("2", "Edit experiment", "Rename conditions, FOVs, channels, bio-reps", _edit_menu),
        MenuItem("3", "Export to CSV", "Export measurements and particle data", _export_csv),
        MenuItem("4", "Export FOVs as TIFF", "Export images, labels, masks as TIFF files", _export_tiff),
    ], state).run()
    raise _MenuCancel()


def _workflows_menu(state: MenuState) -> None:
    Menu("WORKFLOWS", [
        MenuItem("1", "Particle analysis", "Segment → measure → threshold → export", _particle_workflow),
        MenuItem("2", "Decapping sensor", "10-step decapping sensor pipeline", _decapping_sensor_workflow),
    ], state).run()
    raise _MenuCancel()


def _plugins_menu(state: MenuState) -> None:
    """Plugin manager — discover and run analysis/visualization plugins."""
    from percell3.plugins.registry import PluginRegistry

    store = state.require_experiment()
    registry = PluginRegistry()
    registry.discover()
    analysis_plugins = registry.list_plugins()
    viz_plugins = registry.list_viz_plugins()

    if not analysis_plugins and not viz_plugins:
        console.print("\n[yellow]No plugins available.[/yellow]")
        return

    # Build menu items for each discovered plugin
    items: list[MenuItem] = []
    idx = 1
    for info in analysis_plugins:
        items.append(MenuItem(str(idx), info.name, info.description, _make_plugin_runner(registry, info.name)))
        idx += 1
    for info in viz_plugins:
        items.append(MenuItem(str(idx), info.name, info.description, _make_viz_runner(registry, info.name)))
        idx += 1

    Menu("PLUGINS", items, state).run()
    raise _MenuCancel()


def _make_plugin_runner(registry, plugin_name: str):
    """Create a handler function for a specific plugin."""
    def handler(state: MenuState) -> None:
        if plugin_name == "local_bg_subtraction":
            _run_bg_subtraction(state, registry)
        elif plugin_name == "split_halo_condensate_analysis":
            _run_condensate_analysis(state, registry)
        elif plugin_name == "image_calculator":
            _run_image_calculator(state, registry)
        elif plugin_name == "threshold_bg_subtraction":
            _run_threshold_bg_subtraction(state, registry)
        else:
            # Generic plugin runner for future plugins
            _run_generic_plugin(state, registry, plugin_name)
    return handler


def _run_generic_plugin(state: MenuState, registry, plugin_name: str) -> None:
    """Generic plugin runner — validates and runs without custom UI."""
    store = state.require_experiment()

    # Validate
    plugin = registry.get_plugin(plugin_name)
    errors = plugin.validate(store)
    if errors:
        console.print(f"\n[red]Plugin validation failed:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    # Run
    with make_progress() as progress:
        task = progress.add_task(f"Running {plugin_name}...", total=None)

        def on_progress(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        result = registry.run_plugin(plugin_name, store, progress_callback=on_progress)

    console.print(f"\n[green]Plugin complete[/green]")
    console.print(f"  Cells processed: {result.cells_processed}")
    console.print(f"  Measurements written: {result.measurements_written}")
    if result.custom_outputs:
        for key, val in result.custom_outputs.items():
            console.print(f"  {key}: {val}")
    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")


def _run_image_calculator(state: MenuState, registry) -> None:
    """Interactive handler for Image Calculator plugin."""
    from percell3.plugins.builtin.image_calculator_core import OPERATIONS

    store = state.require_experiment()

    plugin = registry.get_plugin("image_calculator")
    errors = plugin.validate(store)
    if errors:
        console.print("\n[red]Cannot run image calculator:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    # Step 1: Mode
    console.print("\n[bold]Step 1: Mode[/bold]")
    console.print("  [dim]Single channel (with constant) or two channel (between images).[/dim]\n")
    mode = numbered_select_one(["single_channel", "two_channel"], "Mode")

    # Step 2: Operation
    console.print("\n[bold]Step 2: Operation[/bold]")
    console.print("  [dim]Select the arithmetic operation to apply.[/dim]\n")
    operation = numbered_select_one(list(OPERATIONS), "Operation")

    # Step 3: FOV
    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("\n[red]No FOVs found.[/red]")
        return

    console.print("\n[bold]Step 3: Select FOV[/bold]\n")
    fov_names = [f.display_name for f in all_fovs]
    chosen_name = numbered_select_one(fov_names, "FOV")
    fov_id = next(f.id for f in all_fovs if f.display_name == chosen_name)

    # Step 4: Channel A
    channels = store.get_channels()
    ch_names = [ch.name for ch in channels]

    console.print("\n[bold]Step 4: Channel A[/bold]")
    console.print("  [dim]Primary channel to operate on.[/dim]\n")
    channel_a = numbered_select_one(ch_names, "Channel A")

    # Step 5: Channel B or constant
    params: dict = {
        "mode": mode,
        "operation": operation,
        "fov_id": fov_id,
        "channel_a": channel_a,
    }

    if mode == "single_channel":
        console.print("\n[bold]Step 5: Constant[/bold]")
        console.print("  [dim]Scalar value to apply with the operation.[/dim]")
        raw = menu_prompt("Constant value")
        try:
            params["constant"] = float(raw)
        except ValueError:
            console.print(f"[red]Invalid number: {raw!r}[/red]")
            return
    else:
        console.print("\n[bold]Step 5: Channel B[/bold]")
        console.print("  [dim]Second channel for the operation.[/dim]\n")
        params["channel_b"] = numbered_select_one(ch_names, "Channel B")

    # Naming prefix
    console.print("\n[bold]Naming Prefix[/bold]")
    console.print("  [dim]Enter a prefix for the derived FOV name.[/dim]")
    operand = str(params.get("constant", params.get("channel_b", "")))
    suffix_ex = f"{params['operation']}_{operand}"
    name_prefix = _prompt_prefix([chosen_name], suffix_example=suffix_ex)
    params["name_prefix"] = name_prefix

    # Run
    with make_progress() as progress:
        task = progress.add_task(f"Running image calculator...", total=None)

        def on_progress(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        result = registry.run_plugin(
            "image_calculator", store, parameters=params,
            progress_callback=on_progress,
        )

    console.print("\n[green]Image calculator complete[/green]")
    derived_fov_id = result.custom_outputs.get("derived_fov_id")
    if derived_fov_id:
        console.print(f"  Derived FOV ID: {derived_fov_id}")
    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")


def _run_threshold_bg_subtraction(state: MenuState, registry) -> None:
    """Interactive handler for threshold-layer background subtraction plugin.

    Two-FOV workflow:
      Step 1: Select channel
      Step 2: Select histogram FOVs (dilute-phase, with thresholds)
      Step 3: For each histogram FOV, pick the apply FOV
      Step 4: Confirmation summary
      Step 5: Execute + summary
    """
    from rich.table import Table

    store = state.require_experiment()

    # Validate prerequisites
    plugin = registry.get_plugin("threshold_bg_subtraction")
    errors = plugin.validate(store)
    if errors:
        console.print("\n[red]Cannot run threshold background subtraction:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    # Step 1: Channel selection
    channels = store.get_channels()
    ch_names = [ch.name for ch in channels]

    console.print("\n[bold]Step 1: Channel[/bold]")
    console.print(
        "  [dim]Select the channel for histogram estimation "
        "and background subtraction.[/dim]\n"
    )
    channel = numbered_select_one(ch_names, "Channel")

    # Step 2: Select histogram FOVs — filter to those with configured thresholds
    console.print("\n[bold]Step 2: Select histogram FOVs[/bold]")
    console.print(
        "  [dim]These are the dilute-phase FOVs used to estimate background.[/dim]"
    )
    all_fovs = store.get_fovs()
    fovs_with_thresholds = []
    for fov in all_fovs:
        fov_config = store.get_fov_config(fov.id)
        if any(entry.threshold_id is not None for entry in fov_config):
            fovs_with_thresholds.append(fov)

    if not fovs_with_thresholds:
        console.print(
            "\n[red]No FOVs have configured threshold layers.[/red]"
        )
        console.print(
            "[dim]Run 'Grouped intensity thresholding' first.[/dim]"
        )
        return

    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(fovs_with_thresholds, seg_summary)

    if len(fovs_with_thresholds) == 1:
        console.print(
            f"  [dim](auto-selected: {fovs_with_thresholds[0].display_name})[/dim]"
        )
        histogram_fovs = fovs_with_thresholds
    else:
        histogram_fovs = _select_fovs_from_table(fovs_with_thresholds)

    # Step 3: For each histogram FOV, pick the apply FOV
    console.print("\n[bold]Step 3: Pair each histogram FOV to an apply FOV[/bold]")
    console.print(
        "  [dim]Select which FOV receives the background subtraction.[/dim]"
    )

    # Build list of candidate apply FOVs (all FOVs except the histogram FOVs)
    histogram_fov_ids = {f.id for f in histogram_fovs}
    candidate_apply_fovs = [f for f in all_fovs if f.id not in histogram_fov_ids]

    if not candidate_apply_fovs:
        console.print(
            "\n[red]No other FOVs available as apply targets.[/red]"
        )
        return

    candidate_names = [f.display_name for f in candidate_apply_fovs]
    candidate_id_map = {f.display_name: f.id for f in candidate_apply_fovs}

    pairings: list[dict[str, int]] = []
    for idx, hist_fov in enumerate(histogram_fovs, 1):
        console.print(
            f"\n  Histogram FOV {idx} of {len(histogram_fovs)}: "
            f"[cyan]{hist_fov.display_name}[/cyan]"
        )
        apply_name = numbered_select_one(
            candidate_names, "  Apply FOV"
        )
        pairings.append({
            "histogram_fov_id": hist_fov.id,
            "apply_fov_id": candidate_id_map[apply_name],
        })

    # Step 4: Naming prefix
    console.print("\n[bold]Step 4: Naming Prefix[/bold]")
    console.print("  [dim]Enter a prefix for derived FOV names.[/dim]")
    apply_fov_names = [
        store.get_fov_by_id(p["apply_fov_id"]).display_name for p in pairings
    ]
    name_prefix = _prompt_prefix(apply_fov_names, suffix_example=channel)

    # Step 5: Confirmation summary
    console.print(f"\n[bold]Threshold background subtraction settings:[/bold]")
    console.print(f"  Channel:  {channel}")
    console.print(f"  Naming:   {name_prefix}_<FOV>_{channel}")
    console.print(f"  Pairings: {len(pairings)}")
    for p in pairings:
        hist_name = store.get_fov_by_id(p["histogram_fov_id"]).display_name
        apply_name = store.get_fov_by_id(p["apply_fov_id"]).display_name
        console.print(f"    {hist_name}  ->  {apply_name}")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Background subtraction cancelled.[/yellow]")
        return

    # Step 6: Run with progress
    parameters = {
        "channel": channel,
        "pairings": pairings,
        "name_prefix": name_prefix,
    }

    with make_progress() as progress:
        task = progress.add_task(
            "Background subtraction...", total=len(pairings),
        )

        def on_progress(current, total, fov_name):
            progress.update(
                task, total=total, completed=current,
                description=f"Processing {fov_name}",
            )

        result = registry.run_plugin(
            "threshold_bg_subtraction", store,
            parameters=parameters, progress_callback=on_progress,
        )

    # Step 6: Summary table
    console.print(f"\n[green]Threshold background subtraction complete[/green]")

    bg_entries = {
        k.removeprefix("bg_"): v
        for k, v in result.custom_outputs.items()
        if k.startswith("bg_")
    }
    if bg_entries:
        summary_table = Table(title="Background Subtraction Results")
        summary_table.add_column("Derived FOV", style="cyan")
        summary_table.add_column("BG Value", justify="right")
        for name, bg_val in bg_entries.items():
            summary_table.add_row(name, bg_val)
        console.print(summary_table)

    histograms_dir = result.custom_outputs.get("histograms_dir")
    if histograms_dir:
        console.print(f"  Histograms: {histograms_dir}")

    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")
    console.print()


def _run_bg_subtraction(state: MenuState, registry) -> None:
    """Interactive handler for local background subtraction plugin."""
    store = state.require_experiment()

    # Validate prerequisites
    plugin = registry.get_plugin("local_bg_subtraction")
    errors = plugin.validate(store)
    if errors:
        console.print(f"\n[red]Cannot run background subtraction:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    channels = store.get_channels()
    ch_names = [ch.name for ch in channels]

    # Step 1: Measurement channel
    console.print("\n[bold]Step 1: Measurement Channel[/bold]")
    console.print("  [dim]Select the channel to measure intensities from.[/dim]\n")
    meas_channel = numbered_select_one(ch_names, "Measurement channel")

    # Step 2: Particle mask channel
    # Find channels with threshold runs (i.e., particle masks exist)
    thresholds = store.get_thresholds()
    particle_channels = sorted({tr.source_channel for tr in thresholds if tr.source_channel})
    if not particle_channels:
        console.print("\n[red]No particle masks found.[/red]")
        console.print("[dim]Run 'Grouped intensity thresholding' first to generate particle masks.[/dim]")
        return

    console.print("\n[bold]Step 2: Particle Mask[/bold]")
    console.print("  [dim]Select the thresholded particle mask to dilate and measure.[/dim]\n")
    particle_channel = numbered_select_one(particle_channels, "Particle mask")

    # Step 3: Exclusion mask (optional)
    other_particle_channels = [c for c in particle_channels if c != particle_channel]
    exclusion_channel = None
    if other_particle_channels:
        console.print("\n[bold]Step 3: Exclusion Mask (optional)[/bold]")
        console.print("  [dim]Exclude another mask's particles from the background ring.[/dim]\n")
        choices = ["(none)"] + other_particle_channels
        choice = numbered_select_one(choices, "Exclusion mask")
        if choice != "(none)":
            exclusion_channel = choice
    else:
        console.print("\n[bold]Step 3: Exclusion Mask[/bold]")
        console.print("  [dim]No other particle masks available — skipping.[/dim]")

    # Step 4: Normalization channel (optional)
    normalization_channel = None
    console.print("\n[bold]Step 4: Normalization Channel (optional)[/bold]")
    console.print("  [dim]Report mean intensity from another channel inside each particle.[/dim]\n")
    norm_choices = ["(none)"] + ch_names
    norm_choice = numbered_select_one(norm_choices, "Normalization channel")
    if norm_choice != "(none)":
        normalization_channel = norm_choice

    # Step 5: Dilation
    console.print("\n[bold]Step 5: Ring Dilation[/bold]")
    dilation_str = menu_prompt("Dilation pixels", default="5")
    try:
        dilation_pixels = int(dilation_str)
    except ValueError:
        console.print("[yellow]Invalid number, using default of 5.[/yellow]")
        dilation_pixels = 5

    # Step 6: FOV selection
    console.print("\n[bold]Step 6: Select FOVs[/bold]")
    all_fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red]")
        return

    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    # Collect cell_ids from selected FOVs
    cell_ids = []
    for fov in selected_fovs:
        cells_df = store.get_cells(fov_id=fov.id)
        cell_ids.extend(cells_df["id"].tolist())

    # Step 7: Confirmation
    console.print(f"\n[bold]Background subtraction settings:[/bold]")
    console.print(f"  Measurement:     {meas_channel}")
    console.print(f"  Particle mask:   {particle_channel}")
    console.print(f"  Exclusion:       {exclusion_channel or '(none)'}")
    console.print(f"  Normalization:   {normalization_channel or '(none)'}")
    console.print(f"  Dilation:        {dilation_pixels} px")
    console.print(f"  FOVs:            {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Background subtraction cancelled.[/yellow]")
        return

    # Step 8: Run with progress
    parameters = {
        "measurement_channel": meas_channel,
        "particle_channel": particle_channel,
        "exclusion_channel": exclusion_channel,
        "normalization_channel": normalization_channel,
        "dilation_pixels": dilation_pixels,
    }

    with make_progress() as progress:
        task = progress.add_task("Background subtraction...", total=len(selected_fovs))

        def on_progress(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        result = registry.run_plugin(
            "local_bg_subtraction", store,
            cell_ids=cell_ids, parameters=parameters,
            progress_callback=on_progress,
        )

    # Step 9: Summary
    console.print(f"\n[green]Background subtraction complete[/green]")
    console.print(f"  Cells processed: {result.cells_processed}")
    console.print(f"  Particles measured: {result.measurements_written}")
    csv_outputs = {
        k: v for k, v in result.custom_outputs.items() if k.startswith("csv_")
    }
    if csv_outputs:
        console.print(f"  CSV files exported:")
        for key, path in csv_outputs.items():
            condition = key.removeprefix("csv_")
            console.print(f"    {condition}: {path}")
    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")
    console.print()


def _run_condensate_analysis(state: MenuState, registry) -> None:
    """Interactive handler for split-Halo condensate analysis plugin."""
    store = state.require_experiment()

    plugin = registry.get_plugin("split_halo_condensate_analysis")
    errors = plugin.validate(store)
    if errors:
        console.print(f"\n[red]Cannot run condensate analysis:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    channels = store.get_channels()
    ch_names = [ch.name for ch in channels]

    # Step 1: Measurement channel
    console.print("\n[bold]Step 1: Measurement Channel[/bold]")
    console.print("  [dim]Select the channel to measure intensities from.[/dim]\n")
    meas_channel = numbered_select_one(ch_names, "Measurement channel")

    # Step 2: Particle mask channel
    thresholds = store.get_thresholds()
    particle_channels = sorted({tr.source_channel for tr in thresholds if tr.source_channel})
    if not particle_channels:
        console.print("\n[red]No particle masks found.[/red]")
        console.print("[dim]Run 'Grouped intensity thresholding' first to generate particle masks.[/dim]")
        return

    console.print("\n[bold]Step 2: Particle Mask[/bold]")
    console.print("  [dim]Select the thresholded particle mask defining granules.[/dim]\n")
    particle_channel = numbered_select_one(particle_channels, "Particle mask")

    # Step 3: Exclusion mask (optional)
    other_particle_channels = [c for c in particle_channels if c != particle_channel]
    exclusion_channel = None
    if other_particle_channels:
        console.print("\n[bold]Step 3: Exclusion Mask (optional)[/bold]")
        console.print("  [dim]Exclude another mask's particles from the background ring.[/dim]\n")
        choices = ["(none)"] + other_particle_channels
        choice = numbered_select_one(choices, "Exclusion mask")
        if choice != "(none)":
            exclusion_channel = choice
    else:
        console.print("\n[bold]Step 3: Exclusion Mask[/bold]")
        console.print("  [dim]No other particle masks available — skipping.[/dim]")

    # Step 4: Ring dilation (granule BG ring)
    console.print("\n[bold]Step 4: Granule Ring Dilation[/bold]")
    console.print("  [dim]Dilation for background ring around each granule.[/dim]")
    ring_str = menu_prompt("Ring dilation pixels", default="5")
    try:
        ring_dilation_pixels = int(ring_str)
    except ValueError:
        console.print("[yellow]Invalid number, using default of 5.[/yellow]")
        ring_dilation_pixels = 5

    # Step 5: Exclusion dilation (dilute phase exclusion zone)
    console.print("\n[bold]Step 5: Dilute Phase Exclusion Dilation[/bold]")
    console.print("  [dim]Dilation applied to particle mask to define the exclusion zone around granules.[/dim]")
    excl_str = menu_prompt("Exclusion dilation pixels", default="5")
    try:
        exclusion_dilation_pixels = int(excl_str)
    except ValueError:
        console.print("[yellow]Invalid number, using default of 5.[/yellow]")
        exclusion_dilation_pixels = 5

    # Step 6: Normalization channel (optional)
    console.print("\n[bold]Step 6: Normalization Channel (optional)[/bold]")
    console.print("  [dim]Report mean intensity from another channel inside each particle/dilute region.[/dim]\n")
    norm_choices = ["(none)"] + ch_names
    norm_choice = numbered_select_one(norm_choices, "Normalization channel")
    normalization_channel = None if norm_choice == "(none)" else norm_choice

    # Step 7: Save derived images
    console.print("\n[bold]Step 7: Save Derived Images[/bold]")
    console.print("  [dim]Create condensed_phase and dilute_phase FOV images for surface plot visualization.[/dim]\n")
    save_images = numbered_select_one(["Yes", "No"], "Save derived images?") == "Yes"

    # Step 8: FOV selection
    console.print("\n[bold]Step 8: Select FOVs[/bold]")
    all_fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]

    # Exclude any previously created derived FOVs
    fovs_with_cells = [
        f for f in fovs_with_cells
        if not f.display_name.startswith(("condensed_phase_", "dilute_phase_"))
    ]

    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red]")
        return

    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    cell_ids = []
    for fov in selected_fovs:
        cells_df = store.get_cells(fov_id=fov.id)
        cell_ids.extend(cells_df["id"].tolist())

    # Step 8b: Naming prefix (only when saving derived images)
    name_prefix = ""
    if save_images:
        console.print("\n[bold]Naming Prefix[/bold]")
        console.print("  [dim]Enter a prefix for derived FOV names.[/dim]")
        fov_display_names = [f.display_name for f in selected_fovs]
        name_prefix = _prompt_prefix(
            fov_display_names, suffix_example="condensed_phase",
        )

    # Step 9: Confirmation
    console.print(f"\n[bold]Condensate analysis settings:[/bold]")
    console.print(f"  Measurement:          {meas_channel}")
    console.print(f"  Particle mask:        {particle_channel}")
    console.print(f"  Exclusion:            {exclusion_channel or '(none)'}")
    console.print(f"  Ring dilation:        {ring_dilation_pixels} px")
    console.print(f"  Exclusion dilation:   {exclusion_dilation_pixels} px")
    console.print(f"  Normalization:        {normalization_channel or '(none)'}")
    console.print(f"  Save derived images:  {'Yes' if save_images else 'No'}")
    if name_prefix:
        console.print(f"  Naming:               {name_prefix}_<FOV>_<phase>")
    console.print(f"  FOVs:                 {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Condensate analysis cancelled.[/yellow]")
        return

    # Step 10: Run with progress
    parameters = {
        "measurement_channel": meas_channel,
        "particle_channel": particle_channel,
        "exclusion_channel": exclusion_channel,
        "ring_dilation_pixels": ring_dilation_pixels,
        "exclusion_dilation_pixels": exclusion_dilation_pixels,
        "normalization_channel": normalization_channel,
        "save_images": save_images,
        "name_prefix": name_prefix,
    }

    with make_progress() as progress:
        task = progress.add_task("Condensate analysis...", total=len(selected_fovs))

        def on_progress(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        result = registry.run_plugin(
            "split_halo_condensate_analysis", store,
            cell_ids=cell_ids, parameters=parameters,
            progress_callback=on_progress,
        )

    # Step 11: Summary
    console.print(f"\n[green]Condensate analysis complete[/green]")
    console.print(f"  Cells processed: {result.cells_processed}")
    console.print(f"  Particles measured: {result.measurements_written}")
    granule_csvs = {
        k: v for k, v in result.custom_outputs.items() if k.startswith("csv_granule_")
    }
    dilute_csvs = {
        k: v for k, v in result.custom_outputs.items() if k.startswith("csv_dilute_")
    }
    if granule_csvs:
        console.print(f"  Granule CSV files:")
        for key, path in granule_csvs.items():
            condition = key.removeprefix("csv_granule_")
            console.print(f"    {condition}: {path}")
    if dilute_csvs:
        console.print(f"  Dilute phase CSV files:")
        for key, path in dilute_csvs.items():
            condition = key.removeprefix("csv_dilute_")
            console.print(f"    {condition}: {path}")
    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")
    console.print()


def _make_viz_runner(registry, plugin_name: str):
    """Create a handler function for a visualization plugin."""
    def handler(state: MenuState) -> None:
        if plugin_name == "surface_plot_3d":
            _run_surface_plot(state, registry)
        else:
            console.print(f"[yellow]No interactive handler for visualization plugin '{plugin_name}'.[/yellow]")
    return handler


def _run_surface_plot(state: MenuState, registry) -> None:
    """Interactive handler for the 3D surface plot visualization plugin."""
    store = state.require_experiment()
    plugin = registry.get_viz_plugin("surface_plot_3d")

    # Validate before opening napari
    errors = plugin.validate(store)
    if errors:
        console.print(f"\n[red]Cannot launch 3D surface plot:[/red]")
        for e in errors:
            console.print(f"  - {e}")
        return

    # Select FOV
    fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(fovs, seg_summary)
    selected = _select_fovs_from_table(fovs)
    if not selected:
        return
    fov = selected[0]  # Single FOV

    console.print(f"\nOpening 3D Surface Plot for [bold]{fov.display_name}[/bold]...")
    console.print("Draw a rectangle ROI, select channels, then click 'Generate Surface'.\n")

    try:
        plugin.launch(store, fov.id)
    except ImportError:
        console.print(
            "[red]Error:[/red] napari is not installed.\n"
            "Install with: [bold]pip install 'percell3[napari]'[/bold]"
        )


_BANNER_LINES = [
    "      ◎                                                                        ",
    "      ║      ███████╗ ████████╗███████╗ ███████╗████████╗██╗      ██╗          ",
    "     ▐█▌     ██╔═══██╗██╔═════╝██╔═══██╗██╔════╝██╔═════╝██║      ██║          ",
    "     ▐█▌     ███████╔╝███████╗ ███████╔╝██║     ███████╗ ██║      ██║          ",
    "      █      ██╔════╝ ██╔════╝ ██╔═══██╗██║     ██╔════╝ ██║      ██║          ",
    "      ▽      ██║      ████████╗██║   ██║███████╗████████╗████████╗████████╗    ",
    "   ───●───   ╚═╝      ╚═══════╝╚═╝   ╚═╝╚══════╝╚═══════╝╚═══════╝╚═══════╝    ",
    "   ▀█████▀                                                                     ",
]


def _colorize_banner_line(line: str) -> str:
    """Color a banner line: cyan microscope, green PER, magenta CELL."""
    parts = []
    for j, char in enumerate(line):
        if char == " ":
            parts.append(char)
        elif j <= 10:
            parts.append(f"[cyan]{char}[/cyan]")
        elif j <= 39:
            parts.append(f"[green]{char}[/green]")
        else:
            parts.append(f"[magenta]{char}[/magenta]")
    return "".join(parts)


def _show_header(state: MenuState) -> None:
    """Display the ASCII art banner, welcome message, and experiment context."""
    console.print()
    for line in _BANNER_LINES:
        console.print(_colorize_banner_line(line))
    console.print()
    console.print("[bold]                PerCell 3.0 — Single-Cell Microscopy Analysis                [/bold]")
    console.print()
    if state.experiment_path:
        name = state.store.name if state.store else ""
        label = f"{name} ({state.experiment_path})" if name else str(state.experiment_path)
        console.print(f"  Experiment: [cyan]{label}[/cyan]\n")
    else:
        console.print("  Experiment: [dim]None selected[/dim]\n")


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
            path_str = _prompt_path("Select experiment", mode="dir", title="Open .percell experiment")
        else:
            path_str = recent[int(choice) - 1]
    else:
        path_str = _prompt_path("Select experiment", mode="dir", title="Open .percell experiment")

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
    path_str = _prompt_path("Path for new experiment", mode="dir", title="Create .percell experiment")

    path = Path(path_str).expanduser()

    # Check if directory already exists and prompt for overwrite
    overwrite = False
    if path.exists() and any(path.iterdir()):
        console.print(
            f"[yellow]Directory is not empty:[/yellow] {path}"
        )
        if numbered_select_one(["No", "Yes"], "Overwrite existing contents?") != "Yes":
            console.print("[yellow]Creation cancelled.[/yellow]")
            return
        overwrite = True

    name = menu_prompt("Experiment name", default="")
    description = menu_prompt("Description", default="")

    try:
        from percell3.core import ExperimentStore
        from percell3.core.exceptions import ExperimentError
        from percell3.cli._recent import add_to_recent

        store = ExperimentStore.create(
            path, name=name, description=description, overwrite=overwrite,
        )
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
        build_auto_assignments,
        build_file_groups,
        next_fov_number,
        show_auto_preview,
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

    # 2a. Tile detection and prompting
    tile_config = None
    if len(scan_result.tiles) > 1:
        tile_config = _prompt_tile_config(scan_result.tiles, groups)

    # 2b. Auto/manual import mode choice
    import_mode = numbered_select_one(
        ["Auto-import all groups", "Manual configuration"],
        "Import mode",
    )

    if import_mode == "Auto-import all groups":
        condition_map, fov_names, bio_rep_map, channel_maps = build_auto_assignments(
            groups, store,
        )
        show_auto_preview(
            groups, condition_map, fov_names, bio_rep_map, channel_maps, "mip",
        )
        if numbered_select_one(["Yes", "No"], "Proceed?") != "Yes":
            console.print("[yellow]Import cancelled.[/yellow]")
            return
        default_condition = next(iter(condition_map.values()), "default")
        default_bio_rep = next(iter(bio_rep_map.values()), "N1")
        _run_import(
            store, str(source), default_condition, channel_maps, "mip",
            yes=True, bio_rep=default_bio_rep,
            condition_map=condition_map, fov_names=fov_names,
            bio_rep_map=bio_rep_map,
            source_files=source_files, scan_result=scan_result,
            tile_config=tile_config,
        )
        return

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
        tile_config=tile_config,
    )


def _import_from_percell(state: MenuState) -> None:
    """Import FOVs from another PerCell project."""
    from percell3.core import ExperimentStore
    from percell3.io.percell_import import PerCellImporter

    dst_store = state.require_experiment()

    # 1. Get source project path
    source_str = _prompt_path(
        "Source .percell project",
        mode="dir",
        title="Select source .percell project",
    )
    source_path = Path(source_str)

    # Validate source
    if not (source_path / "experiment.db").exists():
        console.print("[red]Error:[/red] Not a valid .percell project (no experiment.db).")
        return

    if source_path.resolve() == dst_store.path.resolve():
        console.print("[red]Error:[/red] Cannot import from the same project.")
        return

    # 2. Open source project
    try:
        src_store = ExperimentStore.open(source_path)
    except Exception as exc:
        console.print(f"[red]Error opening source project:[/red] {exc}")
        return

    try:
        src_fovs = src_store.get_fovs()
        if not src_fovs:
            console.print("[dim]Source project has no FOVs.[/dim]")
            return

        # 3. Display FOVs grouped by condition for selection
        fov_labels = [f"{f.display_name} ({f.condition})" for f in src_fovs]
        console.print(f"\n[bold]Source FOVs ({len(src_fovs)}):[/bold]")
        selected_labels = numbered_select_many(fov_labels, "FOVs to import")
        selected_indices = {fov_labels.index(lbl) for lbl in selected_labels}
        selected_fovs = [src_fovs[i] for i in sorted(selected_indices)]

        # 4. Show import summary
        src_channels = src_store.get_channels()
        dst_channels = {ch.name for ch in dst_store.get_channels()}
        new_channels = [ch.name for ch in src_channels if ch.name not in dst_channels]

        console.print(f"\n[bold]Import summary:[/bold]")
        console.print(f"  FOVs to import: {len(selected_fovs)}")
        console.print(f"  Source channels: {len(src_channels)}")
        if new_channels:
            console.print(f"  [yellow]New channels to create:[/yellow] {', '.join(new_channels)}")
        else:
            console.print(f"  All channels exist in destination")

        # 5. Confirm
        if numbered_select_one(["Yes", "No"], "\nProceed with import?") != "Yes":
            console.print("[yellow]Import cancelled.[/yellow]")
            return

        # 6. Execute import with progress
        fov_ids = [f.id for f in selected_fovs]
        importer = PerCellImporter(src_store, dst_store)

        progress = make_progress()
        with progress:
            task = progress.add_task("Importing FOVs...", total=len(fov_ids))

            def on_progress(current: int, total: int, name: str) -> None:
                progress.update(task, completed=current, description=f"Imported {name}")

            result = importer.import_fovs(fov_ids, progress_callback=on_progress)

        # 7. Show results
        console.print(f"\n[green]Import complete![/green]")
        console.print(f"  FOVs imported: {result.fovs_imported}")
        if result.channels_created:
            console.print(f"  Channels created: {result.channels_created}")
        if result.conditions_created:
            console.print(f"  Conditions created: {result.conditions_created}")
        if result.segmentations_created:
            console.print(f"  Segmentations imported: {result.segmentations_created}")
        if result.thresholds_created:
            console.print(f"  Thresholds imported: {result.thresholds_created}")
        if result.cells_imported:
            console.print(f"  Cells imported: {result.cells_imported}")
        if result.measurements_imported:
            console.print(f"  Measurements imported: {result.measurements_imported}")
        if result.particles_imported:
            console.print(f"  Particles imported: {result.particles_imported}")
        if result.warnings:
            console.print(f"\n[yellow]Warnings:[/yellow]")
            for w in result.warnings:
                console.print(f"  - {w}")

    finally:
        src_store.close()


def _prompt_tile_config(
    tiles: list[str],
    groups: list,
) -> TileConfig | None:
    """Detect tiles and prompt user for grid parameters.

    Args:
        tiles: List of detected tile indices from scan result.
        groups: File groups (for counting tiles per group).

    Returns:
        TileConfig if user wants stitching, None otherwise.
    """
    from percell3.io.models import TileConfig

    num_tiles = len(tiles)
    num_groups = len(groups)
    console.print(
        f"\n[bold]Tile scan detected:[/bold] "
        f"{num_tiles} tile indices across {num_groups} file groups"
    )

    stitch = numbered_select_one(
        ["Yes", "No"],
        "Stitch tiles into single FOV?",
    )
    if stitch != "Yes":
        return None

    # Prompt for grid columns (A)
    while True:
        try:
            cols_str = menu_prompt("Grid columns (A)")
            grid_cols = int(cols_str)
            if grid_cols < 1:
                console.print("[red]Must be >= 1[/red]")
                continue
            break
        except (ValueError, _MenuCancel):
            console.print("[red]Enter an integer >= 1[/red]")
            continue

    # Prompt for grid rows (B)
    while True:
        try:
            rows_str = menu_prompt("Grid rows (B)")
            grid_rows = int(rows_str)
            if grid_rows < 1:
                console.print("[red]Must be >= 1[/red]")
                continue
            break
        except (ValueError, _MenuCancel):
            console.print("[red]Enter an integer >= 1[/red]")
            continue

    # Validate tile count
    expected = grid_rows * grid_cols
    if expected != num_tiles:
        console.print(
            f"[yellow]Warning:[/yellow] Grid {grid_cols}x{grid_rows} expects "
            f"{expected} tiles, but {num_tiles} were detected."
        )

    # Grid type
    grid_type = numbered_select_one(
        ["row_by_row", "snake_by_row", "column_by_column", "snake_by_column"],
        "Grid type",
    )

    # Order
    order = numbered_select_one(
        ["right_and_down", "left_and_down", "right_and_up", "left_and_up"],
        "Tile order",
    )

    return TileConfig(
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        grid_type=grid_type,
        order=order,
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
    existing = store.get_bio_reps()
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
            f.display_name,
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


def _config_management_menu(state: MenuState) -> None:
    """Layer-based configuration management sub-menu."""
    Menu("CONFIG MANAGEMENT", [
        MenuItem("1", "Show config matrix", "Display FOV-segmentation-threshold matrix", _show_config_matrix),
        MenuItem("2", "Assign segmentation", "Assign segmentation(s) to FOVs one-by-one", _assign_segmentation),
        MenuItem("3", "Assign threshold", "Assign threshold(s) to FOVs one-by-one", _assign_threshold),
        MenuItem("4", "Rename segmentation", "Rename a segmentation entity", _rename_segmentation),
        MenuItem("5", "Rename threshold", "Rename a threshold entity", _rename_threshold),
        MenuItem("6", "Delete segmentation", "Delete a segmentation with impact preview", _delete_segmentation),
        MenuItem("7", "Delete threshold", "Delete a threshold with impact preview", _delete_threshold),
    ], state).run()
    raise _MenuCancel()


def _show_config_matrix(state: MenuState) -> None:
    """Display the config matrix: FOV | Segmentation | Threshold | Scopes."""
    from rich.table import Table

    store = state.require_experiment()
    matrix = store.get_config_matrix()

    if not matrix:
        console.print("\n[dim]Config matrix is empty. No segmentations or thresholds assigned.[/dim]")
        return

    table = Table(title="Configuration Matrix")
    table.add_column("#", style="dim")
    table.add_column("FOV")
    table.add_column("Segmentation")
    table.add_column("Threshold")
    table.add_column("Scopes")

    fovs = {f.id: f for f in store.get_fovs()}
    for i, entry in enumerate(matrix, 1):
        fov = fovs.get(entry.fov_id)
        fov_name = fov.display_name if fov else f"fov_{entry.fov_id}"

        try:
            seg = store.get_segmentation(entry.segmentation_id)
            seg_label = f"{seg.name} ({seg.cell_count or 0} cells)"
        except Exception:
            seg_label = f"seg_{entry.segmentation_id}"

        thr_label = "(none)"
        if entry.threshold_id is not None:
            try:
                thr = store.get_threshold(entry.threshold_id)
                thr_label = thr.name
            except Exception:
                thr_label = f"thr_{entry.threshold_id}"

        scopes_str = ", ".join(sorted(entry.scopes)) if entry.scopes else "(default)"
        table.add_row(str(i), fov_name, seg_label, thr_label, scopes_str)

    console.print(table)


def _assign_segmentation(state: MenuState) -> None:
    """Assign segmentation(s) to FOVs — one segmentation per FOV."""
    store = state.require_experiment()

    segs = store.get_segmentations(seg_type="cellular")
    if not segs:
        console.print("[red]No cellular segmentations found.[/red] Run segmentation first.")
        return

    seg_labels = [f"{s.name} ({s.cell_count or 0} cells, {s.width}x{s.height})" for s in segs]
    console.print(f"\n[bold]Segmentations ({len(seg_labels)}):[/bold]")
    selected_labels = numbered_select_many(seg_labels, "Segmentations to assign")
    selected_segs = [segs[seg_labels.index(lbl)] for lbl in selected_labels]

    fovs = store.get_fovs()
    if not fovs:
        console.print("[red]No FOVs found.[/red]")
        return

    fov_labels = [f.display_name for f in fovs]
    assigned = 0
    skipped = 0
    affected_fov_ids: list[int] = []

    for seg in selected_segs:
        console.print(f"\n[bold]Assign '{seg.name}' to which FOV(s)?[/bold]")
        selected_fov_names = numbered_select_many(fov_labels, "FOVs")
        target_fovs = [f for f in fovs if f.display_name in selected_fov_names]

        for fov in target_fovs:
            if fov.width != seg.width or fov.height != seg.height:
                console.print(
                    f"  [yellow]Skipped {fov.display_name}: "
                    f"dimension mismatch ({fov.width}x{fov.height} vs {seg.width}x{seg.height})[/yellow]"
                )
                skipped += 1
                continue

            # Replace existing config with new segmentation
            existing = store.get_fov_config(fov.id)
            for entry in existing:
                store.delete_fov_config_entry(entry.id)
            store.set_fov_config_entry(fov.id, seg.id)
            # Re-add any existing thresholds
            for entry in existing:
                if entry.threshold_id is not None:
                    store.set_fov_config_entry(
                        fov.id, seg.id,
                        threshold_id=entry.threshold_id,
                        scopes=entry.scopes,
                    )
            assigned += 1
            affected_fov_ids.append(fov.id)
            console.print(f"  [green]Assigned '{seg.name}' → {fov.display_name}[/green]")

    console.print(f"\n[green]Assigned {assigned} segmentation(s).[/green]")
    if skipped:
        console.print(f"[yellow]Skipped {skipped} (dimension mismatch).[/yellow]")

    # Trigger auto-measurement for affected FOVs
    if affected_fov_ids:
        from percell3.measure.auto_measure import on_config_changed
        for fov_id in affected_fov_ids:
            on_config_changed(store, fov_id)


def _assign_threshold(state: MenuState) -> None:
    """Assign threshold(s) to FOVs — each threshold can go to multiple FOVs."""
    store = state.require_experiment()

    thresholds = store.get_thresholds()
    if not thresholds:
        console.print("[red]No thresholds found.[/red] Run thresholding first.")
        return

    thr_labels = [f"{t.name} ({t.width}x{t.height})" for t in thresholds]
    console.print(f"\n[bold]Thresholds ({len(thr_labels)}):[/bold]")
    selected_labels = numbered_select_many(thr_labels, "Thresholds to assign")
    selected_thrs = [thresholds[thr_labels.index(lbl)] for lbl in selected_labels]

    fovs = store.get_fovs()
    if not fovs:
        console.print("[red]No FOVs found.[/red]")
        return

    fov_labels = [f.display_name for f in fovs]
    assigned = 0
    skipped = 0
    affected_fov_ids: list[int] = []

    for thr in selected_thrs:
        console.print(f"\n[bold]Assign '{thr.name}' to which FOV(s)?[/bold]")
        selected_fov_names = numbered_select_many(fov_labels, "FOVs")
        target_fovs = [f for f in fovs if f.display_name in selected_fov_names]

        for fov in target_fovs:
            if fov.width != thr.width or fov.height != thr.height:
                console.print(
                    f"  [yellow]Skipped {fov.display_name}: "
                    f"dimension mismatch ({fov.width}x{fov.height} vs {thr.width}x{thr.height})[/yellow]"
                )
                skipped += 1
                continue

            existing = store.get_fov_config(fov.id)
            if not existing:
                console.print(
                    f"  [yellow]Skipped {fov.display_name}: no segmentation configured.[/yellow]"
                )
                skipped += 1
                continue

            seg_id = existing[0].segmentation_id
            store.set_fov_config_entry(
                fov.id, seg_id,
                threshold_id=thr.id,
                scopes=["whole_cell", "mask_inside", "mask_outside"],
            )
            assigned += 1
            affected_fov_ids.append(fov.id)
            console.print(f"  [green]Assigned '{thr.name}' → {fov.display_name}[/green]")

    console.print(f"\n[green]Assigned {assigned} threshold-FOV pairing(s).[/green]")
    if skipped:
        console.print(f"[yellow]Skipped {skipped} (dimension mismatch or no segmentation).[/yellow]")

    # Trigger auto-measurement for affected FOVs
    if affected_fov_ids:
        from percell3.measure.auto_measure import on_config_changed
        for fov_id in set(affected_fov_ids):
            on_config_changed(store, fov_id)


def _rename_segmentation(state: MenuState) -> None:
    """Rename a segmentation entity."""
    store = state.require_experiment()
    segs = store.get_segmentations()
    if not segs:
        console.print("[dim]No segmentations found.[/dim]")
        return

    seg_labels = [f"{s.name} ({s.seg_type})" for s in segs]
    console.print("\n[bold]Select segmentation to rename:[/bold]")
    selected = numbered_select_one(seg_labels, "Segmentation")
    seg = segs[seg_labels.index(selected)]

    new_name = menu_prompt(f"New name for '{seg.name}'")
    store.rename_segmentation(seg.id, new_name)
    console.print(f"[green]Renamed to '{new_name}'.[/green]")


def _rename_threshold(state: MenuState) -> None:
    """Rename a threshold entity."""
    store = state.require_experiment()
    thresholds = store.get_thresholds()
    if not thresholds:
        console.print("[dim]No thresholds found.[/dim]")
        return

    thr_labels = [t.name for t in thresholds]
    console.print("\n[bold]Select threshold to rename:[/bold]")
    selected = numbered_select_one(thr_labels, "Threshold")
    thr = thresholds[thr_labels.index(selected)]

    new_name = menu_prompt(f"New name for '{thr.name}'")
    store.rename_threshold(thr.id, new_name)
    console.print(f"[green]Renamed to '{new_name}'.[/green]")


def _delete_segmentation(state: MenuState) -> None:
    """Delete segmentation(s) with impact preview."""
    store = state.require_experiment()
    segs = store.get_segmentations(seg_type="cellular")
    if not segs:
        console.print("[dim]No cellular segmentations to delete.[/dim]")
        return

    seg_labels = [f"{s.name} ({s.cell_count or 0} cells)" for s in segs]
    console.print(f"\n[bold]Segmentations ({len(seg_labels)}):[/bold]")
    selected_labels = numbered_select_many(seg_labels, "Segmentations to delete")
    selected_segs = [segs[seg_labels.index(lbl)] for lbl in selected_labels]

    total_cells = 0
    total_measurements = 0
    total_config = 0
    for seg in selected_segs:
        impact = store.get_segmentation_impact(seg.id)
        total_cells += impact.cells
        total_measurements += impact.measurements
        total_config += impact.config_entries

    console.print(f"\n[yellow]Deleting {len(selected_segs)} segmentation(s) will remove:[/yellow]")
    for seg in selected_segs:
        console.print(f"  - {seg.name}")
    console.print(f"  Cells: {total_cells}")
    console.print(f"  Measurements: {total_measurements}")
    console.print(f"  Config entries: {total_config}")

    if numbered_select_one(["No", "Yes"], "Proceed with deletion?") != "Yes":
        console.print("[dim]Deletion cancelled.[/dim]")
        return

    for seg in selected_segs:
        store.delete_segmentation(seg.id)
        console.print(f"  [red]Deleted:[/red] {seg.name}")

    console.print(f"\n[green]{len(selected_segs)} segmentation(s) deleted.[/green]")


def _delete_threshold(state: MenuState) -> None:
    """Delete threshold(s) with impact preview."""
    store = state.require_experiment()
    thresholds = store.get_thresholds()
    if not thresholds:
        console.print("[dim]No thresholds to delete.[/dim]")
        return

    thr_labels = [t.name for t in thresholds]
    console.print(f"\n[bold]Thresholds ({len(thr_labels)}):[/bold]")
    selected_labels = numbered_select_many(thr_labels, "Thresholds to delete")
    selected_thrs = [thresholds[thr_labels.index(lbl)] for lbl in selected_labels]

    total_particles = 0
    total_measurements = 0
    total_config = 0
    for thr in selected_thrs:
        impact = store.get_threshold_impact(thr.id)
        total_particles += impact.particles
        total_measurements += impact.measurements
        total_config += impact.config_entries

    console.print(f"\n[yellow]Deleting {len(selected_thrs)} threshold(s) will remove:[/yellow]")
    for thr in selected_thrs:
        console.print(f"  - {thr.name}")
    console.print(f"  Particles: {total_particles}")
    console.print(f"  Measurements: {total_measurements}")
    console.print(f"  Config entries: {total_config}")

    if numbered_select_one(["No", "Yes"], "Proceed with deletion?") != "Yes":
        console.print("[dim]Deletion cancelled.[/dim]")
        return

    for thr in selected_thrs:
        store.delete_threshold(thr.id)
        console.print(f"  [red]Deleted:[/red] {thr.name}")

    console.print(f"\n[green]{len(selected_thrs)} threshold(s) deleted.[/green]")


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

    # 4b. Post-segmentation cleanup
    edge_margin: int | None = None
    edge_str = menu_prompt(
        "Edge margin (remove cells within N px of border, blank = off)",
        default="",
    )
    if edge_str:
        try:
            edge_margin = int(edge_str)
            if edge_margin < 0:
                console.print("[red]Edge margin must be >= 0.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid edge margin: {edge_str}[/red]")
            return

    min_area: int | None = None
    area_str = menu_prompt(
        "Min cell area in px (remove small artifacts, blank = off)",
        default="",
    )
    if area_str:
        try:
            min_area = int(area_str)
            if min_area < 1:
                console.print("[red]Min area must be >= 1.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid min area: {area_str}[/red]")
            return

    # 5. FOV status table + selection
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)

    if len(all_fovs) == 1:
        console.print(f"  [dim](auto-selected: {all_fovs[0].display_name})[/dim]")
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
    if edge_margin is not None:
        console.print(f"  Edge margin: {edge_margin} px")
    if min_area is not None:
        console.print(f"  Min area:    {min_area} px")
    console.print(f"  FOVs:     {len(selected_fovs)} selected")

    if reseg_fovs:
        console.print(
            f"  [yellow]Re-segment:[/yellow] {len(reseg_fovs)} FOV(s) "
            "with existing cells will be replaced"
        )
        for f in reseg_fovs[:5]:
            count = seg_summary[f.id][0]
            console.print(f"    - {f.display_name} ({count} cells)")
        if len(reseg_fovs) > 5:
            console.print(f"    ... and {len(reseg_fovs) - 5} more")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Segmentation cancelled.[/yellow]")
        return

    # 7. Run segmentation
    from percell3.segment import SegmentationEngine, detect_gpu

    engine = SegmentationEngine()
    fov_names = [f.display_name for f in selected_fovs]

    device = detect_gpu()
    console.print(f"  Device: [bold]{device}[/bold]")

    with make_progress() as progress:
        task = progress.add_task("Segmenting...", total=None)

        def on_progress(current: int, total: int, fov_name: str) -> None:
            progress.update(
                task, total=total, completed=current,
                description=f"Segmenting {fov_name}",
            )

        seg_kwargs: dict = {}
        if edge_margin is not None:
            seg_kwargs["edge_margin"] = edge_margin
        if min_area is not None:
            seg_kwargs["min_area"] = min_area

        result = engine.run(
            store,
            channel=channel,
            model=model,
            diameter=diameter,
            fovs=fov_names,
            progress_callback=on_progress,
            **seg_kwargs,
        )

    console.print()
    console.print("[green]Segmentation complete[/green]")
    console.print(f"  FOVs processed: {result.fovs_processed}")
    console.print(f"  Total cells found: {result.cell_count}")
    console.print(f"  Elapsed: {result.elapsed_seconds:.1f}s")

    # Show run names per FOV
    for stat in result.fov_stats:
        if stat.get("status") == "ok" and stat.get("run_id"):
            fov_name = stat["fov"]
            run_id = stat["run_id"]
            try:
                seg_info = store.get_segmentation(run_id)
                console.print(f"  {fov_name}: segmentation [cyan]{seg_info.name}[/cyan] ({stat['cell_count']} cells)")
            except Exception:
                console.print(f"  {fov_name}: segmentation #{run_id} ({stat['cell_count']} cells)")

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
        for w in result.warnings:
            console.print(f"  [dim]- {w}[/dim]")

    # Auto-measure all channels on the just-segmented FOVs
    # Build map of FOV name → seg run ID from the result stats
    fov_run_map: dict[str, int] = {}
    for stat in result.fov_stats:
        if stat.get("status") == "ok" and stat.get("run_id"):
            fov_run_map[stat["fov"]] = stat["run_id"]

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
                    seg_id = fov_run_map.get(fov_info.display_name)
                    if seg_id is not None:
                        count = auto_measurer.measure_fov(
                            store,
                            fov_id=fov_info.id,
                            channels=ch_names,
                            segmentation_id=seg_id,
                        )
                        total_auto += count
                    auto_progress.update(
                        auto_task, completed=ai + 1,
                        description=f"Measuring {fov_info.display_name}",
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

    # Show FOV table for selection
    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)

    fov_names = [f.display_name for f in all_fovs]
    console.print(f"\n[bold]FOVs ({len(fov_names)}):[/bold]")
    fov_name = numbered_select_one(fov_names, "FOV to view")
    fov_info = next(f for f in all_fovs if f.display_name == fov_name)

    console.print(f"\nOpening [cyan]{fov_name}[/cyan] in napari...")
    console.print("[dim]Close the napari window to save any label edits.[/dim]\n")

    from percell3.segment.viewer import launch_viewer

    try:
        run_id = launch_viewer(store, fov_info.id)
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

    # Prerequisites (run once)
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

    while True:
        # Mode selection
        console.print("\n[bold]Measurement mode:[/bold]")
        modes = [
            "Whole cell (all channels, all metrics)",
            "Inside threshold mask",
            "Outside threshold mask",
            "Both inside + outside mask",
        ]
        mode = numbered_select_one(modes, "Mode")

        try:
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
        except _MenuCancel:
            continue


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
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
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

    # Run per-FOV measurement
    with make_progress() as progress:
        task = progress.add_task("Measuring...", total=len(selected_fovs))

        from percell3.measure.measurer import Measurer

        measurer = Measurer()
        total_measurements = 0

        for i, fov_info in enumerate(selected_fovs):
            fov_config = store.get_fov_config(fov_info.id)
            if not fov_config:
                continue
            seg_id = fov_config[0].segmentation_id
            count = measurer.measure_fov(
                store,
                fov_id=fov_info.id,
                channels=selected_channels,
                segmentation_id=seg_id,
            )
            total_measurements += count
            progress.update(
                task, completed=i + 1,
                description=f"Measuring {fov_info.display_name}",
            )

    console.print(f"\n[green]Measurement complete[/green]")
    console.print(f"  FOVs:         {len(selected_fovs)}")
    console.print(f"  Channels:     {len(selected_channels)}")
    console.print(f"  Measurements: {total_measurements}")
    console.print()


def _measure_masked(store, channels, all_fovs, scopes: list[str]) -> None:
    """Run mask-based measurement using threshold masks."""
    # Check for thresholds
    all_thresholds = store.get_thresholds()
    if not all_thresholds:
        console.print(
            "[red]No thresholds found.[/red] "
            "Run 'Grouped intensity thresholding' (menu 6) first."
        )
        return

    # Group thresholds by source_channel, pick most recent per channel
    thresholds_by_channel: dict[str, object] = {}
    for thr in all_thresholds:
        if thr.source_channel:
            thresholds_by_channel[thr.source_channel] = thr  # last wins = most recent

    # Select threshold channel
    thresh_channels = list(thresholds_by_channel.keys())
    console.print("\n[bold]Threshold channels available:[/bold]")
    threshold_channel = numbered_select_one(thresh_channels, "Threshold channel")
    selected_thr = thresholds_by_channel[threshold_channel]
    threshold_id = selected_thr.id

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
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    scope_label = " + ".join(s.replace("mask_", "") for s in scopes)
    console.print(f"\n[bold]Measurement settings:[/bold]")
    console.print(f"  Mode:      Mask-based ({scope_label})")
    console.print(f"  Threshold: {threshold_channel} (#{threshold_id})")
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
                # Resolve segmentation_id from FOV config
                fov_config = store.get_fov_config(fov_info.id)
                if not fov_config:
                    warnings.append(f"{fov_info.display_name}: no segmentation configured")
                    continue
                seg_id = fov_config[0].segmentation_id

                count = measurer.measure_fov_masked(
                    store,
                    fov_id=fov_info.id,
                    channels=selected_channels,
                    segmentation_id=seg_id,
                    threshold_id=threshold_id,
                    scopes=scopes,
                )
                total_measurements += count
                fovs_processed += 1
            except Exception as exc:
                if isinstance(exc, (MemoryError, KeyboardInterrupt, SystemExit)):
                    raise
                warnings.append(f"{fov_info.display_name}: {exc}")

            progress.update(
                task, completed=i + 1,
                description=f"Measuring {fov_info.display_name}",
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


def _threshold_fov(
    store: "ExperimentStore",
    fov_info: object,
    threshold_channel: str,
    grouping_channel: str,
    grouping_metric: str,
    gaussian_sigma: float | None = None,
    min_particle_area: int = 1,
    segmentation_id: int | None = None,
    name_prefix: str = "",
) -> tuple[int, int]:
    """Run grouping + threshold QC + particle analysis for one FOV.

    Args:
        store: Open ExperimentStore.
        fov_info: FovInfo object for the FOV to process.
        threshold_channel: Channel to threshold on.
        grouping_channel: Channel used for GMM grouping metric.
        grouping_metric: Metric name for grouping (e.g. mean_intensity).
        gaussian_sigma: Optional Gaussian sigma for pre-threshold smoothing.
        min_particle_area: Minimum particle area in pixels for filtering.
        segmentation_id: Which segmentation to use (default: latest from config).

    Returns:
        (fovs_processed, total_particles) — 1 or 0 for fovs_processed.
    """
    import numpy as np

    from percell3.measure.cell_grouper import CellGrouper
    from percell3.measure.particle_analyzer import ParticleAnalyzer
    from percell3.measure.thresholding import ThresholdEngine

    grouper = CellGrouper()
    engine = ThresholdEngine()
    analyzer = ParticleAnalyzer(min_particle_area=min_particle_area)

    fov_id = fov_info.id
    total_particles = 0

    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold]FOV: {fov_info.display_name} ({fov_info.condition}/{fov_info.bio_rep})[/bold]")

    # Group cells
    try:
        grouping_result = grouper.group_cells(
            store, fov_id=fov_id,
            channel=grouping_channel, metric=grouping_metric,
        )
    except ValueError as e:
        console.print(f"  [yellow]Skipping: {e}[/yellow]")
        return 0, 0

    console.print(f"  Groups found: {grouping_result.n_groups}")
    for i, (tag, mean) in enumerate(
        zip(grouping_result.tag_names, grouping_result.group_means)
    ):
        n_cells = int((grouping_result.group_labels == i).sum())
        console.print(f"    {tag}: {n_cells} cells (mean={mean:.1f})")

    # Read images and labels for this FOV
    if segmentation_id is None:
        fov_config = store.get_fov_config(fov_id)
        seg_id = fov_config[0].segmentation_id if fov_config else None
    else:
        seg_id = segmentation_id
    labels = store.read_labels(seg_id)
    image = store.read_image_numpy(fov_id, threshold_channel)

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
        cells_df = store.get_cells(fov_id=fov_id)
        group_cells = cells_df[cells_df["id"].isin(group_cell_ids)]
        label_values = group_cells["label_value"].tolist()

        from percell3.measure.threshold_viewer import (
            compute_masked_otsu,
            create_group_image,
        )

        group_image, cell_mask = create_group_image(image, labels, label_values)

        # Compute initial Otsu
        try:
            initial_thresh = compute_masked_otsu(
                group_image, cell_mask, gaussian_sigma=gaussian_sigma,
            )
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
                fov_name=fov_info.display_name,
                initial_threshold=initial_thresh,
                gaussian_sigma=gaussian_sigma,
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
            console.print(f"  [yellow]Skipping remaining groups for {fov_info.display_name}[/yellow]")
            skip_remaining_groups = True
            continue

        if not decision.accepted:
            console.print(f"  [dim]Skipped {tag_name}[/dim]")
            continue

        # Store threshold result
        thr_name = ""
        if name_prefix:
            thr_name = f"{name_prefix}_{fov_info.display_name}_g{i + 1}"
        result = engine.threshold_group(
            store, fov_id=fov_id, channel=threshold_channel,
            cell_ids=group_cell_ids,
            labels=labels, image=image,
            threshold_value=decision.threshold_value,
            roi=decision.roi,
            group_tag=tag_name,
            gaussian_sigma=gaussian_sigma,
            name=thr_name,
        )
        console.print(
            f"  [green]Accepted {tag_name}[/green]: "
            f"threshold={result.threshold_value:.1f}, "
            f"positive={result.positive_fraction:.1%}"
        )
        # Show threshold name
        try:
            thr_info = store.get_threshold(result.threshold_id)
            console.print(f"  Threshold: [cyan]{thr_info.name}[/cyan]")
        except Exception:
            console.print(f"  Threshold: #{result.threshold_id}")
        accepted_groups.append((tag_name, group_cell_ids, result.threshold_id))

    # Particle analysis for accepted groups — accumulate into one label image
    if accepted_groups:
        console.print(f"\n  [bold]Particle analysis...[/bold]")

        for tag_name, group_cell_ids, thr_id in accepted_groups:
            pa_result = analyzer.analyze_fov(
                store, fov_id=fov_id,
                threshold_id=thr_id,
                segmentation_id=seg_id,
                channel=threshold_channel,
            )

            # Store results
            if pa_result.particles:
                store.add_particles(pa_result.particles)
            if pa_result.summary_measurements:
                store.add_measurements(pa_result.summary_measurements)

            # Write per-threshold particle labels (label_values match DB)
            store.write_particle_labels(
                pa_result.particle_label_image, thr_id,
            )

            console.print(
                f"    {tag_name}: {pa_result.total_particles} particles "
                f"in {pa_result.cells_analyzed} cells"
            )
            total_particles += pa_result.total_particles
    else:
        console.print(f"  [dim]No groups accepted — skipping particle analysis.[/dim]")

    return 1, total_particles


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

    metrics = ["mean_intensity", "median_intensity", "integrated_intensity", "area_um2"]
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
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    # 4b. Auto-measure if no whole-cell measurements exist for selected FOVs
    measured_channels = store.list_measured_channels()
    if not measured_channels:
        console.print(
            "\n[yellow]No measurements found.[/yellow] "
            "Measuring all channels first..."
        )
        from percell3.measure.measurer import Measurer as _PreMeasurer

        pre_measurer = _PreMeasurer()
        with make_progress() as progress:
            task = progress.add_task("Measuring...", total=len(selected_fovs))
            for i, fov_info in enumerate(selected_fovs):
                fov_config = store.get_fov_config(fov_info.id)
                if fov_config:
                    pre_measurer.measure_fov(
                        store, fov_id=fov_info.id, channels=ch_names,
                        segmentation_id=fov_config[0].segmentation_id,
                    )
                progress.update(
                    task, completed=i + 1,
                    description=f"Measuring {fov_info.display_name}",
                )
        console.print("[green]Auto-measurement complete.[/green]")

    # 5. Gaussian sigma (optional pre-smoothing)
    gaussian_sigma: float | None = None
    sigma_str = menu_prompt(
        "Gaussian sigma for pre-smoothing (blank = off, 1.7 = PerCell default)",
        default="",
    )
    if sigma_str:
        try:
            gaussian_sigma = float(sigma_str)
            if gaussian_sigma < 0:
                console.print("[red]Sigma must be >= 0.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid sigma: {sigma_str}[/red]")
            return

    # 5b. Minimum particle area
    min_particle_area = 1
    area_str = menu_prompt(
        "Minimum particle area in pixels (blank = 1)", default="1",
    )
    try:
        min_particle_area = int(area_str)
        if min_particle_area < 1:
            console.print("[red]Min area must be >= 1.[/red]")
            return
    except ValueError:
        console.print(f"[red]Invalid number: {area_str}[/red]")
        return

    # 5c. Naming prefix
    console.print("\n[bold]Step 4: Naming Prefix[/bold]")
    console.print("  [dim]Enter a prefix for threshold names (e.g. 'Round1').[/dim]")
    fov_display_names = [f.display_name for f in selected_fovs]
    name_prefix = _prompt_prefix(fov_display_names, suffix_example="g1")

    # 6. Confirmation
    console.print(f"\n[bold]Thresholding settings:[/bold]")
    console.print(f"  Grouping:    {grouping_channel} / {grouping_metric}")
    console.print(f"  Threshold:   {threshold_channel} (Otsu)")
    if gaussian_sigma:
        console.print(f"  Smoothing:   Gaussian sigma={gaussian_sigma}")
    console.print(f"  Min particle: {min_particle_area} px")
    console.print(f"  Naming:      {name_prefix}_<FOV>_g<N>")
    console.print(f"  FOVs:        {len(selected_fovs)} selected")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Thresholding cancelled.[/yellow]")
        return

    # 6. Resolve segmentation per FOV (from config)
    fov_seg_map: dict[int, int] = {}
    for fov_info in selected_fovs:
        fov_config = store.get_fov_config(fov_info.id)
        if fov_config:
            fov_seg_map[fov_info.id] = fov_config[0].segmentation_id

    # 7. Run per-FOV
    total_particles = 0
    fovs_processed = 0
    skip_remaining_fovs = False

    for fov_info in selected_fovs:
        if skip_remaining_fovs:
            break

        processed, particles = _threshold_fov(
            store, fov_info, threshold_channel, grouping_channel, grouping_metric,
            gaussian_sigma=gaussian_sigma,
            min_particle_area=min_particle_area,
            segmentation_id=fov_seg_map.get(fov_info.id),
            name_prefix=name_prefix,
        )
        fovs_processed += processed
        total_particles += particles

    # 8. Summary
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[green]Thresholding complete[/green]")
    console.print(f"  FOVs processed: {fovs_processed}")
    console.print(f"  Total particles: {total_particles}")
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


def _query_menu(state: MenuState) -> None:
    """Query experiment data via a sub-menu."""
    Menu("QUERY", [
        MenuItem("1", "Experiment summary", "Per-FOV overview of cells and measurements", _query_summary),
        MenuItem("2", "Channels", "List channels in the experiment", _query_channels),
        MenuItem("3", "FOVs", "List fields of view", _query_fovs),
        MenuItem("4", "Conditions", "List experimental conditions", _query_conditions),
        MenuItem("5", "Biological replicates", "List biological replicates", _query_bio_reps),
    ], state).run()
    raise _MenuCancel()


def _query_channels(state: MenuState) -> None:
    from percell3.cli.query import format_output

    store = state.require_experiment()
    ch_list = store.get_channels()
    if not ch_list:
        console.print("[dim]No channels found.[/dim]")
        return
    rows = [{"name": ch.name, "role": ch.role or "", "color": ch.color or ""}
            for ch in ch_list]
    format_output(rows, ["name", "role", "color"], "table", "Channels")


def _query_fovs(state: MenuState) -> None:
    from percell3.cli.query import format_output

    store = state.require_experiment()
    fov_list = store.get_fovs()
    if not fov_list:
        console.print("[dim]No FOVs found.[/dim]")
        return
    rows = [
        {
            "name": f.display_name,
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


def _query_conditions(state: MenuState) -> None:
    from percell3.cli.query import format_output

    store = state.require_experiment()
    cond_list = store.get_conditions()
    if not cond_list:
        console.print("[dim]No conditions found.[/dim]")
        return
    rows = [{"name": c} for c in cond_list]
    format_output(rows, ["name"], "table", "Conditions")


def _query_bio_reps(state: MenuState) -> None:
    from percell3.cli.query import format_output

    store = state.require_experiment()
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

    rep_list = store.get_bio_reps()
    if not rep_list:
        console.print("[dim]No biological replicates found.[/dim]")
        return
    rows = [{"name": r} for r in rep_list]
    title = f"Biological Replicates ({cond_filter})" if cond_filter else "Biological Replicates"
    format_output(rows, ["name"], "table", title)


def _query_summary(state: MenuState) -> None:
    from percell3.cli.query import format_output

    store = state.require_experiment()
    summary = store.get_experiment_summary()
    if not summary:
        console.print("[dim]No FOVs found.[/dim]")
        return

    # Format particle column: "channel (count)" or "-"
    rows = []
    for s in summary:
        p_ch = s["particle_channels"] or ""
        p_count = s["particles"]
        if p_ch and p_count:
            particle_str = f"{p_ch} ({p_count})"
        elif p_ch:
            particle_str = p_ch
        else:
            particle_str = "-"

        rows.append({
            "condition": s["condition_name"],
            "bio_rep": s["bio_rep_name"],
            "fov": s["fov_name"],
            "cells": str(s["cells"]),
            "seg_model": s["seg_model"] or "-",
            "measured": s["measured_channels"] or "-",
            "masked": s["masked_channels"] or "-",
            "particles": particle_str,
        })

    columns = [
        "condition", "bio_rep", "fov", "cells", "seg_model",
        "measured", "masked", "particles",
    ]
    format_output(rows, columns, "table", "Experiment Summary")

    # Offer CSV export
    console.print()
    save = numbered_select_one(["No", "Yes"], "Save summary to CSV?")
    if save == "Yes":
        import pandas as pd

        out_str = _prompt_path("Output CSV path", mode="save", title="Save summary CSV")
        out_path = Path(out_str).expanduser()
        pd.DataFrame(summary).to_csv(out_path, index=False)
        console.print(f"[green]Saved to {out_path}[/green]")


def _import_imagej_rois(state: MenuState) -> None:
    """Import ImageJ ROI .zip files as cellular segmentation layers."""
    store = state.require_experiment()
    fovs = store.get_fovs()
    if not fovs:
        console.print("[dim]No FOVs found. Import images first.[/dim]")
        return

    mode = numbered_select_one(
        ["Single .zip file", "Folder of .zip files"],
        "Import mode",
    )

    if mode == "Single .zip file":
        zip_str = _prompt_path(
            "ImageJ ROI .zip file",
            mode="file",
            title="Select ImageJ ROI .zip file",
        )
        zip_path = Path(zip_str).expanduser()
        if not zip_path.exists():
            console.print(f"[red]File not found: {zip_path}[/red]")
            return
        _import_single_roi_zip(store, zip_path, fovs)
    else:
        dir_str = _prompt_path(
            "Folder containing .zip files",
            mode="dir",
            title="Select folder with ImageJ ROI .zip files",
        )
        dir_path = Path(dir_str).expanduser()
        if not dir_path.is_dir():
            console.print(f"[red]Not a directory: {dir_path}[/red]")
            return
        zip_files = sorted(dir_path.glob("*.zip"))
        if not zip_files:
            console.print(f"[dim]No .zip files found in {dir_path}[/dim]")
            return
        console.print(f"\n[bold]Found {len(zip_files)} .zip file(s).[/bold]")
        imported = 0
        failed = 0
        for zf in zip_files:
            console.print(f"\n[bold]--- {zf.name} ---[/bold]")
            try:
                _import_single_roi_zip(store, zf, fovs)
                imported += 1
            except (_MenuCancel, _MenuHome):
                raise
            except Exception as exc:
                console.print(f"[red]Failed: {exc}[/red]")
                failed += 1
        console.print(f"\n[green]Batch complete: {imported} imported, {failed} failed.[/green]")


def _import_single_roi_zip(
    store: "ExperimentStore",
    zip_path: Path,
    fovs: list,
) -> None:
    """Import one ImageJ ROI .zip as a segmentation on a user-selected FOV."""
    from percell3.segment.imagej_roi_reader import rois_to_labels
    from percell3.segment.roi_import import store_labels_and_cells

    # 1. Read and preview ROIs
    fov_names = [f.display_name for f in fovs]
    console.print(f"\n[bold]Select target FOV for '{zip_path.name}':[/bold]")
    fov_name = numbered_select_one(fov_names, "FOV")
    fov_info = next(f for f in fovs if f.display_name == fov_name)

    if fov_info.width is None or fov_info.height is None:
        console.print(
            f"[red]FOV '{fov_name}' has no dimensions. "
            "Import images before importing ROIs.[/red]"
        )
        return

    # 2. Render ROIs to label image
    console.print("  Reading ROIs...")
    try:
        labels, info = rois_to_labels(
            zip_path, (fov_info.height, fov_info.width),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    roi_count = info["roi_count"]
    skipped = info["skipped_count"]
    skip_msg = f" (skipped {skipped} non-polygon)" if skipped else ""
    console.print(f"  Found [bold]{roi_count}[/bold] polygon ROI(s){skip_msg}")

    # 3. Naming
    naming_mode = numbered_select_one(
        [f"Auto: {zip_path.stem}", "Manual: type a name"],
        "Segmentation name",
    )
    if naming_mode.startswith("Auto"):
        seg_name = zip_path.stem
    else:
        seg_name = menu_prompt("Segmentation name")

    # 4. Re-segmentation warning
    config = store.get_fov_config(fov_info.id)
    existing_cellular = [
        e for e in config
        if store.get_segmentation(e.segmentation_id).seg_type == "cellular"
    ]
    if existing_cellular:
        existing_seg = store.get_segmentation(existing_cellular[0].segmentation_id)
        console.print(
            f"[yellow]FOV already has cellular segmentation "
            f"'{existing_seg.name}'. The new import will replace it "
            f"in the active config.[/yellow]"
        )

    # 5. Confirm
    console.print(
        f"\n  Import {roi_count} ROIs → FOV '{fov_name}' as '{seg_name}'?"
    )
    if numbered_select_one(["No", "Yes"], "Confirm") != "Yes":
        console.print("[dim]Import cancelled.[/dim]")
        return

    # 6. Create segmentation and store
    console.print("  Creating segmentation...")
    seg_id = store.add_segmentation(
        name=seg_name, seg_type="cellular",
        width=fov_info.width, height=fov_info.height,
        source_fov_id=fov_info.id, source_channel="imagej",
        model_name="imagej",
        parameters={"source": "imagej", "imported": True,
                    "roi_file": zip_path.name},
    )

    console.print("  Storing labels and extracting cells...")
    cell_count = store_labels_and_cells(
        store, labels, fov_info.id, seg_id, fov_info.pixel_size_um,
    )

    # Trigger auto-measurement
    console.print("  Auto-measuring channels (this may take a moment)...")
    from percell3.measure.auto_measure import on_segmentation_created
    on_segmentation_created(store, seg_id, [fov_info.id])

    console.print(
        f"[green]Imported {cell_count} cells from "
        f"{zip_path.name} → '{fov_name}'[/green]"
    )


def _edit_menu(state: MenuState) -> None:
    """Edit experiment entities via a sub-menu."""
    Menu("EDIT", [
        MenuItem("1", "Rename experiment", "Change the experiment name", _rename_experiment),
        MenuItem("2", "Rename condition", "Rename a condition", _rename_condition),
        MenuItem("3", "Rename FOV", "Rename a field of view", _rename_fov),
        MenuItem("4", "Rename channel", "Rename a channel", _rename_channel),
        MenuItem("5", "Rename bio-rep", "Rename a biological replicate", _rename_bio_rep),
        MenuItem("6", "Delete FOV", "Remove FOV(s) and all associated data", _delete_fov),
        MenuItem("7", "Manage segmentations", "List, rename, delete, or unassign segmentations", _manage_seg_runs),
        MenuItem("8", "Manage thresholds", "List, rename, delete, or unassign thresholds", _manage_thr_runs),
        MenuItem("9", "Combine masks", "Create new mask from union/intersect of existing masks", _combine_masks),
        MenuItem("10", "Import ImageJ ROIs", "Import ImageJ ROI .zip as segmentation", _import_imagej_rois),
    ], state).run()
    raise _MenuCancel()


def _rename_experiment(state: MenuState) -> None:
    store = state.require_experiment()
    new_name = menu_prompt("New experiment name")
    store.rename_experiment(new_name)
    console.print(f"[green]Experiment renamed to '{new_name}'[/green]")


def _rename_condition(state: MenuState) -> None:
    store = state.require_experiment()
    conditions = store.get_conditions()
    if not conditions:
        console.print("[dim]No conditions found.[/dim]")
        return
    console.print("\n[bold]Conditions:[/bold]")
    old = numbered_select_one(conditions, "Condition to rename")
    new_name = menu_prompt(f"New name for '{old}'")
    store.rename_condition(old, new_name)
    console.print(f"[green]Condition '{old}' → '{new_name}'[/green]")


def _rename_fov(state: MenuState) -> None:
    store = state.require_experiment()
    fovs = store.get_fovs()
    if not fovs:
        console.print("[dim]No FOVs found.[/dim]")
        return
    fov_names = [f.display_name for f in fovs]
    console.print(f"\n[bold]FOVs ({len(fov_names)}):[/bold]")
    old = numbered_select_one(fov_names, "FOV to rename")
    fov_info = next(f for f in fovs if f.display_name == old)
    new_name = menu_prompt(f"New name for '{old}'")
    store.rename_fov(fov_info.id, new_name)
    console.print(f"[green]FOV '{old}' → '{new_name}'[/green]")


def _rename_channel(state: MenuState) -> None:
    store = state.require_experiment()
    channels = [ch.name for ch in store.get_channels()]
    if not channels:
        console.print("[dim]No channels found.[/dim]")
        return
    console.print("\n[bold]Channels:[/bold]")
    old = numbered_select_one(channels, "Channel to rename")
    new_name = menu_prompt(f"New name for '{old}'")
    store.rename_channel(old, new_name)
    console.print(f"[green]Channel '{old}' → '{new_name}'[/green]")


def _rename_bio_rep(state: MenuState) -> None:
    store = state.require_experiment()
    reps = store.get_bio_reps()
    if not reps:
        console.print("[dim]No biological replicates found.[/dim]")
        return
    console.print("\n[bold]Biological replicates:[/bold]")
    old = numbered_select_one(reps, "Bio-rep to rename")
    new_name = menu_prompt(f"New name for '{old}'")
    store.rename_bio_rep(old, new_name)
    console.print(f"[green]Bio-rep '{old}' → '{new_name}'[/green]")


def _delete_fov(state: MenuState) -> None:
    """Interactively delete FOV(s) and all associated data."""
    store = state.require_experiment()
    fovs = store.get_fovs()
    if not fovs:
        console.print("[dim]No FOVs found.[/dim]")
        return
    fov_names = [f.display_name for f in fovs]
    console.print(f"\n[bold]FOVs ({len(fov_names)}):[/bold]")
    selected_names = numbered_select_many(fov_names, "FOVs to delete")
    selected_fovs = [f for f in fovs if f.display_name in selected_names]

    console.print(f"\n[yellow]This will permanently delete {len(selected_fovs)} FOV(s) "
                  "and all associated cells, measurements, particles, and images.[/yellow]")
    for f in selected_fovs:
        console.print(f"  - {f.display_name}")

    if numbered_select_one(["No", "Yes"], "\nConfirm deletion?") != "Yes":
        console.print("[dim]Deletion cancelled.[/dim]")
        return

    for f in selected_fovs:
        store.delete_fov(f.id)
        console.print(f"  [red]Deleted:[/red] {f.display_name}")

    console.print(f"\n[green]{len(selected_fovs)} FOV(s) deleted.[/green]")


def _manage_seg_runs(state: MenuState) -> None:
    """Manage segmentations: list, rename, delete, or unassign."""
    store = state.require_experiment()

    segs = store.get_segmentations()
    if not segs:
        console.print("[dim]No segmentations found.[/dim]")
        return

    console.print(f"\n[bold]Segmentations:[/bold]")
    for i, seg in enumerate(segs, 1):
        console.print(
            f"  \\[{i}] {seg.name} — {seg.cell_count} cells, "
            f"model={seg.model_name}, created={seg.created_at}"
        )

    action = numbered_select_one(
        ["Rename", "Delete", "Unassign from FOVs", "Back"], "Action",
    )

    if action == "Rename":
        seg_labels = [f"{s.name} ({s.cell_count} cells)" for s in segs]
        selected_label = numbered_select_one(seg_labels, "Segmentation to rename")
        idx = seg_labels.index(selected_label)
        seg = segs[idx]
        new_name = menu_prompt(f"New name for '{seg.name}'")
        try:
            store.rename_segmentation(seg.id, new_name)
            console.print(f"[green]'{seg.name}' → '{new_name}'[/green]")
        except Exception as e:
            console.print(f"[red]Rename failed:[/red] {e}")

    elif action == "Delete":
        seg_labels = [f"{s.name} ({s.cell_count} cells)" for s in segs]
        selected_labels = numbered_select_many(seg_labels, "Segmentations to delete")
        selected_segs = [segs[seg_labels.index(lbl)] for lbl in selected_labels]

        # Show aggregate impact
        total_cells = 0
        total_measurements = 0
        total_particles = 0
        total_config = 0
        for seg in selected_segs:
            impact = store.get_segmentation_impact(seg.id)
            total_cells += impact.cells
            total_measurements += impact.measurements
            total_particles += impact.particles
            total_config += impact.config_entries

        console.print(f"\n[yellow]Deleting {len(selected_segs)} segmentation(s) will remove:[/yellow]")
        for seg in selected_segs:
            console.print(f"  - {seg.name}")
        console.print(f"  Cells: {total_cells}")
        console.print(f"  Measurements: {total_measurements}")
        console.print(f"  Particles: {total_particles}")
        console.print(f"  Config entries: {total_config}")

        if numbered_select_one(["No", "Yes"], "Confirm deletion?") != "Yes":
            console.print("[dim]Deletion cancelled.[/dim]")
            return

        for seg in selected_segs:
            store.delete_segmentation(seg.id)
            console.print(f"  [red]Deleted:[/red] {seg.name}")

        console.print(f"\n[green]{len(selected_segs)} segmentation(s) deleted.[/green]")

    elif action == "Unassign from FOVs":
        # Filter to cellular segmentations only
        cellular_segs = [s for s in segs if s.seg_type == "cellular"]
        if not cellular_segs:
            console.print("[dim]No cellular segmentations to unassign.[/dim]")
            return

        seg_labels = [f"{s.name} ({s.cell_count} cells)" for s in cellular_segs]
        selected_label = numbered_select_one(seg_labels, "Segmentation to unassign")
        idx = seg_labels.index(selected_label)
        seg = cellular_segs[idx]

        # Find FOVs that have this segmentation assigned
        config_matrix = store.get_config_matrix()
        assigned_fov_ids = sorted({
            e.fov_id for e in config_matrix
            if e.segmentation_id == seg.id
        })
        if not assigned_fov_ids:
            console.print("[dim]This segmentation is not assigned to any FOVs.[/dim]")
            return

        fovs = store.get_fovs()
        fov_map = {f.id: f for f in fovs}
        fov_labels = [fov_map[fid].display_name for fid in assigned_fov_ids]
        console.print(f"\n[bold]FOVs with '{seg.name}' assigned:[/bold]")
        selected_labels = numbered_select_many(fov_labels, "FOVs to unassign from")
        selected_fov_ids = [
            assigned_fov_ids[fov_labels.index(lbl)] for lbl in selected_labels
        ]

        console.print(
            f"\n[yellow]Unassigning '{seg.name}' from {len(selected_fov_ids)} FOV(s) "
            f"will remove associated cells, measurements, and particles.[/yellow]"
        )
        if numbered_select_one(["No", "Yes"], "Confirm?") != "Yes":
            console.print("[dim]Cancelled.[/dim]")
            return

        total = {"cells_deleted": 0, "measurements_deleted": 0,
                 "particles_deleted": 0, "config_entries_deleted": 0}
        for fov_id in selected_fov_ids:
            result = store.unassign_segmentation_from_fov(seg.id, fov_id)
            for k in total:
                total[k] += result[k]

        console.print(f"[green]Unassigned '{seg.name}' from {len(selected_fov_ids)} FOV(s).[/green]")
        console.print(f"  Cells removed: {total['cells_deleted']}")
        console.print(f"  Measurements removed: {total['measurements_deleted']}")
        console.print(f"  Particles removed: {total['particles_deleted']}")


def _manage_thr_runs(state: MenuState) -> None:
    """Manage thresholds: list, rename, delete, or unassign."""
    store = state.require_experiment()

    thresholds = store.get_thresholds()
    if not thresholds:
        console.print("[dim]No thresholds found.[/dim]")
        return

    console.print(f"\n[bold]Thresholds:[/bold]")
    for i, thr in enumerate(thresholds, 1):
        ch_label = thr.source_channel or "n/a"
        console.print(
            f"  \\[{i}] {ch_label}/{thr.name} — method={thr.method}, "
            f"threshold={thr.threshold_value}, created={thr.created_at}"
        )

    action = numbered_select_one(
        ["Rename", "Delete", "Unassign from FOVs", "Back"], "Action",
    )

    if action == "Rename":
        thr_labels = [f"{(t.source_channel or 'n/a')}/{t.name}" for t in thresholds]
        selected_label = numbered_select_one(thr_labels, "Threshold to rename")
        idx = thr_labels.index(selected_label)
        thr = thresholds[idx]
        new_name = menu_prompt(f"New name for '{thr.name}'")
        try:
            store.rename_threshold(thr.id, new_name)
            console.print(f"[green]'{thr.name}' → '{new_name}'[/green]")
        except Exception as e:
            console.print(f"[red]Rename failed:[/red] {e}")

    elif action == "Delete":
        thr_labels = [f"{(t.source_channel or 'n/a')}/{t.name}" for t in thresholds]
        selected_labels = numbered_select_many(thr_labels, "Thresholds to delete")
        selected_thrs = [thresholds[thr_labels.index(lbl)] for lbl in selected_labels]

        # Show aggregate impact
        total_measurements = 0
        total_particles = 0
        total_config = 0
        for thr in selected_thrs:
            impact = store.get_threshold_impact(thr.id)
            total_measurements += impact.measurements
            total_particles += impact.particles
            total_config += impact.config_entries

        console.print(f"\n[yellow]Deleting {len(selected_thrs)} threshold(s) will remove:[/yellow]")
        for thr in selected_thrs:
            ch_label = thr.source_channel or "n/a"
            console.print(f"  - {ch_label}/{thr.name}")
        console.print(f"  Measurements: {total_measurements}")
        console.print(f"  Particles: {total_particles}")
        console.print(f"  Config entries: {total_config}")

        if numbered_select_one(["No", "Yes"], "Confirm deletion?") != "Yes":
            console.print("[dim]Deletion cancelled.[/dim]")
            return

        for thr in selected_thrs:
            ch_label = thr.source_channel or "n/a"
            store.delete_threshold(thr.id)
            console.print(f"  [red]Deleted:[/red] {ch_label}/{thr.name}")

        console.print(f"\n[green]{len(selected_thrs)} threshold(s) deleted.[/green]")

    elif action == "Unassign from FOVs":
        thr_labels = [f"{(t.source_channel or 'n/a')}/{t.name}" for t in thresholds]
        selected_label = numbered_select_one(thr_labels, "Threshold to unassign")
        idx = thr_labels.index(selected_label)
        thr = thresholds[idx]

        # Find FOVs that have this threshold assigned
        config_matrix = store.get_config_matrix()
        assigned_fov_ids = sorted({
            e.fov_id for e in config_matrix
            if e.threshold_id == thr.id
        })
        if not assigned_fov_ids:
            console.print("[dim]This threshold is not assigned to any FOVs.[/dim]")
            return

        fovs = store.get_fovs()
        fov_map = {f.id: f for f in fovs}
        fov_labels = [fov_map[fid].display_name for fid in assigned_fov_ids]
        ch_label = thr.source_channel or "n/a"
        console.print(f"\n[bold]FOVs with '{ch_label}/{thr.name}' assigned:[/bold]")
        selected_labels = numbered_select_many(fov_labels, "FOVs to unassign from")
        selected_fov_ids = [
            assigned_fov_ids[fov_labels.index(lbl)] for lbl in selected_labels
        ]

        console.print(
            f"\n[yellow]Unassigning '{ch_label}/{thr.name}' from "
            f"{len(selected_fov_ids)} FOV(s) will remove associated "
            f"measurements and particles.[/yellow]"
        )
        if numbered_select_one(["No", "Yes"], "Confirm?") != "Yes":
            console.print("[dim]Cancelled.[/dim]")
            return

        total = {"measurements_deleted": 0, "particles_deleted": 0,
                 "config_entries_deleted": 0}
        for fov_id in selected_fov_ids:
            result = store.unassign_threshold_from_fov(thr.id, fov_id)
            for k in total:
                total[k] += result[k]

        console.print(
            f"[green]Unassigned '{ch_label}/{thr.name}' from "
            f"{len(selected_fov_ids)} FOV(s).[/green]"
        )
        console.print(f"  Measurements removed: {total['measurements_deleted']}")
        console.print(f"  Particles removed: {total['particles_deleted']}")


def _combine_masks(state: MenuState) -> None:
    """Combine thresholds via union or intersect."""
    import numpy as np

    store = state.require_experiment()

    thresholds = store.get_thresholds()
    if len(thresholds) < 2:
        console.print("[red]Need at least 2 thresholds to combine.[/red]")
        return

    # Group by source_channel and let user pick channel
    channels = sorted({t.source_channel for t in thresholds if t.source_channel})
    if not channels:
        console.print("[red]No thresholds with a source channel found.[/red]")
        return

    if len(channels) > 1:
        console.print("\n[bold]Select channel:[/bold]")
        channel = numbered_select_one(channels, "Channel")
        filtered = [t for t in thresholds if t.source_channel == channel]
    else:
        channel = channels[0]
        filtered = [t for t in thresholds if t.source_channel == channel]

    if len(filtered) < 2:
        console.print(f"[red]Need at least 2 thresholds on channel '{channel}'.[/red]")
        return

    # Select thresholds to combine
    thr_labels = [f"{t.name} (method={t.method})" for t in filtered]
    console.print(f"\n[bold]Select thresholds to combine ({channel}):[/bold]")
    selected_labels = numbered_select_many(thr_labels, "Thresholds (space-separated, or 'all')")
    selected_thrs = [filtered[thr_labels.index(l)] for l in selected_labels]

    if len(selected_thrs) < 2:
        console.print("[red]Select at least 2 thresholds.[/red]")
        return

    # Operation
    operation = numbered_select_one(["union", "intersect"], "Combine operation")

    # Optional name
    default_name = f"{operation}_{'_'.join(t.name for t in selected_thrs[:3])}"
    name = menu_prompt("Threshold name", default=default_name)

    try:
        # Read and combine masks
        first_mask = store.read_mask(selected_thrs[0].id)
        combined = first_mask > 0

        for thr in selected_thrs[1:]:
            mask = store.read_mask(thr.id)
            if operation == "union":
                combined = combined | (mask > 0)
            else:
                combined = combined & (mask > 0)

        # Create new threshold entity
        ref = selected_thrs[0]
        new_thr_id = store.add_threshold(
            name=name,
            method=operation,
            width=ref.width,
            height=ref.height,
            source_channel=channel,
        )

        # Write combined mask
        store.write_mask(combined.astype(np.uint8), new_thr_id)

        console.print(f"\n[green]Combined mask created (threshold ID {new_thr_id}).[/green]")
        try:
            new_thr = store.get_threshold(new_thr_id)
            console.print(f"  Name: [cyan]{new_thr.name}[/cyan]")
        except Exception:
            pass
    except (ValueError, KeyError) as e:
        console.print(f"[red]Combine failed:[/red] {e}")


def _export_csv(state: MenuState) -> None:
    """Interactively export measurements to CSV."""
    store = state.require_experiment()

    # Format selection
    console.print("\n[bold]Export format:[/bold]")
    fmt = numbered_select_one(
        ["Wide format (single CSV, one row per cell)",
         "Prism format (directory of CSVs, one per metric)"],
        "Format",
    )
    if "Prism" in fmt:
        _export_prism(state)
        return

    # FOV selection
    console.print("\n[bold]FOV filter:[/bold]")
    all_fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)
    if len(all_fovs) == 1:
        console.print(
            f"  [dim](auto-selected: {all_fovs[0].display_name})[/dim]"
        )
        selected_fovs = all_fovs
    else:
        selected_fovs = _select_fovs_from_table(all_fovs)

    fov_ids: list[int] | None = None
    if len(selected_fovs) < len(all_fovs):
        fov_ids = [f.id for f in selected_fovs]
        console.print(f"  [dim]{len(selected_fovs)} of {len(all_fovs)} FOVs selected[/dim]")

    output_str = _prompt_path("Output CSV path", mode="save", title="Save measurements CSV")

    out_path = Path(output_str).expanduser()

    # Auto-correct directory to directory/measurements.csv
    if out_path.is_dir():
        out_path = out_path / "measurements.csv"
        console.print(f"[yellow]Path is a directory — exporting to {out_path}[/yellow]")

    # Check parent directory exists
    if not out_path.parent.exists():
        console.print(f"[red]Parent directory does not exist: {out_path.parent}[/red]")
        return

    if out_path.exists():
        if numbered_select_one(["No", "Yes"], "File exists. Overwrite?") != "Yes":
            console.print("[yellow]Export cancelled.[/yellow]")
            return

    # Export type selection
    console.print("\n[bold]Export type:[/bold]")
    export_type = numbered_select_one(
        ["Cell measurements only", "Particle data only", "Both"],
        "Export",
    )

    include_cells = export_type != "Particle data only"
    include_particles = export_type != "Cell measurements only"

    # Check for particle data if requested
    if include_particles:
        particle_df = store.get_particles()
        if particle_df.empty:
            console.print("[yellow]No particle data found.[/yellow]")
            if not include_cells:
                return
            include_particles = False

    ch_list = None
    met_list = None
    scope_val = None
    particle_metrics = None

    # Channel selection — shared between cell and particle exports
    if include_cells or include_particles:
        if include_particles and include_cells:
            # Show all experiment channels so particles can measure from any
            all_channels = [ch.name for ch in store.get_channels()]
        elif include_cells:
            all_channels = store.list_measured_channels()
        else:
            all_channels = [ch.name for ch in store.get_channels()]

        if all_channels:
            console.print("\n[bold]Channel filter:[/bold]")
            ch_list = numbered_select_many(
                all_channels, "Channels (space-separated, or 'all')",
            )
            if set(ch_list) == set(all_channels):
                ch_list = None  # all selected — no filter needed

    if include_cells:
        # Optional metric filter (cell-level)
        available_metrics = store.list_measured_metrics()
        if available_metrics:
            console.print("\n[bold]Metric filter:[/bold]")
            met_list = numbered_select_many(available_metrics, "Metrics (space-separated, or 'all')")
            if set(met_list) == set(available_metrics):
                met_list = None  # all selected — no filter needed

        # Scope filter
        console.print("\n[bold]Scope filter:[/bold]")
        scope_options = [
            "All scopes",
            "Whole cell only",
            "Inside mask only",
            "Outside mask only",
        ]
        scope_choice = numbered_select_one(scope_options, "Scope")
        scope_map = {
            "Whole cell only": "whole_cell",
            "Inside mask only": "mask_inside",
            "Outside mask only": "mask_outside",
        }
        scope_val = scope_map.get(scope_choice)

    if include_particles:
        # Optional particle metric filter
        particle_metric_options = [
            "area_pixels", "area_um2", "perimeter", "circularity",
            "eccentricity", "solidity", "major_axis_length", "minor_axis_length",
            "mean_intensity", "max_intensity", "integrated_intensity",
        ]
        console.print("\n[bold]Particle metric filter:[/bold]")
        selected_particle_metrics = numbered_select_many(
            particle_metric_options, "Particle metrics (space-separated, or 'all')",
        )
        if set(selected_particle_metrics) != set(particle_metric_options):
            particle_metrics = selected_particle_metrics

    try:
        if include_cells:
            with console.status("[bold blue]Exporting measurements..."):
                store.export_csv(
                    out_path, channels=ch_list, metrics=met_list,
                    scope=scope_val, fov_ids=fov_ids,
                )
            console.print(f"[green]Exported measurements to {out_path}[/green]")

        if include_particles:
            if include_cells:
                particle_path = out_path.with_name(
                    f"{out_path.stem}_particles{out_path.suffix}"
                )
            else:
                particle_path = out_path
            with console.status("[bold blue]Exporting particle data..."):
                store.export_particles_csv(
                    particle_path, channels=ch_list,
                    metrics=particle_metrics, fov_ids=fov_ids,
                )
            console.print(f"[green]Exported particle data to {particle_path}[/green]")
    except OSError as exc:
        console.print(f"[red]Export failed:[/red] {exc}")


def _export_prism(state: MenuState) -> None:
    """Interactively export measurements in Prism-friendly format."""
    store = state.require_experiment()

    # FOV selection
    console.print("\n[bold]FOV filter:[/bold]")
    all_fovs = store.get_fovs()
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)
    if len(all_fovs) == 1:
        console.print(
            f"  [dim](auto-selected: {all_fovs[0].display_name})[/dim]"
        )
        selected_fovs = all_fovs
    else:
        selected_fovs = _select_fovs_from_table(all_fovs)

    fov_ids: list[int] | None = None
    if len(selected_fovs) < len(all_fovs):
        fov_ids = [f.id for f in selected_fovs]
        console.print(f"  [dim]{len(selected_fovs)} of {len(all_fovs)} FOVs selected[/dim]")

    output_str = _prompt_path("Output directory for Prism export", mode="dir", title="Select Prism export directory")
    out_dir = Path(output_str).expanduser()

    # Auto-correct: if user enters a .csv path, use its parent directory
    if out_dir.suffix.lower() == ".csv":
        out_dir = out_dir.parent / out_dir.stem
        console.print(f"[yellow]Using directory: {out_dir}[/yellow]")

    # Check parent directory exists
    if not out_dir.parent.exists():
        console.print(f"[red]Parent directory does not exist: {out_dir.parent}[/red]")
        return

    # Check overwrite if directory exists and is non-empty
    if out_dir.exists() and any(out_dir.iterdir()):
        if numbered_select_one(["No", "Yes"], "Directory is not empty. Overwrite?") != "Yes":
            console.print("[yellow]Export cancelled.[/yellow]")
            return

    try:
        with console.status("[bold blue]Exporting Prism-format CSVs..."):
            result = store.export_prism_csv(out_dir, fov_ids=fov_ids)

        if result["files_written"] == 0:
            console.print("[yellow]No measurements found to export.[/yellow]")
        else:
            console.print(
                f"[green]Prism export complete![/green]\n"
                f"  Directory: {out_dir}\n"
                f"  Channels: {result['channels_exported']}\n"
                f"  Files written: {result['files_written']}"
            )
    except OSError as exc:
        console.print(f"[red]Export failed:[/red] {exc}")


def _export_tiff(state: MenuState) -> None:
    """Export FOV images, labels, and masks as TIFF files."""
    from percell3.core.tiff_export import export_fov_as_tiff

    store = state.require_experiment()
    fovs = store.get_fovs()
    if not fovs:
        console.print("[yellow]No FOVs found.[/yellow]")
        return

    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(fovs, seg_summary)

    if len(fovs) == 1:
        console.print(f"  [dim](auto-selected: {fovs[0].display_name})[/dim]")
        selected = fovs
    else:
        selected = _select_fovs_from_table(fovs)

    output_dir = store.path / "exports" / "tiff"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Overwrite check
    overwrite = False
    existing = list(output_dir.glob("*.tiff"))
    if existing:
        ans = menu_prompt("Files already exist in exports/tiff/. Overwrite?", default="n")
        overwrite = ans.lower().startswith("y")
        if not overwrite:
            console.print("[dim]Export cancelled.[/dim]")
            return

    total_written = 0
    all_skipped: list[str] = []

    with make_progress() as progress:
        task = progress.add_task("Exporting TIFFs...", total=len(selected))
        for fov in selected:
            progress.update(task, description=f"Exporting {fov.display_name}")
            try:
                result = export_fov_as_tiff(store, fov.id, output_dir, overwrite=overwrite)
                total_written += len(result.written)
                all_skipped.extend(result.skipped)
            except FileExistsError:
                console.print(f"  [yellow]Skipped {fov.display_name} (files exist)[/yellow]")
            except OSError as exc:
                console.print(f"  [red]Error exporting {fov.display_name}:[/red] {exc}")
            progress.advance(task)

    console.print(f"\n[green]Exported {total_written} files to exports/tiff/[/green]")
    if all_skipped:
        console.print(f"[yellow]Skipped {len(all_skipped)} items:[/yellow]")
        for skip in all_skipped:
            console.print(f"  [dim]{skip}[/dim]")


def _particle_workflow(state: MenuState) -> None:
    """Particle analysis workflow: segment → measure → threshold → export."""
    store = state.require_experiment()

    # --- Prerequisites ---
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    ch_names = [ch.name for ch in channels]

    # --- Step 1: FOV selection ---
    console.print("\n[bold]Step 1: Select FOVs[/bold]")
    seg_summary = store.get_fov_segmentation_summary()
    _show_fov_status_table(all_fovs, seg_summary)

    if len(all_fovs) == 1:
        console.print(f"  [dim](auto-selected: {all_fovs[0].display_name})[/dim]")
        selected_fovs = all_fovs
    else:
        selected_fovs = _select_fovs_from_table(all_fovs)

    # --- Step 2: Segmentation channel + model ---
    console.print("\n[bold]Step 2: Segmentation[/bold]")
    console.print("\n[bold]Channel to segment:[/bold]")
    seg_channel = numbered_select_one(ch_names, "Segmentation channel")

    models = _build_model_list()
    console.print("\n[bold]Segmentation model:[/bold]")
    model = numbered_select_one(models, "Model")

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

    edge_margin: int | None = None
    edge_str = menu_prompt(
        "Edge margin (remove cells within N px of border, blank = off)",
        default="",
    )
    if edge_str:
        try:
            edge_margin = int(edge_str)
            if edge_margin < 0:
                console.print("[red]Edge margin must be >= 0.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid edge margin: {edge_str}[/red]")
            return

    min_area: int | None = None
    area_str = menu_prompt(
        "Min cell area in px (remove small artifacts, blank = off)",
        default="",
    )
    if area_str:
        try:
            min_area = int(area_str)
            if min_area < 1:
                console.print("[red]Min area must be >= 1.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid min area: {area_str}[/red]")
            return

    # --- Step 3: Threshold channels (multi-select) ---
    console.print("\n[bold]Step 3: Threshold Channels[/bold]")
    console.print("\n[bold]Channels to threshold:[/bold]")
    threshold_channels = numbered_select_many(ch_names, "Threshold channels (numbers, 'all')")

    # --- Step 4: Grouping channel + metric ---
    console.print("\n[bold]Step 4: Grouping[/bold]")
    console.print("\n[bold]Channel for grouping metric:[/bold]")
    grouping_channel = numbered_select_one(ch_names, "Grouping channel")

    metrics = ["mean_intensity", "median_intensity", "integrated_intensity", "area_um2"]
    console.print("\n[bold]Metric for grouping:[/bold]")
    grouping_metric = numbered_select_one(metrics, "Grouping metric")

    # Gaussian sigma for threshold smoothing
    gaussian_sigma: float | None = None
    sigma_str = menu_prompt(
        "Gaussian sigma for pre-smoothing (blank = off, 1.7 = PerCell default)",
        default="",
    )
    if sigma_str:
        try:
            gaussian_sigma = float(sigma_str)
            if gaussian_sigma < 0:
                console.print("[red]Sigma must be >= 0.[/red]")
                return
        except ValueError:
            console.print(f"[red]Invalid sigma: {sigma_str}[/red]")
            return

    # --- Step 4b: Minimum particle area ---
    wf_min_particle_area = 1
    area_str = menu_prompt(
        "Minimum particle area in pixels (blank = 1)", default="1",
    )
    try:
        wf_min_particle_area = int(area_str)
        if wf_min_particle_area < 1:
            console.print("[red]Min area must be >= 1.[/red]")
            return
    except ValueError:
        console.print(f"[red]Invalid number: {area_str}[/red]")
        return

    # --- Step 5: Export directory ---
    console.print("\n[bold]Step 5: Export[/bold]")
    output_str = _prompt_path("Output directory for Prism export", mode="dir", title="Select Prism export directory")
    out_dir = Path(output_str).expanduser()
    if out_dir.suffix.lower() == ".csv":
        out_dir = out_dir.parent / out_dir.stem
        console.print(f"[yellow]Using directory: {out_dir}[/yellow]")

    if not out_dir.parent.exists():
        console.print(f"[red]Parent directory does not exist: {out_dir.parent}[/red]")
        return

    if out_dir.exists() and any(out_dir.iterdir()):
        if numbered_select_one(["No", "Yes"], "Directory is not empty. Overwrite?") != "Yes":
            console.print("[yellow]Workflow cancelled.[/yellow]")
            return

    # --- Confirmation ---
    # Check for re-segmentation
    reseg_fovs = [
        f for f in selected_fovs
        if seg_summary.get(f.id, (0, None))[0] > 0
    ]

    console.print(f"\n[bold]Workflow settings:[/bold]")
    console.print(f"  FOVs:           {len(selected_fovs)} selected")
    console.print(f"  Segmentation:   {seg_channel} / {model} / {diameter or 'auto-detect'}")
    if edge_margin is not None:
        console.print(f"  Edge margin:    {edge_margin} px")
    if min_area is not None:
        console.print(f"  Min area:       {min_area} px")
    console.print(f"  Threshold:      {', '.join(threshold_channels)} (Otsu)")
    if gaussian_sigma:
        console.print(f"  Smoothing:      Gaussian sigma={gaussian_sigma}")
    console.print(f"  Min particle:   {wf_min_particle_area} px")
    console.print(f"  Grouping:       {grouping_channel} / {grouping_metric}")
    console.print(f"  Measurement:    all channels")
    console.print(f"  Export:         {out_dir} (Prism format)")

    if reseg_fovs:
        console.print(
            f"  [yellow]Re-segment:[/yellow] {len(reseg_fovs)} FOV(s) "
            "with existing cells will be replaced"
        )

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Workflow cancelled.[/yellow]")
        return

    # =================================================================
    # Stage 1: Segmentation
    # =================================================================
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold]Stage 1: Segmentation[/bold]")

    from percell3.segment import SegmentationEngine, detect_gpu

    engine = SegmentationEngine()
    fov_names = [f.display_name for f in selected_fovs]

    device = detect_gpu()
    console.print(f"  Device: [bold]{device}[/bold]")

    with make_progress() as progress:
        task = progress.add_task("Segmenting...", total=None)

        def on_seg_progress(current: int, total: int, fov_name: str) -> None:
            progress.update(
                task, total=total, completed=current,
                description=f"Segmenting {fov_name}",
            )

        wf_seg_kwargs: dict = {}
        if edge_margin is not None:
            wf_seg_kwargs["edge_margin"] = edge_margin
        if min_area is not None:
            wf_seg_kwargs["min_area"] = min_area

        seg_result = engine.run(
            store,
            channel=seg_channel,
            model=model,
            diameter=diameter,
            fovs=fov_names,
            progress_callback=on_seg_progress,
            **wf_seg_kwargs,
        )

    console.print(f"\n[green]Segmentation complete[/green]")
    console.print(f"  FOVs processed: {seg_result.fovs_processed}")
    console.print(f"  Total cells: {seg_result.cell_count}")
    console.print(f"  Elapsed: {seg_result.elapsed_seconds:.1f}s")

    if seg_result.warnings:
        console.print(f"\n[yellow]Warnings ({len(seg_result.warnings)}):[/yellow]")
        for w in seg_result.warnings:
            console.print(f"  [dim]- {w}[/dim]")

    if seg_result.cell_count == 0:
        console.print("[red]No cells found. Workflow cannot continue.[/red]")
        return

    # =================================================================
    # Stage 2: Measurement (all channels, whole-cell)
    # =================================================================
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold]Stage 2: Measuring all channels[/bold]")

    from percell3.measure.measurer import Measurer

    measurer = Measurer()
    total_measurements = 0

    with make_progress() as progress:
        task = progress.add_task("Measuring...", total=len(selected_fovs))
        for i, fov_info in enumerate(selected_fovs):
            fov_config = store.get_fov_config(fov_info.id)
            if fov_config:
                count = measurer.measure_fov(
                    store, fov_id=fov_info.id, channels=ch_names,
                    segmentation_id=fov_config[0].segmentation_id,
                )
                total_measurements += count
            progress.update(
                task, completed=i + 1,
                description=f"Measuring {fov_info.display_name}",
            )

    console.print(f"\n[green]Measurement complete[/green]")
    console.print(f"  FOVs: {len(selected_fovs)}")
    console.print(f"  Channels: {len(ch_names)}")
    console.print(f"  Measurements: {total_measurements}")

    # =================================================================
    # Stage 3: Thresholding + particle analysis (interactive per FOV)
    # =================================================================
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold]Stage 3: Thresholding + particle analysis[/bold]")

    total_particles = 0
    fovs_thresholded = 0

    for thr_channel in threshold_channels:
        console.print(f"\n[bold]--- Threshold channel: {thr_channel} ---[/bold]")
        for fov_info in selected_fovs:
            processed, particles = _threshold_fov(
                store, fov_info, thr_channel, grouping_channel, grouping_metric,
                gaussian_sigma=gaussian_sigma,
                min_particle_area=wf_min_particle_area,
            )
            fovs_thresholded += processed
            total_particles += particles

    console.print(f"\n[green]Thresholding complete[/green]")
    console.print(f"  FOVs processed: {fovs_thresholded}")
    console.print(f"  Total particles: {total_particles}")

    # =================================================================
    # Stage 4: Prism CSV export
    # =================================================================
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold]Stage 4: Prism CSV export[/bold]")

    try:
        with console.status("[bold blue]Exporting Prism-format CSVs..."):
            result = store.export_prism_csv(out_dir)

        if result["files_written"] == 0:
            console.print("[yellow]No measurements found to export.[/yellow]")
        else:
            console.print(
                f"[green]Prism export complete![/green]\n"
                f"  Directory: {out_dir}\n"
                f"  Channels: {result['channels_exported']}\n"
                f"  Files written: {result['files_written']}"
            )
    except OSError as exc:
        console.print(f"[red]Export failed:[/red] {exc}")

    # =================================================================
    # Final summary
    # =================================================================
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print(f"[bold green]Workflow complete![/bold green]")
    console.print(f"  Cells segmented:   {seg_result.cell_count}")
    console.print(f"  Measurements:      {total_measurements}")
    console.print(f"  Particles found:   {total_particles}")
    console.print(f"  Export directory:   {out_dir}")
    console.print()


def _assign_original_seg_to_derived(
    store: "ExperimentStore",
    original_fov_id: int,
    derived_fov_id: int,
) -> None:
    """Assign the cellular segmentation from original FOV to a derived FOV."""
    from percell3.measure.auto_measure import on_config_changed

    orig_config = store.get_fov_config(original_fov_id)
    cellular_entries = [e for e in orig_config if e.segmentation_id is not None]
    if not cellular_entries:
        return
    seg_id = cellular_entries[0].segmentation_id

    # Clear auto-created whole-field config on derived FOV
    store.delete_fov_config_for_fov(derived_fov_id)

    # Assign original segmentation
    store.set_fov_config_entry(derived_fov_id, seg_id)
    on_config_changed(store, derived_fov_id)


def _decapping_sensor_workflow(state: MenuState) -> None:
    """10-step decapping sensor pipeline.

    Steps:
      1. Grouped thresholding on original FOVs (interactive napari)
      2. Split-halo condensate analysis → delete condensed, keep dilute
      3. Auto-assign original segmentation to step 2 FOVs
      4. Grouped thresholding on step 2 FOVs (interactive napari)
      5. Split-halo again on step 2 FOVs → delete condensed, keep dilute
      6. Auto-assign original segmentation to step 5 FOVs
      7. Grouped thresholding on step 5 FOVs (interactive napari)
      8. BG subtraction (step 5 FOVs as histogram, originals as apply)
      9. Auto-assign original segmentation to step 8 FOVs
     10. Assign thresholds (all step 1 + matching step 7) to step 8 FOVs
    """
    from percell3.plugins.registry import PluginRegistry

    store = state.require_experiment()

    # ── Prerequisites ────────────────────────────────────────────────
    channels = store.get_channels()
    if not channels:
        console.print("[red]No channels found.[/red] Import images first.")
        return

    ch_names = [ch.name for ch in channels]

    all_fovs = store.get_fovs()
    if not all_fovs:
        console.print("[red]No FOVs found.[/red] Import images first.")
        return

    # Filter to FOVs with cellular segmentation and cells
    seg_summary = store.get_fov_segmentation_summary()
    fovs_with_cells = [f for f in all_fovs if seg_summary.get(f.id, (0, None))[0] > 0]
    if not fovs_with_cells:
        console.print("[red]No FOVs with segmented cells.[/red] Segment cells first.")
        return

    registry = PluginRegistry()
    registry.discover()

    # Verify required plugins
    try:
        registry.get_plugin("split_halo_condensate_analysis")
        registry.get_plugin("threshold_bg_subtraction")
    except KeyError as e:
        console.print(f"[red]Required plugin not found: {e}[/red]")
        return

    # ── Upfront Parameter Collection ─────────────────────────────────
    console.print("\n[bold]DECAPPING SENSOR WORKFLOW[/bold]")
    console.print("[dim]10-step pipeline: threshold → split-halo → threshold → "
                  "split-halo → threshold → BG subtraction → assign[/dim]\n")

    # FOV selection
    console.print("[bold]Select FOVs to process:[/bold]")
    _show_fov_status_table(fovs_with_cells, seg_summary)
    if len(fovs_with_cells) == 1:
        console.print(f"  [dim](auto-selected: {fovs_with_cells[0].display_name})[/dim]")
        selected_fovs = fovs_with_cells
    else:
        selected_fovs = _select_fovs_from_table(fovs_with_cells)

    fov_display_names = [f.display_name for f in selected_fovs]

    # Thresholding parameters (shared across steps 1, 4, 7)
    console.print("\n[bold]Thresholding Parameters[/bold]")
    console.print("  [dim]Used for all three thresholding steps (1, 4, 7).[/dim]\n")

    console.print("[bold]Grouping channel:[/bold]")
    grouping_channel = numbered_select_one(ch_names, "Grouping channel")

    console.print("\n[bold]Grouping metric:[/bold]")
    metric_choices = ["mean_intensity", "median_intensity", "integrated_intensity"]
    grouping_metric = numbered_select_one(metric_choices, "Metric")

    console.print("\n[bold]Threshold channel:[/bold]")
    threshold_channel = numbered_select_one(ch_names, "Threshold channel")

    console.print("\n[bold]Gaussian sigma for steps 1 & 4 (optional):[/bold]")
    sigma_str = menu_prompt("Gaussian sigma (blank = none)", default="")
    gaussian_sigma_early: float | None = None
    if sigma_str:
        try:
            gaussian_sigma_early = float(sigma_str)
        except ValueError:
            console.print("[yellow]Invalid sigma, using none.[/yellow]")

    console.print("\n[bold]Gaussian sigma for step 7 (optional):[/bold]")
    sigma_str_7 = menu_prompt("Gaussian sigma (blank = none)", default="")
    gaussian_sigma_step7: float | None = None
    if sigma_str_7:
        try:
            gaussian_sigma_step7 = float(sigma_str_7)
        except ValueError:
            console.print("[yellow]Invalid sigma, using none.[/yellow]")

    console.print("\n[bold]Min particle area:[/bold]")
    area_str = menu_prompt("Min particle area in pixels", default="1")
    try:
        min_particle_area = int(area_str)
    except ValueError:
        console.print("[yellow]Invalid area, using default of 1.[/yellow]")
        min_particle_area = 1

    # Split-halo parameters (shared for steps 2 and 5)
    console.print("\n[bold]Split-Halo Parameters[/bold]")
    console.print("  [dim]Used for both split-halo steps (2, 5).[/dim]\n")

    console.print("[bold]Measurement channel:[/bold]")
    meas_channel = numbered_select_one(ch_names, "Measurement channel")

    console.print("\n[bold]Particle mask channel:[/bold]")
    console.print("  [dim]Thresholds on this channel will be created in step 1.[/dim]")
    particle_channel = numbered_select_one(ch_names, "Particle mask channel")

    other_channels = [c for c in ch_names if c != particle_channel]
    exclusion_channel = None
    if other_channels:
        console.print("\n[bold]Exclusion mask channel (optional):[/bold]")
        excl_choices = ["(none)"] + other_channels
        excl_choice = numbered_select_one(excl_choices, "Exclusion mask")
        if excl_choice != "(none)":
            exclusion_channel = excl_choice

    console.print("\n[bold]Ring dilation pixels:[/bold]")
    ring_str = menu_prompt("Ring dilation pixels", default="5")
    try:
        ring_dilation_pixels = int(ring_str)
    except ValueError:
        ring_dilation_pixels = 5

    console.print("\n[bold]Exclusion dilation pixels:[/bold]")
    excl_dil_str = menu_prompt("Exclusion dilation pixels", default="5")
    try:
        exclusion_dilation_pixels = int(excl_dil_str)
    except ValueError:
        exclusion_dilation_pixels = 5

    console.print("\n[bold]Normalization channel (optional):[/bold]")
    norm_choices = ["(none)"] + ch_names
    norm_choice = numbered_select_one(norm_choices, "Normalization channel")
    normalization_channel = None if norm_choice == "(none)" else norm_choice

    # BG subtraction channel
    console.print("\n[bold]BG Subtraction Channel[/bold]")
    console.print("  [dim]Channel for background subtraction (may differ from threshold channel).[/dim]\n")
    bg_channel = numbered_select_one(ch_names, "BG subtraction channel")

    # 6 naming prefixes
    console.print("\n[bold]Naming Prefixes[/bold]")
    console.print("  [dim]Enter 6 prefixes for each step's outputs.[/dim]\n")

    console.print("[bold]Step 1 threshold prefix:[/bold]")
    step1_prefix = _prompt_prefix(fov_display_names, suffix_example="g1")

    console.print("\n[bold]Step 2 split-halo prefix:[/bold]")
    step2_prefix = _prompt_prefix(fov_display_names, suffix_example="dilute_phase")

    console.print("\n[bold]Step 4 threshold prefix:[/bold]")
    step4_prefix = _prompt_prefix(fov_display_names, suffix_example="g1")

    console.print("\n[bold]Step 5 split-halo prefix:[/bold]")
    step5_prefix = _prompt_prefix(fov_display_names, suffix_example="dilute_phase")

    console.print("\n[bold]Step 7 threshold prefix:[/bold]")
    step7_prefix = _prompt_prefix(fov_display_names, suffix_example="g1")

    console.print("\n[bold]Step 8 BG subtraction prefix:[/bold]")
    step8_prefix = _prompt_prefix(fov_display_names, suffix_example=bg_channel)

    # Confirmation summary
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]Decapping Sensor Workflow Summary[/bold]")
    console.print(f"  FOVs:                  {len(selected_fovs)}")
    console.print(f"  Grouping channel:      {grouping_channel}")
    console.print(f"  Grouping metric:       {grouping_metric}")
    console.print(f"  Threshold channel:     {threshold_channel}")
    console.print(f"  Gaussian sigma (1,4):  {gaussian_sigma_early or '(none)'}")
    console.print(f"  Gaussian sigma (7):    {gaussian_sigma_step7 or '(none)'}")
    console.print(f"  Min particle area:     {min_particle_area}")
    console.print(f"  Measurement channel:   {meas_channel}")
    console.print(f"  Particle mask:         {particle_channel}")
    console.print(f"  Exclusion mask:        {exclusion_channel or '(none)'}")
    console.print(f"  Ring dilation:         {ring_dilation_pixels} px")
    console.print(f"  Exclusion dilation:    {exclusion_dilation_pixels} px")
    console.print(f"  Normalization:         {normalization_channel or '(none)'}")
    console.print(f"  BG subtraction ch:     {bg_channel}")
    console.print(f"  Prefixes:")
    console.print(f"    Step 1 (threshold):  {step1_prefix}")
    console.print(f"    Step 2 (split-halo): {step2_prefix}")
    console.print(f"    Step 4 (threshold):  {step4_prefix}")
    console.print(f"    Step 5 (split-halo): {step5_prefix}")
    console.print(f"    Step 7 (threshold):  {step7_prefix}")
    console.print(f"    Step 8 (BG sub):     {step8_prefix}")

    if numbered_select_one(["Yes", "No"], "\nProceed?") != "Yes":
        console.print("[yellow]Workflow cancelled.[/yellow]")
        return

    # ── Lineage tracking dicts ───────────────────────────────────────
    # original_fov_id → step2_dilute_fov_id
    step2_lineage: dict[int, int] = {}
    # step2_fov_id → step5_dilute_fov_id
    step5_lineage: dict[int, int] = {}
    # original_fov_id → list of step8_bgsub_fov_ids
    step8_lineage: dict[int, list[int]] = {}
    # step1 thresholds: original_fov_id → list of threshold_ids
    step1_thresholds: dict[int, list[int]] = {}
    # step7 thresholds: step5_fov_id → list of threshold_ids
    step7_thresholds: dict[int, list[int]] = {}

    # ── STEP 1: Grouped thresholding on original FOVs ────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 1: Grouped thresholding on original FOVs[/bold]")
    console.print("[dim]Interactive napari thresholding for each FOV.[/dim]\n")

    for fov_info in selected_fovs:
        _threshold_fov(
            store, fov_info,
            threshold_channel=threshold_channel,
            grouping_channel=grouping_channel,
            grouping_metric=grouping_metric,
            gaussian_sigma=gaussian_sigma_early,
            min_particle_area=min_particle_area,
            name_prefix=step1_prefix,
        )
        # Collect thresholds created for this FOV
        all_thrs = store.get_thresholds()
        fov_thrs = [
            t for t in all_thrs
            if t.source_fov_id == fov_info.id
            and t.name.startswith(f"{step1_prefix}_")
        ]
        step1_thresholds[fov_info.id] = [t.id for t in fov_thrs]

    console.print(f"\n[green]Step 1 complete.[/green] "
                  f"Thresholds created for {len(step1_thresholds)} FOVs.")

    # ── STEP 2: Split-halo on original FOVs ──────────────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 2: Split-halo condensate analysis[/bold]\n")

    # Get cell_ids for selected FOVs
    cell_ids = []
    for fov in selected_fovs:
        cells_df = store.get_cells(fov_id=fov.id)
        cell_ids.extend(cells_df["id"].tolist())

    split_halo_params = {
        "measurement_channel": meas_channel,
        "particle_channel": particle_channel,
        "exclusion_channel": exclusion_channel,
        "ring_dilation_pixels": ring_dilation_pixels,
        "exclusion_dilation_pixels": exclusion_dilation_pixels,
        "normalization_channel": normalization_channel,
        "save_images": True,
        "name_prefix": step2_prefix,
    }

    with make_progress() as progress:
        task = progress.add_task("Split-halo analysis...", total=len(selected_fovs))

        def on_progress_s2(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        registry.run_plugin(
            "split_halo_condensate_analysis", store,
            cell_ids=cell_ids, parameters=split_halo_params,
            progress_callback=on_progress_s2,
        )

    # Delete condensed-phase FOVs and build step2_lineage
    all_fovs_after = store.get_fovs()
    fov_by_name = {f.display_name: f for f in all_fovs_after}

    for orig_fov in selected_fovs:
        # Delete condensed phase
        condensed_name = f"{step2_prefix}_{orig_fov.display_name}_condensed_phase"
        if condensed_name in fov_by_name:
            store.delete_fov(fov_by_name[condensed_name].id)
            console.print(f"  Deleted condensed: {condensed_name}")

        # Track dilute phase
        dilute_name = f"{step2_prefix}_{orig_fov.display_name}_dilute_phase"
        if dilute_name in fov_by_name:
            step2_lineage[orig_fov.id] = fov_by_name[dilute_name].id
        else:
            console.print(f"  [yellow]Warning: dilute FOV not found for {orig_fov.display_name}[/yellow]")

    console.print(f"\n[green]Step 2 complete.[/green] "
                  f"Dilute FOVs created: {len(step2_lineage)}")

    # ── STEP 3: Assign original segmentation to step 2 FOVs ─────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 3: Assign segmentation to step 2 FOVs[/bold]\n")

    for orig_fov_id, step2_fov_id in step2_lineage.items():
        _assign_original_seg_to_derived(store, orig_fov_id, step2_fov_id)
        step2_fov = store.get_fov_by_id(step2_fov_id)
        console.print(f"  Assigned segmentation to {step2_fov.display_name}")

    console.print(f"\n[green]Step 3 complete.[/green]")

    # ── STEP 4: Grouped thresholding on step 2 FOVs ─────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 4: Grouped thresholding on step 2 (dilute) FOVs[/bold]")
    console.print("[dim]Interactive napari thresholding for each dilute FOV.[/dim]\n")

    step2_fovs = [store.get_fov_by_id(fov_id) for fov_id in step2_lineage.values()]
    for fov_info in step2_fovs:
        _threshold_fov(
            store, fov_info,
            threshold_channel=threshold_channel,
            grouping_channel=grouping_channel,
            grouping_metric=grouping_metric,
            gaussian_sigma=gaussian_sigma_early,
            min_particle_area=min_particle_area,
            name_prefix=step4_prefix,
        )

    console.print(f"\n[green]Step 4 complete.[/green]")

    # ── STEP 5: Split-halo on step 2 FOVs ───────────────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 5: Split-halo on step 2 (dilute) FOVs[/bold]\n")

    # Get cell_ids for step 2 FOVs
    step2_cell_ids = []
    for fov_info in step2_fovs:
        cells_df = store.get_cells(fov_id=fov_info.id)
        step2_cell_ids.extend(cells_df["id"].tolist())

    step5_halo_params = {
        "measurement_channel": meas_channel,
        "particle_channel": particle_channel,
        "exclusion_channel": exclusion_channel,
        "ring_dilation_pixels": ring_dilation_pixels,
        "exclusion_dilation_pixels": exclusion_dilation_pixels,
        "normalization_channel": normalization_channel,
        "save_images": True,
        "name_prefix": step5_prefix,
    }

    with make_progress() as progress:
        task = progress.add_task("Split-halo analysis (round 2)...", total=len(step2_fovs))

        def on_progress_s5(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        registry.run_plugin(
            "split_halo_condensate_analysis", store,
            cell_ids=step2_cell_ids, parameters=step5_halo_params,
            progress_callback=on_progress_s5,
        )

    # Delete condensed-phase FOVs and build step5_lineage
    all_fovs_after = store.get_fovs()
    fov_by_name = {f.display_name: f for f in all_fovs_after}

    for step2_fov in step2_fovs:
        condensed_name = f"{step5_prefix}_{step2_fov.display_name}_condensed_phase"
        if condensed_name in fov_by_name:
            store.delete_fov(fov_by_name[condensed_name].id)
            console.print(f"  Deleted condensed: {condensed_name}")

        dilute_name = f"{step5_prefix}_{step2_fov.display_name}_dilute_phase"
        if dilute_name in fov_by_name:
            step5_lineage[step2_fov.id] = fov_by_name[dilute_name].id
        else:
            console.print(f"  [yellow]Warning: dilute FOV not found for {step2_fov.display_name}[/yellow]")

    console.print(f"\n[green]Step 5 complete.[/green] "
                  f"Dilute FOVs created: {len(step5_lineage)}")

    # ── STEP 6: Assign original segmentation to step 5 FOVs ─────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 6: Assign segmentation to step 5 FOVs[/bold]\n")

    for orig_fov_id, step2_fov_id in step2_lineage.items():
        step5_fov_id = step5_lineage.get(step2_fov_id)
        if step5_fov_id is not None:
            _assign_original_seg_to_derived(store, orig_fov_id, step5_fov_id)
            step5_fov = store.get_fov_by_id(step5_fov_id)
            console.print(f"  Assigned segmentation to {step5_fov.display_name}")

    console.print(f"\n[green]Step 6 complete.[/green]")

    # ── STEP 7: Grouped thresholding on step 5 FOVs ─────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 7: Grouped thresholding on step 5 (2nd dilute) FOVs[/bold]")
    console.print("[dim]Interactive napari thresholding for each FOV.[/dim]\n")

    step5_fovs = [store.get_fov_by_id(fov_id) for fov_id in step5_lineage.values()]
    for fov_info in step5_fovs:
        _threshold_fov(
            store, fov_info,
            threshold_channel=threshold_channel,
            grouping_channel=grouping_channel,
            grouping_metric=grouping_metric,
            gaussian_sigma=gaussian_sigma_step7,
            min_particle_area=min_particle_area,
            name_prefix=step7_prefix,
        )
        # Collect step 7 thresholds
        all_thrs = store.get_thresholds()
        fov_thrs = [
            t for t in all_thrs
            if t.source_fov_id == fov_info.id
            and t.name.startswith(f"{step7_prefix}_")
        ]
        step7_thresholds[fov_info.id] = [t.id for t in fov_thrs]

    console.print(f"\n[green]Step 7 complete.[/green] "
                  f"Thresholds created for {len(step7_thresholds)} FOVs.")

    # ── STEP 8: BG subtraction ───────────────────────────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 8: Threshold background subtraction[/bold]\n")

    # Build pairings: histogram=step5 FOV, apply=original FOV
    pairings: list[dict[str, int]] = []
    for orig_fov_id, step2_fov_id in step2_lineage.items():
        step5_fov_id = step5_lineage.get(step2_fov_id)
        if step5_fov_id is not None:
            pairings.append({
                "histogram_fov_id": step5_fov_id,
                "apply_fov_id": orig_fov_id,
            })

    if not pairings:
        console.print("[red]No valid pairings for BG subtraction.[/red]")
        return

    console.print(f"  Auto-paired {len(pairings)} histogram → apply FOV(s)")
    for p in pairings:
        hist_name = store.get_fov_by_id(p["histogram_fov_id"]).display_name
        apply_name = store.get_fov_by_id(p["apply_fov_id"]).display_name
        console.print(f"    {hist_name}  →  {apply_name}")

    bg_params = {
        "channel": bg_channel,
        "pairings": pairings,
        "name_prefix": step8_prefix,
    }

    with make_progress() as progress:
        task = progress.add_task("Background subtraction...", total=len(pairings))

        def on_progress_s8(current, total, fov_name):
            progress.update(task, total=total, completed=current,
                            description=f"Processing {fov_name}")

        result = registry.run_plugin(
            "threshold_bg_subtraction", store,
            parameters=bg_params, progress_callback=on_progress_s8,
        )

    # Build step8_lineage by finding derived FOV names
    all_fovs_after = store.get_fovs()
    fov_by_name = {f.display_name: f for f in all_fovs_after}

    for orig_fov in selected_fovs:
        bgsub_fov_ids = []
        for fov_after in all_fovs_after:
            if fov_after.display_name.startswith(f"{step8_prefix}_{orig_fov.display_name}_"):
                bgsub_fov_ids.append(fov_after.id)
        if bgsub_fov_ids:
            step8_lineage[orig_fov.id] = bgsub_fov_ids

    for w in result.warnings:
        console.print(f"  [yellow]Warning: {w}[/yellow]")

    console.print(f"\n[green]Step 8 complete.[/green] "
                  f"BG-subtracted FOVs: {sum(len(v) for v in step8_lineage.values())}")

    # ── STEP 9: Assign original segmentation to step 8 FOVs ─────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 9: Assign segmentation to BG-subtracted FOVs[/bold]\n")

    for orig_fov_id, bgsub_fov_ids in step8_lineage.items():
        for bgsub_fov_id in bgsub_fov_ids:
            _assign_original_seg_to_derived(store, orig_fov_id, bgsub_fov_id)
            bgsub_fov = store.get_fov_by_id(bgsub_fov_id)
            console.print(f"  Assigned segmentation to {bgsub_fov.display_name}")

    console.print(f"\n[green]Step 9 complete.[/green]")

    # ── STEP 10: Assign thresholds to step 8 FOVs ───────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold]STEP 10: Assign thresholds to BG-subtracted FOVs[/bold]\n")

    from percell3.measure.auto_measure import on_config_changed

    threshold_assignments = 0
    all_bgsub_fov_ids = [
        fov_id
        for fov_ids in step8_lineage.values()
        for fov_id in fov_ids
    ]
    total_bgsub = len(all_bgsub_fov_ids)

    for idx, (orig_fov_id, bgsub_fov_ids) in enumerate(step8_lineage.items()):
        for bgsub_fov_id in bgsub_fov_ids:
            bgsub_fov_info = store.get_fov_by_id(bgsub_fov_id)
            console.print(f"  Assigning thresholds to {bgsub_fov_info.display_name}...")

            config = store.get_fov_config(bgsub_fov_id)
            if not config:
                continue
            seg_id = config[0].segmentation_id

            # Assign ALL step 1 thresholds for this original FOV
            for thr_id in step1_thresholds.get(orig_fov_id, []):
                store.set_fov_config_entry(
                    bgsub_fov_id, seg_id,
                    threshold_id=thr_id,
                    scopes=["whole_cell", "mask_inside", "mask_outside"],
                )
                threshold_assignments += 1

            # Assign matching step 7 threshold by checking name in BG-sub FOV name
            for step5_fov_id, thr_ids in step7_thresholds.items():
                for thr_id in thr_ids:
                    thr_info = store.get_threshold(thr_id)
                    if thr_info.name in bgsub_fov_info.display_name:
                        store.set_fov_config_entry(
                            bgsub_fov_id, seg_id,
                            threshold_id=thr_id,
                            scopes=["whole_cell", "mask_inside", "mask_outside"],
                        )
                        threshold_assignments += 1
                        break

            console.print(f"    Auto-measuring {bgsub_fov_info.display_name}...")
            on_config_changed(store, bgsub_fov_id)
            console.print(f"    [green]Done[/green]")

    console.print(f"\n[green]Step 10 complete.[/green] "
                  f"Threshold assignments: {threshold_assignments}")

    # ── Final Summary ────────────────────────────────────────────────
    console.print(f"\n[bold]{'='*60}[/bold]")
    console.print("[bold green]Decapping sensor workflow complete![/bold green]")
    console.print(f"  Original FOVs processed:   {len(selected_fovs)}")
    console.print(f"  Step 2 dilute FOVs:        {len(step2_lineage)}")
    console.print(f"  Step 5 dilute FOVs:        {len(step5_lineage)}")
    console.print(f"  Step 8 BG-sub FOVs:        {sum(len(v) for v in step8_lineage.values())}")
    console.print(f"  Step 1 threshold groups:   {sum(len(v) for v in step1_thresholds.values())}")
    console.print(f"  Step 7 threshold groups:   {sum(len(v) for v in step7_thresholds.values())}")
    console.print(f"  Threshold assignments:     {threshold_assignments}")
    console.print()


def _run_workflow(state: MenuState) -> None:
    """Legacy workflow handler — kept for backwards compatibility."""
    _particle_workflow(state)


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
