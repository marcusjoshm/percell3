"""Plugin ABCs and supporting dataclasses for the PerCell 3 plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from percell3.core import ExperimentStore


class InputKind(str, Enum):
    """Kind of run input a plugin requires."""

    SEGMENTATION = "segmentation"
    THRESHOLD = "threshold"


@dataclass(frozen=True)
class PluginInputRequirement:
    """Declares a run input that a plugin needs.

    Attributes:
        kind: Whether this is a segmentation or threshold run.
        channel: Required channel name, or None for any channel.
    """

    kind: InputKind
    channel: str | None = None


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

    def required_inputs(self) -> list[PluginInputRequirement]:
        """Declare what run inputs this plugin needs.

        Override in subclasses to specify segmentation and/or threshold
        run requirements. The CLI/GUI will resolve matching runs from
        the active measurement config.

        Returns:
            List of input requirements (empty = no run inputs needed).
        """
        return []

    def get_parameter_schema(self) -> dict[str, Any]:
        """Return JSON Schema for plugin parameters.

        Used by CLI/GUI to generate parameter forms.
        Override in subclasses to define plugin-specific parameters.
        """
        return {}


class VisualizationPlugin(ABC):
    """Base class for plugins that launch interactive viewers (no data writes).

    Unlike AnalysisPlugin, visualization plugins read data and open a viewer
    rather than writing measurements back to the store.
    """

    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""

    @abstractmethod
    def validate(self, store: ExperimentStore) -> list[str]:
        """Check if the plugin can launch on this experiment.

        Args:
            store: The experiment to validate against.

        Returns:
            List of validation error messages (empty = OK to launch).
        """

    @abstractmethod
    def launch(
        self,
        store: ExperimentStore,
        fov_id: int,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Open the interactive visualization. Blocks until viewer is closed.

        Args:
            store: ExperimentStore to read from.
            fov_id: FOV database ID to visualize.
            parameters: Plugin-specific parameters.
        """

    def get_parameter_schema(self) -> dict[str, Any]:
        """Return JSON Schema for plugin parameters."""
        return {}
