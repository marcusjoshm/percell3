"""3D Surface Plot Visualization Plugin.

Renders a microscopy image as an interactive 3D heightmap in napari.
One channel defines Z-axis elevation, a second channel drives a colormap
painted onto the terrain surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from percell3.plugins.base import PluginInfo, VisualizationPlugin

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


class SurfacePlot3DPlugin(VisualizationPlugin):
    """3D surface plot with dual-channel height + color overlay."""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="surface_plot_3d",
            version="1.0.0",
            description="3D surface plot with dual-channel height + color overlay",
            author="PerCell Team",
        )

    def validate(self, store: ExperimentStore) -> list[str]:
        """Check experiment has at least 2 channels and FOVs."""
        errors: list[str] = []

        channels = store.get_channels()
        if len(channels) < 2:
            errors.append("At least 2 channels required (height + color).")

        fovs = store.get_fovs()
        if not fovs:
            errors.append("No FOVs in experiment.")

        return errors

    def launch(
        self,
        store: ExperimentStore,
        fov_id: int,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Open the 3D surface plot viewer. Blocks until closed."""
        import napari

        from percell3.segment.viewer.surface_plot_widget import SurfacePlotWidget

        channels = store.get_channels()
        channel_names = [ch.name for ch in channels]
        fov_info = store.get_fov_by_id(fov_id)

        viewer = napari.Viewer(
            title=f"PerCell 3 \u2014 Surface Plot \u2014 {fov_info.display_name}"
        )

        # Load all channel images as 2D layers for ROI drawing context
        for ch in channels:
            data = store.read_image(fov_id, ch.name)
            viewer.add_image(data, name=ch.name, blending="additive")

        # Add ROI shapes layer for rectangle drawing
        roi_layer = viewer.add_shapes(
            name="ROI",
            edge_color="yellow",
            face_color="transparent",
        )
        roi_layer.mode = "add_rectangle"

        # Add dock widget
        widget = SurfacePlotWidget(viewer, store, fov_id, channel_names)
        viewer.window.add_dock_widget(
            widget.widget, name="3D Surface Plot", area="right",
        )

        napari.run()
