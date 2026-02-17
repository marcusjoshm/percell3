---
status: pending
priority: p3
issue_id: "087"
tags: [plan-review, planning-gap, completeness]
dependencies: []
---

# SegmentationResult Field Renames

## Problem Statement

Phase 1.5 says "Rename region parameters -> fov in engine, viewer, and all related files" but doesn't enumerate the SegmentationResult dataclass fields that need renaming.

## Findings

Python reviewer: "SegmentationResult.regions_processed -> fovs_processed, region_stats -> fov_stats. The plan's Phase 1.5 is too terse — enumerate all public API field names."

## Proposed Solutions

### A) Add explicit rename list for SegmentationResult fields to Phase 1.5

- **Effort:** Trivial
- **Risk:** None

Enumerate every public field and method on SegmentationResult (and any related dataclasses) that contains "region" and specify its "fov" replacement. This prevents implementers from missing renames or being inconsistent.

## Technical Details

Known fields that need renaming (based on current codebase):

- `SegmentationResult.regions_processed` -> `fovs_processed`
- `SegmentationResult.region_stats` -> `fov_stats`

Additional renames may exist in:

- Engine method signatures (e.g., parameters named `region`)
- Viewer/display code that references region names
- Any helper functions that accept or return region-related data

The plan should enumerate all of these explicitly so that Phase 1.5 is a complete checklist, not a vague directive.

## Acceptance Criteria

- [ ] Plan Phase 1.5 enumerates all SegmentationResult field renames

## Work Log

_No work performed yet._

## Resources

- Plan review: Python reviewer feedback
- Current dataclass: `src/percell3/segment/engine.py`
