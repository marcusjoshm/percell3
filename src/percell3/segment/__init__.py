"""PerCell 3 Segment — Segmentation engine and Cellpose adapter."""

from percell3.segment.base_segmenter import (
    BaseSegmenter,
    SegmentationParams,
    SegmentationResult,
)

__all__ = [
    "BaseSegmenter",
    "CellposeAdapter",
    "RoiImporter",
    "SegmentationEngine",
    "SegmentationParams",
    "SegmentationResult",
]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy imports to avoid heavy dependencies (cellpose) at module level."""
    if name == "SegmentationEngine":
        from percell3.segment._engine import SegmentationEngine

        return SegmentationEngine
    if name == "CellposeAdapter":
        from percell3.segment.cellpose_adapter import CellposeAdapter

        return CellposeAdapter
    if name == "RoiImporter":
        from percell3.segment.roi_import import RoiImporter

        return RoiImporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
