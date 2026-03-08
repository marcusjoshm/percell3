---
status: complete
priority: p1
issue_id: "090"
tags: [code-review, correctness, core, validation-asymmetry]
dependencies: []
---

# `read_labels` and `read_mask` Bypass FOV Validation

## Problem Statement

In `ExperimentStore`, `write_labels` and `write_mask` call `self._resolve_fov()` which validates the FOV exists in the database and extracts the correct `bio_rep` name from the DB record. However, `read_labels` and `read_mask` call `self._resolve_bio_rep()` directly and construct the zarr path from the raw user-provided `fov` and `condition` strings without verifying they exist. This means:

1. If someone passes an incorrect FOV name, reads get a cryptic zarr KeyError instead of `FovNotFoundError`
2. The write path gets the bio_rep name from the database; the read path trusts the caller — behavioral asymmetry

## Findings

- **Found by:** kieran-python-reviewer, code-simplicity-reviewer
- **Evidence:**
  - `experiment_store.py:329-338`: `read_labels` uses `_resolve_bio_rep` directly
  - `experiment_store.py:489-499`: `read_mask` uses `_resolve_bio_rep` directly
  - `experiment_store.py:309-327`: `write_labels` uses `_resolve_fov` (validates FOV)
  - `experiment_store.py:477-487`: `write_mask` uses `_resolve_fov` (validates FOV)

## Proposed Solutions

### Solution A: Use _resolve_fov for reads too (Recommended)
- Change `read_labels` and `read_mask` to call `self._resolve_fov(fov, condition, bio_rep, timepoint)` just like the write methods
- Extract the bio_rep name from the returned `FovInfo` object
- **Pros:** Consistent validation, proper error messages, bio_rep comes from DB
- **Cons:** One extra DB query per read (negligible vs zarr I/O)
- **Effort:** Small
- **Risk:** Low

## Recommended Action

Solution A

## Technical Details

**Affected files:**
- `src/percell3/core/experiment_store.py` (read_labels ~line 329, read_mask ~line 489)

## Acceptance Criteria

- [ ] `read_labels` calls `_resolve_fov` instead of `_resolve_bio_rep`
- [ ] `read_mask` calls `_resolve_fov` instead of `_resolve_bio_rep`
- [ ] Invalid FOV name raises `FovNotFoundError`, not zarr KeyError
- [ ] Tests verify read path validates FOV existence

## Work Log

- 2026-02-17: Identified during code review of feat/data-model-bio-rep-fov branch

## Resources

- PR branch: feat/data-model-bio-rep-fov
