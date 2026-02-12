# Module 5: Plugins — Specification

## Overview

The plugin system allows extensible analysis without modifying core code.
Plugins receive an ExperimentStore and a set of cell IDs, perform custom
analysis, and write results back as measurements or Zarr layers.

## AnalysisPlugin ABC

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from percell3.core import ExperimentStore

@dataclass
class PluginInfo:
    """Plugin metadata."""
    name: str
    version: str
    description: str
    author: str = ""
    required_channels: list[str] = None  # None = works with any channels

class AnalysisPlugin(ABC):
    """Base class for all analysis plugins."""

    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""

    @abstractmethod
    def validate(self, store: ExperimentStore) -> list[str]:
        """Check if plugin can run on this experiment.
        Returns list of validation errors (empty = OK)."""

    @abstractmethod
    def run(self, store: ExperimentStore,
            cell_ids: list[int] = None,
            parameters: dict = None,
            progress_callback=None) -> PluginResult:
        """Execute the plugin analysis.

        Args:
            store: ExperimentStore to read from and write to.
            cell_ids: Subset of cells to analyze (None = all cells).
            parameters: Plugin-specific parameters.
            progress_callback: Optional callback(current, total, message).

        Returns:
            PluginResult with summary.
        """

    def get_parameter_schema(self) -> dict:
        """Return JSON Schema for plugin parameters.
        Used by CLI/GUI to generate parameter forms."""
        return {}

@dataclass
class PluginResult:
    """Summary of a plugin execution."""
    measurements_written: int
    cells_processed: int
    custom_outputs: dict[str, str]  # name -> description of custom outputs
    warnings: list[str]
```

## Plugin Registry

```python
class PluginRegistry:
    """Discovers and manages analysis plugins."""

    def __init__(self):
        self._plugins: dict[str, type[AnalysisPlugin]] = {}

    def discover(self) -> None:
        """Discover plugins from:
        1. Built-in plugins (percell3.plugins.builtin)
        2. Entry points (group: 'percell3.plugins')
        3. Plugin directories (configurable)
        """

    def list_plugins(self) -> list[PluginInfo]:
        """List all discovered plugins."""

    def get_plugin(self, name: str) -> AnalysisPlugin:
        """Get a plugin instance by name."""

    def run_plugin(self, name: str, store: ExperimentStore,
                   cell_ids: list[int] = None,
                   parameters: dict = None,
                   progress_callback=None) -> PluginResult:
        """Run a plugin with full lifecycle management.

        1. Get plugin instance
        2. Validate against store
        3. Start analysis run in SQLite
        4. Execute plugin.run()
        5. Complete analysis run
        6. Return result
        """
```

## Built-in Plugins

### Intensity Grouping Plugin

Replaces PerCell 2's cell grouping functionality. Groups cells into categories
based on intensity thresholds.

```python
class IntensityGroupingPlugin(AnalysisPlugin):
    """Group cells by intensity level in a channel.

    Parameters:
        channel: str - Channel to group by
        method: str - "quantile" or "manual"
        n_groups: int - Number of groups (for quantile method)
        thresholds: list[float] - Manual threshold values
        group_names: list[str] - Names for each group (e.g., ["low", "medium", "high"])

    Outputs:
        - Measurement: '{channel}_group' with integer group ID per cell
        - Tags: Cells tagged with group names (e.g., 'GFP_high', 'GFP_low')
    """
```

### Colocalization Plugin

Computes per-cell colocalization metrics between two channels.

```python
class ColocalizationPlugin(AnalysisPlugin):
    """Compute colocalization metrics between two channels.

    Parameters:
        channel_a: str - First channel
        channel_b: str - Second channel

    Outputs (per cell):
        - 'pearson_r': Pearson correlation coefficient
        - 'manders_m1': Manders overlap coefficient (A in B)
        - 'manders_m2': Manders overlap coefficient (B in A)
        - 'overlap_fraction': Fraction of cell with both channels above threshold
    """
```

### FLIM-Phasor Plugin (Scaffold)

Placeholder for FLIM phasor analysis integration. Defines the interface
that will wrap existing FLIM-Phasor Python code.

```python
class FlimPhasorPlugin(AnalysisPlugin):
    """FLIM Phasor analysis scaffold.

    Parameters:
        channel: str - FLIM channel
        frequency_mhz: float - Laser repetition frequency
        harmonic: int - Harmonic number (default: 1)

    Outputs (per cell):
        - 'phasor_g': G coordinate (real component)
        - 'phasor_s': S coordinate (imaginary component)
        - 'lifetime_ns': Estimated fluorescence lifetime

    Custom Zarr output:
        - Phasor G/S images (per pixel) in custom Zarr layer
    """
```

## Plugin Discovery via entry_points

External plugins register via pyproject.toml:

```toml
[project.entry-points."percell3.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

Discovery code:

```python
from importlib.metadata import entry_points

def _discover_entry_points(self):
    eps = entry_points(group="percell3.plugins")
    for ep in eps:
        plugin_cls = ep.load()
        if issubclass(plugin_cls, AnalysisPlugin):
            self._plugins[ep.name] = plugin_cls
```

## Plugin Custom Zarr Layers

Plugins can write custom output images to the ExperimentStore:

```python
# Inside a plugin's run() method:
store.write_custom_layer("phasor_g", region, condition, g_image)
store.write_custom_layer("phasor_s", region, condition, s_image)
```

This writes to a `custom.zarr/` directory following the same
condition/region hierarchy as other Zarr stores.
