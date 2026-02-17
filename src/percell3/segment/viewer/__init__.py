"""PerCell 3 napari viewer — optional GUI for viewing and editing segmentation labels.

napari is an optional dependency. Install with: ``pip install percell3[napari]``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


def _napari_available() -> bool:
    """Check if napari is importable without keeping it in memory."""
    try:
        import napari  # noqa: F401

        return True
    except ImportError:
        return False


NAPARI_AVAILABLE: bool = _napari_available()


def launch_viewer(
    store: ExperimentStore,
    region: str,
    condition: str,
    channels: list[str] | None = None,
) -> int | None:
    """Launch napari to view and edit segmentation labels.

    Opens napari pre-loaded with experiment channel images and the most
    recent segmentation labels for the given region. When the viewer
    closes, any label edits are saved back to the ExperimentStore as a
    new segmentation run.

    Args:
        store: An open ExperimentStore.
        region: Region name to display.
        condition: Condition name.
        channels: Channel names to load. If None, all channels are loaded.

    Returns:
        The new segmentation run ID if labels were edited, or None if
        labels were unchanged.

    Raises:
        ImportError: If napari is not installed.
        RuntimeError: If no display server is available (headless).
        ValueError: If the region or condition does not exist.
    """
    if not NAPARI_AVAILABLE:
        raise ImportError(
            "napari is required for the viewer. "
            "Install with: pip install 'percell3[napari]'"
        )
    from percell3.segment.viewer._viewer import _launch

    return _launch(store, region, condition, channels)


def save_edited_labels(
    store: ExperimentStore,
    region: str,
    condition: str,
    edited_labels: "np.ndarray",
    parent_run_id: int | None,
    channel: str,
    pixel_size_um: float | None,
    region_id: int,
) -> int:
    """Save edited labels back to ExperimentStore (headless-safe).

    See :func:`percell3.segment.viewer._viewer.save_edited_labels` for
    full documentation. This wrapper does NOT require napari.
    """
    from percell3.segment.viewer._viewer import save_edited_labels as _impl

    return _impl(
        store, region, condition, edited_labels,
        parent_run_id, channel, pixel_size_um, region_id,
    )
