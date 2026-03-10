"""Plugin ABCs and supporting dataclasses for the PerCell 4 plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from percell4.core.experiment_store import ExperimentStore


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginResult:
    """Summary of a plugin execution.

    Attributes:
        fovs_processed: Number of FOVs processed.
        rois_processed: Number of ROIs (cells/particles) processed.
        measurements_added: Number of measurement records written.
        derived_fovs_created: Number of derived FOVs created.
        errors: Non-fatal error messages collected during execution.
    """

    fovs_processed: int = 0
    rois_processed: int = 0
    measurements_added: int = 0
    derived_fovs_created: int = 0
    errors: list[str] = field(default_factory=list)


class AnalysisPlugin(ABC):
    """Base class for all PerCell 4 analysis plugins.

    Plugins receive an ExperimentStore and parameters, perform analysis,
    and write results back as measurements or derived FOVs.
    """

    name: str
    description: str

    @abstractmethod
    def run(
        self,
        store: ExperimentStore,
        fov_ids: list[bytes],
        roi_ids: list[bytes] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        **kwargs: Any,
    ) -> PluginResult:
        """Execute the plugin analysis.

        Args:
            store: ExperimentStore to read from and write to.
            fov_ids: FOVs to process.
            roi_ids: Optional subset of ROI IDs to restrict analysis to.
            on_progress: Optional callback(current, total, message).
            **kwargs: Plugin-specific parameters.

        Returns:
            PluginResult summarizing the execution.
        """
        ...


class VisualizationPlugin(ABC):
    """Base class for plugins that launch interactive viewers (no data writes).

    Unlike AnalysisPlugin, visualization plugins read data and open a viewer
    rather than writing measurements back to the store.
    """

    name: str
    description: str

    @abstractmethod
    def launch(
        self,
        store: ExperimentStore,
        fov_id: bytes,
        **kwargs: Any,
    ) -> None:
        """Open the interactive visualization. Blocks until viewer is closed.

        Args:
            store: ExperimentStore to read from.
            fov_id: FOV database ID (16-byte UUID) to visualize.
            **kwargs: Plugin-specific parameters.
        """
        ...
