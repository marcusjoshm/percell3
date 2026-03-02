"""Exception classes for the PerCell 3 core module."""


class ExperimentError(Exception):
    """Base exception for all experiment-related errors."""


class ExperimentNotFoundError(ExperimentError):
    """Raised when opening a nonexistent .percell directory."""

    def __init__(self, path: str | None = None) -> None:
        msg = f"Experiment not found: {path}" if path else "Experiment not found"
        super().__init__(msg)
        self.path = path


class ChannelNotFoundError(ExperimentError):
    """Raised when referencing an undefined channel."""

    def __init__(self, name: str | None = None) -> None:
        msg = f"Channel not found: {name}" if name else "Channel not found"
        super().__init__(msg)
        self.name = name


class ConditionNotFoundError(ExperimentError):
    """Raised when referencing an undefined condition."""

    def __init__(self, name: str | None = None) -> None:
        msg = f"Condition not found: {name}" if name else "Condition not found"
        super().__init__(msg)
        self.name = name


class BioRepNotFoundError(ExperimentError):
    """Raised when referencing an undefined biological replicate."""

    def __init__(self, name: str | None = None) -> None:
        msg = f"Biological replicate not found: {name}" if name else "Biological replicate not found"
        super().__init__(msg)
        self.name = name


class FovNotFoundError(ExperimentError):
    """Raised when referencing an undefined FOV."""

    def __init__(self, name: str | None = None) -> None:
        msg = f"FOV not found: {name}" if name else "FOV not found"
        super().__init__(msg)
        self.name = name


class SchemaVersionError(ExperimentError):
    """Raised when opening a database with an incompatible schema version."""

    def __init__(self, stored: str, expected: str) -> None:
        msg = (
            f"Schema version mismatch: database has version '{stored}', "
            f"expected '{expected}'. Re-import your data with the current "
            f"version of PerCell 3."
        )
        super().__init__(msg)
        self.stored = stored
        self.expected = expected


class DuplicateError(ExperimentError):
    """Raised when adding a duplicate entity (channel, condition, etc.)."""

    def __init__(self, entity: str | None = None, name: str | None = None) -> None:
        if entity and name:
            msg = f"Duplicate {entity}: {name}"
        elif entity:
            msg = f"Duplicate {entity}"
        else:
            msg = "Duplicate entry"
        super().__init__(msg)
        self.entity = entity
        self.name = name


class SegmentationNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent segmentation."""

    def __init__(self, segmentation_id: int | None = None) -> None:
        msg = f"Segmentation not found: {segmentation_id}" if segmentation_id is not None else "Segmentation not found"
        super().__init__(msg)
        self.segmentation_id = segmentation_id


class ThresholdNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent threshold."""

    def __init__(self, threshold_id: int | None = None) -> None:
        msg = f"Threshold not found: {threshold_id}" if threshold_id is not None else "Threshold not found"
        super().__init__(msg)
        self.threshold_id = threshold_id


class RunNameError(ExperimentError):
    """Raised when an entity name is invalid or conflicts with an existing name."""

    def __init__(self, name: str, reason: str = "invalid") -> None:
        msg = f"Invalid name {name!r}: {reason}"
        super().__init__(msg)
        self.name = name
        self.reason = reason
