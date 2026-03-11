"""Custom menu handlers for analysis plugins requiring parameter prompting.

Each handler prompts for plugin-specific parameters using numbered_select_one,
numbered_select_many, and menu_prompt, then runs the plugin with progress.
"""

from __future__ import annotations

from percell4.cli.menu_system import (
    MenuState,
    menu_prompt,
    numbered_select_many,
    numbered_select_one,
    require_experiment,
)
from percell4.cli.utils import console, make_progress, print_error, print_success, print_warning


def _get_active_fov_ids(store):
    """Return (fovs, fov_ids) for all non-deleted FOVs."""
    exp = store.db.get_experiment()
    fovs = store.db.get_fovs(exp["id"])
    active = [
        f for f in fovs
        if f["status"] not in ("deleted", "deleting", "error")
    ]
    return active


def _select_fovs(store):
    """Prompt user to select FOVs. Returns list of FOV dicts."""
    fovs = _get_active_fov_ids(store)
    if not fovs:
        print_warning("No active FOVs to process")
        return []

    fov_names = [f["auto_name"] or f"FOV-{i+1}" for i, f in enumerate(fovs)]
    selected_names = numbered_select_many(fov_names, "FOVs to process (numbers, 'all', or blank=all)")
    return [fovs[fov_names.index(n)] for n in selected_names]


def _get_channel_names(store):
    """Return list of channel names for current experiment."""
    exp = store.db.get_experiment()
    channels = store.db.get_channels(exp["id"])
    return [ch["name"] for ch in channels]


def _make_progress_callback(progress, task):
    """Create an on_progress callback for plugin.run()."""
    def on_progress(current: int, total: int, msg: str = "") -> None:
        progress.update(task, completed=current, total=total)
    return on_progress


# ---------------------------------------------------------------------------
# Image Calculator
# ---------------------------------------------------------------------------

def image_calculator_handler(state: MenuState) -> None:
    """Prompt for image calculator parameters and run plugin."""
    store = require_experiment(state)

    from percell4.plugins.image_calculator import ImageCalculatorPlugin
    from percell4.plugins.image_calculator_core import OPERATIONS

    selected_fovs = _select_fovs(store)
    if not selected_fovs:
        return

    ch_names = _get_channel_names(store)
    if not ch_names:
        print_warning("No channels in experiment")
        return

    console.print("\n[bold]Image Calculator[/bold]")

    modes = ["single_channel", "two_channel", "zero_to_nan"]
    mode = numbered_select_one(modes, "Mode")

    if mode == "zero_to_nan":
        channels = numbered_select_many(ch_names, "Channels to convert zeros to NaN")
        fov_ids = [f["id"] for f in selected_fovs]

        plugin = ImageCalculatorPlugin()
        try:
            with make_progress() as progress:
                task = progress.add_task("Processing...", total=len(fov_ids))
                result = plugin.run(
                    store, fov_ids,
                    mode="zero_to_nan",
                    operation="zero_to_nan",
                    channel_a=channels[0],
                    channels=channels,
                    on_progress=_make_progress_callback(progress, task),
                )
            print_success(
                f"Created {result.derived_fovs_created} derived FOVs "
                f"({result.fovs_processed} FOVs processed)"
            )
            if result.errors:
                for err in result.errors:
                    print_warning(err)
        except Exception as e:
            print_error(str(e))
        return

    # Regular operations
    ops_list = list(OPERATIONS)
    operation = numbered_select_one(ops_list, "Operation")
    channel_a = numbered_select_one(ch_names, "Channel A")

    channel_b = None
    constant = None

    if mode == "single_channel":
        constant_str = menu_prompt("Constant value", default="0")
        try:
            constant = float(constant_str)
        except ValueError:
            print_error(f"Invalid number: {constant_str}")
            return
    else:
        remaining = [c for c in ch_names if c != channel_a]
        if not remaining:
            print_error("Need at least 2 channels for two_channel mode")
            return
        channel_b = numbered_select_one(remaining, "Channel B")

    fov_ids = [f["id"] for f in selected_fovs]
    plugin = ImageCalculatorPlugin()
    try:
        with make_progress() as progress:
            task = progress.add_task("Processing...", total=len(fov_ids))
            result = plugin.run(
                store, fov_ids,
                mode=mode,
                operation=operation,
                channel_a=channel_a,
                channel_b=channel_b,
                constant=constant,
                on_progress=_make_progress_callback(progress, task),
            )
        print_success(
            f"Created {result.derived_fovs_created} derived FOVs "
            f"({result.fovs_processed} FOVs processed)"
        )
        if result.errors:
            for err in result.errors:
                print_warning(err)
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Condensate Partitioning Ratio
# ---------------------------------------------------------------------------

