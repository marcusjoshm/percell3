"""Built-in workflow steps and preset workflow factories.

All built-in steps use lazy imports so they can be imported even before
Modules 2-5 (io, segment, measure, plugins) are implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from percell3.workflow.dag import WorkflowDAG
from percell3.workflow.step import (
    StepInput,
    StepOutput,
    StepParameter,
    StepRegistry,
    StepResult,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Built-in steps
# ---------------------------------------------------------------------------


@StepRegistry.register
class ImportLif(WorkflowStep):
    """Import images from a Leica LIF file."""

    @property
    def name(self) -> str:
        return "import_lif"

    @property
    def inputs(self) -> list[StepInput]:
        return []

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("images"), StepOutput("channels"), StepOutput("fovs")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("path", "str", description="Path to .lif file"),
            StepParameter("condition", "str", default="", description="Condition label"),
            StepParameter("bio_rep", "str", default="N1", description="Biological replicate"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.io.lif_reader import LifReader  # type: ignore[import-not-found]

        reader = LifReader()
        reader.read(store, Path(params["path"]), condition=params.get("condition", ""))
        return StepResult(
            status="completed",
            outputs_produced=["images", "channels", "fovs"],
        )


@StepRegistry.register
class ImportTiff(WorkflowStep):
    """Import images from a directory of TIFF files."""

    @property
    def name(self) -> str:
        return "import_tiff"

    @property
    def inputs(self) -> list[StepInput]:
        return []

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("images"), StepOutput("channels"), StepOutput("fovs")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("path", "str", description="Path to TIFF directory"),
            StepParameter("condition", "str", default="", description="Condition label"),
            StepParameter("bio_rep", "str", default="N1", description="Biological replicate"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.io.tiff_reader import TiffDirectoryReader  # type: ignore[import-not-found]

        reader = TiffDirectoryReader()
        reader.read(store, Path(params["path"]), condition=params.get("condition", ""))
        return StepResult(
            status="completed",
            outputs_produced=["images", "channels", "fovs"],
        )


@StepRegistry.register
class Segment(WorkflowStep):
    """Run segmentation on images."""

    @property
    def name(self) -> str:
        return "segment"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("images"), StepInput("channels")]

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("labels"), StepOutput("cells")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("channel", "str", default="DAPI", description="Channel to segment"),
            StepParameter(
                "model", "choice", default="cpsam",
                choices=["cpsam", "cyto3", "nuclei", "cyto2"],
                description="Cellpose model",
            ),
            StepParameter("diameter", "int", default=60, description="Expected cell diameter"),
            StepParameter("bio_rep", "str", default="N1", description="Biological replicate"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.segment import SegmentationEngine  # type: ignore[import-not-found]

        engine = SegmentationEngine()
        engine.run(store, **params)
        return StepResult(
            status="completed",
            outputs_produced=["labels", "cells"],
        )


@StepRegistry.register
class Measure(WorkflowStep):
    """Measure intensity features for segmented cells."""

    @property
    def name(self) -> str:
        return "measure"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("images"), StepInput("labels"), StepInput("cells")]

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("measurements")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("channels", "str", description="Channels to measure (comma-separated)"),
            StepParameter(
                "metrics", "str",
                default="mean_intensity,max_intensity,integrated_intensity",
                description="Metrics to compute",
            ),
            StepParameter("bio_rep", "str", default="N1", description="Biological replicate"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.measure import MeasurementEngine  # type: ignore[import-not-found]

        engine = MeasurementEngine()
        engine.run(store, **params)
        return StepResult(
            status="completed",
            outputs_produced=["measurements"],
        )


@StepRegistry.register
class Threshold(WorkflowStep):
    """Apply intensity thresholding to create binary masks."""

    @property
    def name(self) -> str:
        return "threshold"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("images")]

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("masks")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("channel", "str", description="Channel to threshold"),
            StepParameter("method", "choice", default="otsu",
                          choices=["otsu", "manual"], description="Thresholding method"),
            StepParameter("value", "float", default=None, description="Manual threshold value"),
            StepParameter("bio_rep", "str", default="N1", description="Biological replicate"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.measure import ThresholdEngine  # type: ignore[import-not-found]

        engine = ThresholdEngine()
        engine.run(store, **params)
        return StepResult(
            status="completed",
            outputs_produced=["masks"],
        )


@StepRegistry.register
class Classify(WorkflowStep):
    """Classify cells as positive/negative based on masks."""

    @property
    def name(self) -> str:
        return "classify"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("labels"), StepInput("masks")]

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("classifications")]

    @property
    def parameters(self) -> list[StepParameter]:
        return []

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.measure import classify_cells  # type: ignore[import-not-found]

        classify_cells(store, **params)
        return StepResult(
            status="completed",
            outputs_produced=["classifications"],
        )


@StepRegistry.register
class RunPlugin(WorkflowStep):
    """Run a registered plugin."""

    @property
    def name(self) -> str:
        return "run_plugin"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("measurements", required=False)]

    @property
    def outputs(self) -> list[StepOutput]:
        return [StepOutput("measurements")]

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("plugin_name", "str", description="Name of the plugin to run"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        from percell3.plugins import PluginManager  # type: ignore[import-not-found]

        manager = PluginManager()
        plugin = manager.get(params["plugin_name"])
        plugin.run(store, params)
        return StepResult(
            status="completed",
            outputs_produced=["measurements"],
        )


@StepRegistry.register
class ExportCsv(WorkflowStep):
    """Export measurements to a CSV file."""

    @property
    def name(self) -> str:
        return "export_csv"

    @property
    def inputs(self) -> list[StepInput]:
        return [StepInput("measurements")]

    @property
    def outputs(self) -> list[StepOutput]:
        return []

    @property
    def parameters(self) -> list[StepParameter]:
        return [
            StepParameter("path", "str", default="results.csv",
                          description="Output CSV path"),
        ]

    def execute(
        self,
        store: Any,
        params: dict[str, Any],
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> StepResult:
        store.export_csv(Path(params.get("path", "results.csv")))
        return StepResult(status="completed")


# ---------------------------------------------------------------------------
# Preset workflow factories
# ---------------------------------------------------------------------------


def complete_analysis_workflow(
    source_path: Path,
    source_format: str = "lif",
    channel_seg: str = "DAPI",
    channels_measure: list[str] | None = None,
) -> WorkflowDAG:
    """Standard workflow: import -> segment -> measure -> export.

    Args:
        source_path: Path to the source file or directory.
        source_format: "lif" or "tiff".
        channel_seg: Channel to segment on.
        channels_measure: Channels to measure. Defaults to all.
    """
    dag = WorkflowDAG()

    if source_format == "lif":
        dag.add_step(ImportLif(), {"path": str(source_path)})
    else:
        dag.add_step(ImportTiff(), {"path": str(source_path)})

    dag.add_step(Segment(), {"channel": channel_seg})
    dag.add_step(
        Measure(),
        {"channels": ",".join(channels_measure) if channels_measure else ""},
    )
    dag.add_step(ExportCsv())
    dag.auto_connect()
    return dag


def measure_only_workflow(channels: list[str]) -> WorkflowDAG:
    """For re-measuring with different channels (assumes labels exist).

    Args:
        channels: List of channel names to measure.
    """
    dag = WorkflowDAG()
    dag.add_step(Measure(), {"channels": ",".join(channels)})
    dag.add_step(ExportCsv())
    dag.auto_connect()
    return dag
