"""Exception hierarchy for the PerCell 4 core module."""

from __future__ import annotations


class ExperimentError(Exception):
    """Base exception for all experiment-related errors."""


class MergeConflictError(ExperimentError):
    """Raised when a database merge encounters conflicting data."""

    def __init__(self, message: str = "Merge conflict") -> None:
        super().__init__(message)


class InvalidStatusTransition(ExperimentError):
    """Raised when an FOV status transition violates the state machine."""

    def __init__(self, message: str = "Invalid status transition") -> None:
        super().__init__(message)


class PathTraversalError(ExperimentError):
    """Raised when a path attempts to escape the experiment directory."""

    def __init__(self, message: str = "Path traversal detected") -> None:
        super().__init__(message)


class RoiNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent ROI."""

    def __init__(self, roi_id: bytes | None = None) -> None:
        if roi_id is not None:
            msg = f"ROI not found: {roi_id.hex()}"
        else:
            msg = "ROI not found"
        super().__init__(msg)
        self.roi_id = roi_id


class LineageError(ExperimentError):
    """Raised when a FOV lineage operation fails (e.g., depth exceeded, cycle detected)."""

    def __init__(self, message: str = "Lineage error") -> None:
        super().__init__(message)
