"""AnalysisPlugin ABC and supporting dataclasses for the PerCell 3 plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


@dataclass(frozen=True)
class PluginInfo:
    """Metadata describing an analysis plugin.

    Attributes:
        name: Machine-readable plugin identifier (e.g., "local_bg_subtraction").
        version: Semantic version string.
        description: Human-readable one-line description.
        author: Plugin author or team name.
        required_channels: Channel names the plugin needs, or None for any.
    """

    name: str
    version: str
    description: str
    author: str = ""
    required_channels: list[str] | None = None


@dataclass(frozen=True)
class PluginResult:
    """Summary of a plugin execution.

    Attributes:
        measurements_written: Number of measurement records written.
        cells_processed: Number of cells processed.
        custom_outputs: Map of output name to description (e.g., CSV path).
        warnings: Non-fatal warnings collected during execution.
    """

    measurements_written: int
    cells_processed: int
    custom_outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class AnalysisPlugin(ABC):
    """Base class for all PerCell 3 analysis plugins.

    Plugins receive an ExperimentStore and parameters, perform analysis,
    and write results back as measurements or custom outputs.
    """

    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""

    @abstractmethod
    def validate(self, store: ExperimentStore) -> list[str]:
        """Check if the plugin can run on this experiment.

        Args:
            store: The experiment to validate against.

        Returns:
            List of validation error messages (empty = OK to run).
        """

    @abstractmethod
    def run(
        self,
        store: ExperimentStore,
        cell_ids: list[int] | None = None,
        parameters: dict[str, Any] | None = None,
        progress_callback: Any | None = None,
    ) -> PluginResult:
        """Execute the plugin analysis.

        Args:
            store: ExperimentStore to read from and write to.
            cell_ids: Subset of cells to analyze (None = all cells).
            parameters: Plugin-specific parameters.
            progress_callback: Optional callback(current, total, message).

        Returns:
            PluginResult summarizing the execution.
        """

    def get_parameter_schema(self) -> dict[str, Any]:
        """Return JSON Schema for plugin parameters.

        Used by CLI/GUI to generate parameter forms.
        Override in subclasses to define plugin-specific parameters.
        """
        return {}
