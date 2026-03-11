"""Shared constants for the PerCell 4 core module.

Defines metric names, scope values, FOV status state machine,
batch parameters, and merge ordering used across all modules.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Measurement metric names
# ---------------------------------------------------------------------------

MEAN: str = "mean"
MAX: str = "max"
MIN: str = "min"
INTEGRATED: str = "integrated"
STD: str = "std"
MEDIAN: str = "median"
AREA: str = "area"

# ---------------------------------------------------------------------------
# Measurement scopes
# ---------------------------------------------------------------------------

SCOPE_WHOLE_ROI: str = "whole_roi"
SCOPE_MASK_INSIDE: str = "mask_inside"
SCOPE_MASK_OUTSIDE: str = "mask_outside"

# Display mapping: internal scope name -> user-facing label.
# whole_roi is displayed as "whole_cell" for backward compatibility with
# percell3 exports and user expectations.
SCOPE_DISPLAY: dict[str, str] = {
    SCOPE_WHOLE_ROI: "whole_cell",
    SCOPE_MASK_INSIDE: "mask_inside",
    SCOPE_MASK_OUTSIDE: "mask_outside",
}

# ---------------------------------------------------------------------------
# Batch defaults
# ---------------------------------------------------------------------------

DEFAULT_BATCH_SIZE: int = 500

# ---------------------------------------------------------------------------
# FOV status state machine
# ---------------------------------------------------------------------------


class FovStatus(StrEnum):
    """Valid status values for an FOV record.

    Transitions between statuses are enforced by VALID_TRANSITIONS.
    """

    pending = "pending"
    imported = "imported"
    segmented = "segmented"
    measured = "measured"
    analyzing = "analyzing"
    qc_pending = "qc_pending"
    qc_done = "qc_done"
    stale = "stale"
    error = "error"
    deleting = "deleting"
    deleted = "deleted"


VALID_TRANSITIONS: dict[FovStatus, set[FovStatus]] = {
    FovStatus.pending: {FovStatus.imported, FovStatus.error},
    FovStatus.imported: {FovStatus.segmented, FovStatus.stale, FovStatus.deleting},
    FovStatus.segmented: {
        FovStatus.measured, FovStatus.imported,  # imported: re-processing
        FovStatus.stale, FovStatus.deleting,
    },
    FovStatus.measured: {
        FovStatus.analyzing, FovStatus.segmented, FovStatus.imported,  # re-processing
        FovStatus.stale, FovStatus.deleting,
    },
    FovStatus.analyzing: {FovStatus.qc_pending, FovStatus.stale, FovStatus.deleting},
    FovStatus.qc_pending: {FovStatus.qc_done, FovStatus.stale, FovStatus.deleting},
    FovStatus.qc_done: {FovStatus.stale, FovStatus.deleting},
    FovStatus.stale: {FovStatus.imported, FovStatus.deleting},
    FovStatus.error: {FovStatus.deleting},
    FovStatus.deleting: {FovStatus.deleted},
    FovStatus.deleted: set(),
}

# ---------------------------------------------------------------------------
# Lineage depth guard
# ---------------------------------------------------------------------------

MAX_LINEAGE_DEPTH: int = 50

# ---------------------------------------------------------------------------
# Merge table ordering — topological order for INSERT OR IGNORE merges
# ---------------------------------------------------------------------------

MERGE_TABLE_ORDER: tuple[str, ...] = (
    "experiments",
    "conditions",
    "bio_reps",
    "channels",
    "timepoints",
    "roi_type_definitions",
    "pipeline_runs",
    "fovs",
    "cell_identities",
    "segmentation_sets",
    "threshold_masks",
    "rois",
    "fov_segmentation_assignments",
    "fov_mask_assignments",
    "measurements",
    "intensity_groups",
    "cell_group_assignments",
    "fov_status_log",
    "workflow_configs",
)

ENTITY_TABLES: frozenset[str] = frozenset(MERGE_TABLE_ORDER)
