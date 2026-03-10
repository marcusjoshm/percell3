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