def condensate_partitioning_ratio_handler(state: MenuState) -> None:
    """Prompt for CPR parameters and run plugin."""
    store = require_experiment(state)

    from percell4.plugins.condensate_partitioning_ratio import (
        CondensatePartitioningRatioPlugin,
    )

    selected_fovs = _select_fovs(store)
    if not selected_fovs:
        return

    ch_names = _get_channel_names(store)
    if not ch_names:
        print_warning("No channels in experiment")
        return

    console.print("\n[bold]Condensate Partitioning Ratio[/bold]")

    meas_channel = numbered_select_one(ch_names, "Measurement channel")
    particle_channel = numbered_select_one(ch_names, "Particle channel (threshold source)")

    gap_str = menu_prompt("Gap pixels (exclusion zone)", default="3")
    ring_str = menu_prompt("Ring pixels (ring width)", default="2")
    min_ring_str = menu_prompt("Min ring pixels", default="10")
    export_csv = menu_prompt("Export CSV? (y/n)", default="y").lower().startswith("y")

    try:
        gap_pixels = int(gap_str)
        ring_pixels = int(ring_str)
        min_ring_pixels = int(min_ring_str)
    except ValueError:
        print_error("Invalid integer value for pixel parameters")
        return

    fov_ids = [f["id"] for f in selected_fovs]
    plugin = CondensatePartitioningRatioPlugin()
    try:
        with make_progress() as progress:
            task = progress.add_task("Processing...", total=len(fov_ids))
            result = plugin.run(
                store, fov_ids,
                measurement_channel=meas_channel,
                particle_channel=particle_channel,
                gap_pixels=gap_pixels,
                ring_pixels=ring_pixels,
                min_ring_pixels=min_ring_pixels,
                export_csv=export_csv,
                on_progress=_make_progress_callback(progress, task),
            )
        print_success(
            f"Processed {result.rois_processed} ROIs, "
            f"{result.measurements_added} particles measured"
        )
        if result.errors:
            for err in result.errors:
                print_warning(err)
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Local Background Subtraction
# ---------------------------------------------------------------------------

def local_bg_subtraction_handler(state: MenuState) -> None:
    """Prompt for local BG subtraction parameters and run plugin."""
    store = require_experiment(state)

    from percell4.plugins.local_bg_subtraction import LocalBGSubtractionPlugin

    selected_fovs = _select_fovs(store)
    if not selected_fovs:
        return

    ch_names = _get_channel_names(store)
    if not ch_names:
        print_warning("No channels in experiment")
        return

    console.print("\n[bold]Local Background Subtraction[/bold]")

    meas_channel = numbered_select_one(ch_names, "Measurement channel")
    particle_channel = numbered_select_one(ch_names, "Particle channel (threshold source)")

    dilation_str = menu_prompt("Dilation pixels (ring size)", default="5")
    max_bg_str = menu_prompt("Max background (blank=auto)", default="")
    export_csv = menu_prompt("Export CSV? (y/n)", default="y").lower().startswith("y")

    norm_channel = None
    if len(ch_names) > 1:
        use_norm = menu_prompt("Use normalization channel? (y/n)", default="n")
        if use_norm.lower().startswith("y"):
            norm_channel = numbered_select_one(ch_names, "Normalization channel")

    try:
        dilation_pixels = int(dilation_str)
    except ValueError:
        print_error(f"Invalid integer: {dilation_str}")
        return

    max_background = None
    if max_bg_str.strip():
        try:
            max_background = float(max_bg_str)
        except ValueError:
            print_error(f"Invalid number: {max_bg_str}")
            return

    fov_ids = [f["id"] for f in selected_fovs]
    plugin = LocalBGSubtractionPlugin()
    try:
        with make_progress() as progress:
            task = progress.add_task("Processing...", total=len(fov_ids))
            result = plugin.run(
                store, fov_ids,
                measurement_channel=meas_channel,
                particle_channel=particle_channel,
                dilation_pixels=dilation_pixels,
                max_background=max_background,
                normalization_channel=norm_channel,
                export_csv=export_csv,
                on_progress=_make_progress_callback(progress, task),
            )
        print_success(
            f"Processed {result.rois_processed} ROIs, "
            f"{result.measurements_added} particles measured"
        )
        if result.errors:
            for err in result.errors:
                print_warning(err)
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Split-Halo Condensate Analysis
# ---------------------------------------------------------------------------

