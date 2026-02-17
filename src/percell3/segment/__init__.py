"""PerCell 3 Segment — Segmentation engine and Cellpose adapter."""

from percell3.segment.base_segmenter import (
    BaseSegmenter,
    SegmentationParams,
    SegmentationResult,
)
from percell3.segment._engine import SegmentationEngine
from percell3.segment.label_processor import LabelProcessor, extract_cells
from percell3.segment.roi_import import RoiImporter, store_labels_and_cells

__all__ = [
    "BaseSegmenter",
    "CellposeAdapter",
    "extract_cells",
    "KNOWN_CELLPOSE_MODELS",
    "LabelProcessor",
    "launch_viewer",
    "NAPARI_AVAILABLE",
    "RoiImporter",
    "save_edited_labels",
    "SegmentationEngine",
    "SegmentationParams",
    "SegmentationResult",
    "store_labels_and_cells",
]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy imports for cellpose-dependent symbols to avoid slow startup."""
    if name == "CellposeAdapter":
        from percell3.segment.cellpose_adapter import CellposeAdapter

        return CellposeAdapter
    if name == "KNOWN_CELLPOSE_MODELS":
        from percell3.segment.cellpose_adapter import KNOWN_CELLPOSE_MODELS

        return KNOWN_CELLPOSE_MODELS
    if name in ("launch_viewer", "NAPARI_AVAILABLE", "save_edited_labels"):
        from percell3.segment.viewer import (
            NAPARI_AVAILABLE,
            launch_viewer,
            save_edited_labels,
        )

        return {
            "launch_viewer": launch_viewer,
            "NAPARI_AVAILABLE": NAPARI_AVAILABLE,
            "save_edited_labels": save_edited_labels,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
