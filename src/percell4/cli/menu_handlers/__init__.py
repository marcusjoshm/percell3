"""Menu handler modules for PerCell 4 interactive CLI.

Each module contains thin handler functions (< 100 lines) that
implement one category of the interactive menu.
"""

from __future__ import annotations

from percell4.cli.menu_system import Menu, MenuItem, MenuState, _MenuCancel


def build_main_menu(state: MenuState) -> Menu:
    """Assemble the top-level interactive menu.

    8 top-level items: Setup, Import/Export, Segment, Analyze,
    View, Config, Workflows, Plugins.

    Args:
        state: Shared session state.

    Returns:
        A Menu instance ready to run.
    """
    from percell4.cli.menu_handlers.setup import (
        create_experiment_handler,
        open_experiment_handler,
    )
    from percell4.cli.menu_handlers.import_handlers import import_images_handler
    from percell4.cli.menu_handlers.status import status_handler
    from percell4.cli.menu_handlers.segment import segment_handler
    from percell4.cli.menu_handlers.measure import measure_handler
    from percell4.cli.menu_handlers.threshold import threshold_handler
    from percell4.cli.menu_handlers.export import (
        export_csv_handler,
        export_prism_handler,
        export_tiff_handler,
    )
    from percell4.cli.menu_handlers.plugins import plugin_menu_handler
    from percell4.cli.menu_handlers.merge import merge_handler
    from percell4.cli.menu_handlers.viewer import viewer_handler
    from percell4.cli.menu_handlers.config import config_menu_handler

    # ----- 1. Setup -----
    def _setup_menu(st: MenuState) -> None:
        Menu(
            "SETUP",
            [
                MenuItem("1", "Create experiment", "Create a new .percell experiment", create_experiment_handler),
                MenuItem("2", "Open experiment", "Open an existing experiment", open_experiment_handler),
            ],
            st,
            return_home=True,
        ).run()
        raise _MenuCancel()

    # ----- 2. Import / Export -----
    def _import_export_menu(st: MenuState) -> None:
        Menu(
            "IMPORT / EXPORT",
            [
                MenuItem("1", "Import images", "Load TIFF, LIF, or CZI files", import_images_handler),
                MenuItem("2", "Export CSV", "Export measurements to CSV", export_csv_handler),
                MenuItem("3", "Export Prism", "Export per-channel CSVs for Prism", export_prism_handler),
                MenuItem("4", "Export TIFF", "Export FOV channels as TIFF files", export_tiff_handler),
                MenuItem("5", "Merge", "Merge another experiment", merge_handler),
            ],
            st,
            return_home=True,
        ).run()
        raise _MenuCancel()

    # ----- 3. Segment -----
    def _segment_menu(st: MenuState) -> None:
        Menu(
            "SEGMENT",
            [
                MenuItem("1", "Segment cells", "Run Cellpose segmentation", segment_handler),
            ],
            st,
        ).run()
        raise _MenuCancel()

    # ----- 4. Analyze -----
    def _analyze_menu(st: MenuState) -> None:
        Menu(
            "ANALYZE",
            [
                MenuItem("1", "Measure channels", "Measure intensities per ROI", measure_handler),
                MenuItem("2", "Threshold", "Apply intensity thresholds", threshold_handler),
                MenuItem("3", "Status", "Experiment dashboard", status_handler),
            ],
            st,
        ).run()
        raise _MenuCancel()

    # ----- 5. View -----
    # viewer_handler used directly (single item, no submenu needed)

    # ----- 6. Config -----
    # config_menu_handler builds its own submenu

    # ----- 7. Workflows -----
    def _workflows_menu(st: MenuState) -> None:
        from percell4.cli.menu_handlers.workflow import (
            particle_analysis_handler,
            decapping_sensor_handler,
        )
        Menu(
            "WORKFLOWS",
            [
                MenuItem("1", "Particle analysis", "Standard particle pipeline", particle_analysis_handler),
                MenuItem("2", "Decapping sensor", "BiFC split-Halo decapping assay", decapping_sensor_handler),
            ],
            st,
        ).run()
        raise _MenuCancel()

    # ----- 8. Plugins -----
    def _plugins_menu(st: MenuState) -> None:
        plugin_menu_handler(st)

    return Menu(
        "MAIN MENU",
        [
            MenuItem("1", "Setup", "Create and select experiments", _setup_menu),
            MenuItem("2", "Import / Export", "Import images, export data", _import_export_menu),
            MenuItem("3", "Segment", "Single-cell segmentation", _segment_menu),
            MenuItem("4", "Analyze", "Measure, threshold, and status", _analyze_menu),
            MenuItem("5", "View", "Open napari viewer", viewer_handler),
            MenuItem("6", "Config", "Conditions, bio reps, assignments", config_menu_handler),
            MenuItem("7", "Workflows", "Automated analysis pipelines", _workflows_menu),
            MenuItem("8", "Plugins", "Run analysis plugins", _plugins_menu),
        ],
        state,
        show_banner=True,
    )
