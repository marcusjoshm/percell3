"""UUID-based type aliases and helpers for the PerCell 4 database layer.

All entity primary keys are UUID stored as BLOB(16) in SQLite.
These type aliases and helpers provide a consistent interface for
creating, converting, and validating UUIDs throughout the codebase.
"""

from __future__ import annotations

import uuid
from typing import TypeAlias

# ---------------------------------------------------------------------------
# Entity ID type aliases (PEP 613)
# ---------------------------------------------------------------------------
# All are structurally `bytes` (16-byte UUID), but the alias names document
# which entity the ID belongs to.  Never reuse a UUID variable for a
# different entity.

FovId: TypeAlias = bytes
RoiId: TypeAlias = bytes
SegmentationSetId: TypeAlias = bytes
CellIdentityId: TypeAlias = bytes
ExperimentId: TypeAlias = bytes
ConditionId: TypeAlias = bytes
ChannelId: TypeAlias = bytes
BioRepId: TypeAlias = bytes
TimepointId: TypeAlias = bytes
ThresholdMaskId: TypeAlias = bytes
PipelineRunId: TypeAlias = bytes
IntensityGroupId: TypeAlias = bytes
RoiTypeDefinitionId: TypeAlias = bytes

# ---------------------------------------------------------------------------
# UUID helpers — use these everywhere, never write ad hoc UUID logic
# ---------------------------------------------------------------------------


def new_uuid() -> bytes:
    """Generate a new random UUID as 16 raw bytes."""
    return uuid.uuid4().bytes


def uuid_to_str(b: bytes) -> str:
    """Convert 16-byte UUID to its canonical string representation.

    Args:
        b: A 16-byte UUID value.

    Returns:
        Canonical UUID string (e.g., '550e8400-e29b-41d4-a716-446655440000').

    Raises:
        ValueError: If *b* is not exactly 16 bytes.
    """
    validate_uuid_bytes(b, "uuid_to_str input")
    return str(uuid.UUID(bytes=b))


def str_to_uuid(s: str) -> bytes:
    """Convert a UUID string to 16 raw bytes.

    Args:
        s: A UUID string in any format accepted by :class:`uuid.UUID`.

    Returns:
        16-byte UUID value.
    """
    return uuid.UUID(s).bytes


def validate_uuid_bytes(b: bytes, name: str = "value") -> None:
    """Validate that *b* is a well-formed 16-byte UUID.

    Args:
        b: The value to validate.
        name: Human-readable label for error messages.

    Raises:
        ValueError: If *b* is not ``bytes`` or not exactly 16 bytes long.
    """
    if not isinstance(b, bytes):
        raise ValueError(
            f"{name}: expected bytes, got {type(b).__name__}"
        )
    if len(b) != 16:
        raise ValueError(
            f"{name}: expected 16 bytes, got {len(b)}"
        )
