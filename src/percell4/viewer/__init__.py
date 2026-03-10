"""PerCell 4 interactive napari viewer.

napari is an optional dependency. Install with: ``pip install percell4[napari]``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore


def _napari_available() -> bool:
    """Check if napari is importable without keeping it in memory."""
    try:
        import napari  # noqa: F401

        return True
    except ImportError:
        return False


NAPARI_AVAILABLE: bool = _napari_available()


def launch_viewer(
    store: "ExperimentStore",
    fov_id: bytes | None = None,
) -> None:
    """Launch interactive napari viewer for an experiment.

    Opens napari pre-loaded with experiment channel images, segmentation
    labels, and threshold masks. When the viewer closes, any label edits
    are saved back as a new segmentation.

    Args:
        store: An open ExperimentStore.
        fov_id: Optional FOV UUID to open. If None, opens the first FOV.

    Raises:
        ImportError: If napari is not installed.
    """
    if not NAPARI_AVAILABLE:
        raise ImportError(
            "napari is required for the viewer. "
            "Install with: pip install 'napari[all]'"
        )
    from percell4.viewer._viewer import _launch

    _launch(store, fov_id=fov_id)
