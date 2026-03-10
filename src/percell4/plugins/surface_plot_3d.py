"""3D Surface Plot Visualization Plugin.

Renders a microscopy image as an interactive 3D heightmap in napari.
One channel defines Z-axis elevation, a second channel drives a colormap
painted onto the terrain surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from percell4.plugins.base import VisualizationPlugin

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore


class SurfacePlot3DPlugin(VisualizationPlugin):
    """3D surface plot with dual-channel height + color overlay."""

    name = "surface_plot_3d"
    description = "3D surface plot with dual-channel height + color overlay"

    def launch(
        self,
        store: ExperimentStore,
        fov_id: bytes,
        **kwargs: Any,
    ) -> None:
        """Open the 3D surface plot viewer. Blocks until closed.

        Requires napari to be installed (optional dependency).
        """
        import napari

        from percell4.core.db_types import uuid_to_hex, uuid_to_str

        exp = store.db.get_experiment()
        channels = store.db.get_channels(exp["id"])
        channel_names = [ch["name"] for ch in channels]
        fov = store.db.get_fov(fov_id)
        fov_name = fov["auto_name"] if fov else uuid_to_str(fov_id)
        fov_hex = uuid_to_hex(fov_id)

        viewer = napari.Viewer(
            title=f"PerCell 4 — Surface Plot — {fov_name}"
        )

        # Load all channel images as 2D layers
        for idx, ch in enumerate(channels):
            data = store.layers.read_image_channel_numpy(fov_hex, idx)
            viewer.add_image(data, name=ch["name"], blending="additive")

        # Add ROI shapes layer for rectangle drawing
        roi_layer = viewer.add_shapes(
            name="ROI",
            edge_color="yellow",
            face_color="transparent",
        )
        roi_layer.mode = "add_rectangle"

        napari.run()
