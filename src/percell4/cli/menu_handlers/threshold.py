"""Threshold handler -- placeholder for interactive thresholding."""

from __future__ import annotations

from percell4.cli.menu_system import MenuState, require_experiment
from percell4.cli.utils import print_warning


def threshold_handler(state: MenuState) -> None:
    """Placeholder: interactive thresholding requires napari."""
    require_experiment(state)
    print_warning("Interactive thresholding requires napari.")
    print_warning("Use the CLI 'threshold' command for manual thresholds.")
