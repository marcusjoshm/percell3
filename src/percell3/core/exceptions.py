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


class SegmentationRunNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent segmentation run."""

    def __init__(self, run_id: int | None = None) -> None:
        msg = f"Segmentation run not found: {run_id}" if run_id is not None else "Segmentation run not found"
        super().__init__(msg)
        self.run_id = run_id


class ThresholdRunNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent threshold run."""

    def __init__(self, run_id: int | None = None) -> None:
        msg = f"Threshold run not found: {run_id}" if run_id is not None else "Threshold run not found"
        super().__init__(msg)
        self.run_id = run_id


class MeasurementConfigNotFoundError(ExperimentError):
    """Raised when referencing a nonexistent measurement configuration."""

    def __init__(self, config_id: int | None = None) -> None:
        msg = f"Measurement config not found: {config_id}" if config_id is not None else "Measurement config not found"
        super().__init__(msg)
        self.config_id = config_id


class RunNameError(ExperimentError):
    """Raised when a run name is invalid or conflicts with an existing name."""

    def __init__(self, name: str, reason: str = "invalid") -> None:
        msg = f"Invalid run name {name!r}: {reason}"
        super().__init__(msg)
        self.name = name
        self.reason = reason
