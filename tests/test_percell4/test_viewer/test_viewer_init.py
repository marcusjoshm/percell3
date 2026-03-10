"""Tests for percell4.viewer __init__ module."""

from __future__ import annotations

from unittest.mock import patch


def test_napari_available_is_bool():
    """NAPARI_AVAILABLE should always be a bool."""
    from percell4.viewer import NAPARI_AVAILABLE

    assert isinstance(NAPARI_AVAILABLE, bool)


def test_launch_viewer_raises_when_napari_unavailable():
    """launch_viewer should raise ImportError when napari is not installed."""
    with patch("percell4.viewer.NAPARI_AVAILABLE", False):
        from percell4.viewer import launch_viewer

        try:
            launch_viewer(None)  # type: ignore[arg-type]
            assert False, "Expected ImportError"
        except ImportError as e:
            assert "napari" in str(e).lower()


def test_launch_viewer_signature():
    """launch_viewer should accept store and optional fov_id."""
    import inspect

    from percell4.viewer import launch_viewer

    sig = inspect.signature(launch_viewer)
    params = list(sig.parameters.keys())
    assert "store" in params
    assert "fov_id" in params