def split_halo_handler(state: MenuState) -> None:
    """Prompt for split-halo analysis parameters and run plugin."""
    store = require_experiment(state)

    from percell4.plugins.split_halo_condensate_analysis import (
        SplitHaloCondensateAnalysisPlugin,
    )

    selected_fovs = _select_fovs(store)
    if not selected_fovs:
        return

    ch_names = _get_channel_names(store)
    if not ch_names:
        print_warning("No channels in experiment")
        return

    console.print("\n[bold]Split-Halo Condensate Analysis[/bold]")

    meas_channel = numbered_select_one(ch_names, "Measurement channel")
    particle_channel = numbered_select_one(ch_names, "Particle channel (threshold source)")

    ring_str = menu_prompt("Ring dilation pixels", default="5")
    excl_str = menu_prompt("Exclusion dilation pixels", default="5")
    max_bg_str = menu_prompt("Max background (blank=auto)", default="")
    export_csv = menu_prompt("Export CSV? (y/n)", default="y").lower().startswith("y")
    save_images = menu_prompt("Save derived FOV images? (y/n)", default="y").lower().startswith("y")

    norm_channel = None
    if len(ch_names) > 1:
        use_norm = menu_prompt("Use normalization channel? (y/n)", default="n")
        if use_norm.lower().startswith("y"):
            norm_channel = numbered_select_one(ch_names, "Normalization channel")

    try:
        ring_dilation = int(ring_str)
        excl_dilation = int(excl_str)
    except ValueError:
        print_error("Invalid integer for pixel parameters")
        return

    max_background = None
    if max_bg_str.strip():
        try:
            max_background = float(max_bg_str)
        except ValueError:
            print_error(f"Invalid number: {max_bg_str}")
            return

    fov_ids = [f["id"] for f in selected_fovs]
    plugin = SplitHaloCondensateAnalysisPlugin()
    try:
        with make_progress() as progress:
            task = progress.add_task("Processing...", total=len(fov_ids))
            result = plugin.run(
                store, fov_ids,
                measurement_channel=meas_channel,
                particle_channel=particle_channel,
                ring_dilation_pixels=ring_dilation,
                exclusion_dilation_pixels=excl_dilation,
                max_background=max_background,
                normalization_channel=norm_channel,
                export_csv=export_csv,
                save_images=save_images,
                on_progress=_make_progress_callback(progress, task),
            )
        print_success(
            f"Processed {result.rois_processed} ROIs, "
            f"{result.measurements_added} particles, "
            f"{result.derived_fovs_created} derived FOVs"
        )
        if result.errors:
            for err in result.errors:
                print_warning(err)
    except Exception as e:
        print_error(str(e))


# ---------------------------------------------------------------------------
# Threshold Background Subtraction
# ---------------------------------------------------------------------------

def threshold_bg_subtraction_handler(state: MenuState) -> None:
    """Prompt for threshold BG subtraction parameters and run plugin."""
    store = require_experiment(state)

    from percell4.plugins.threshold_bg_subtraction import (
        ThresholdBGSubtractionPlugin,
    )

    selected_fovs = _select_fovs(store)
    if not selected_fovs:
        return

    ch_names = _get_channel_names(store)
    if not ch_names:
        print_warning("No channels in experiment")
        return

    # Check for intensity groups
    exp = store.db.get_experiment()
    groups = store.db.get_intensity_groups(exp["id"])
    if not groups:
        print_warning(
            "No intensity groups found. "
            "Run 'Grouped intensity thresholding' first."
        )
        return

    console.print("\n[bold]Threshold Background Subtraction[/bold]")
    console.print(
        "[dim]Per-group BG subtraction with single derived FOV, "
        "NaN outside ROIs[/dim]\n"
    )

    # Show available groups
    group_names = sorted(set(g["name"] for g in groups))
    console.print(f"[dim]Intensity groups: {', '.join(group_names)}[/dim]")

    channel = numbered_select_one(ch_names, "Channel to subtract background from")

    fov_ids = [f["id"] for f in selected_fovs]
    plugin = ThresholdBGSubtractionPlugin()
    try:
        with make_progress() as progress:
            task = progress.add_task("Processing...", total=len(fov_ids))
            result = plugin.run(
                store, fov_ids,
                channel=channel,
                on_progress=_make_progress_callback(progress, task),
            )
        print_success(
            f"Created {result.derived_fovs_created} derived FOVs "
            f"({result.fovs_processed} FOVs processed)"
        )
        if result.errors:
            for err in result.errors:
                print_warning(err)
    except Exception as e:
        print_error(str(e))


# Map plugin names to custom handlers
PLUGIN_HANDLERS: dict[str, callable] = {
    "image_calculator": image_calculator_handler,
    "condensate_partitioning_ratio": condensate_partitioning_ratio_handler,
    "local_bg_subtraction": local_bg_subtraction_handler,
    "split_halo_condensate_analysis": split_halo_handler,
    "threshold_bg_subtraction": threshold_bg_subtraction_handler,
}
