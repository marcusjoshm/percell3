"""PerCell 3 Plugins — Plugin system and built-in analysis/visualization plugins."""

from percell3.plugins.base import (
    AnalysisPlugin,
    PluginInfo,
    PluginResult,
    VisualizationPlugin,
)
from percell3.plugins.registry import PluginError, PluginRegistry

__all__ = [
    "AnalysisPlugin",
    "PluginError",
    "PluginInfo",
    "PluginRegistry",
    "PluginResult",
    "VisualizationPlugin",
]
