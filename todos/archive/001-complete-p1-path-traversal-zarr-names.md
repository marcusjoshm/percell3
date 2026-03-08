---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, security]
dependencies: []
---
# Path Traversal via Unvalidated Names

## Problem Statement

The zarr I/O layer builds storage paths by interpolating user-supplied names
(condition, region, channel, timepoint) directly into f-strings. Because no
validation is applied anywhere in the call chain, a malicious or malformed name
such as `"../../etc"` can escape the zarr directory root and read or overwrite
arbitrary locations on the filesystem.

## Findings

- `zarr_io.py` path functions (`image_group_path`, `label_group_path`,
  `mask_group_path`) at lines 36-67 construct paths via f-string interpolation.
- Names flow in from `ExperimentStore.add_condition`, `add_region`,
  `add_channel`, and `add_timepoint` (experiment_store.py:135-158) with no
  sanitization or validation.
- No intermediate layer checks for path-separator characters, relative-path
  components (`..`), or other dangerous sequences.
- This affects every code path that stores or retrieves image data.

## Proposed Solutions

### Option 1 -- Centralized `validate_name()` guard (recommended)

Add a `validate_name(name: str) -> str` function to a shared validation module
(e.g., `core/validation.py`) that:

1. Checks `name` against the regex `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`.
2. Raises `ValueError` with a clear message on failure.
3. Returns the name unchanged on success (allows inline use).

Call `validate_name()` at the entry points in `ExperimentStore`:
- `add_condition(name)`
- `add_region(name)`
- `add_channel(name)`
- `add_timepoint(name)`

This ensures that by the time a name reaches the zarr path functions, it is
already known-safe.

### Option 2 -- Path-level assertion in zarr_io

Add a secondary defence inside each path-building function that resolves the
constructed path and asserts it is still beneath the zarr root:

```python
resolved = root / constructed
assert resolved.resolve().is_relative_to(root.resolve())
```

This is a good belt-and-suspenders measure but should not replace input
validation because it only catches the symptom, not the root cause.

## Technical Details

- **Files affected:** `zarr_io.py:36-67`, `experiment_store.py:135-158`
- **Regex rationale:** Must start with an alphanumeric character; body may
  include alphanumerics, dots, hyphens, and underscores; max length 255 to
  stay within filesystem limits on all major OSes.
- **Performance impact:** Negligible -- regex check on short strings at
  infrequent entry points.

## Acceptance Criteria

- [ ] `validate_name()` exists with full regex enforcement.
- [ ] All four `ExperimentStore.add_*` methods call `validate_name()`.
- [ ] Unit tests confirm rejection of `../`, empty string, names starting with
      `.` or `-`, and names exceeding 255 characters.
- [ ] Unit tests confirm acceptance of typical names like `"DAPI"`, `"t0"`,
      `"control_group.1"`.
- [ ] Option 2 path-level assertion added as defence-in-depth in zarr_io
      path functions.

## Work Log

### 2026-02-12 - Code Review Discovery

Identified during manual review of `percell3.core`. The zarr path construction
functions accept arbitrary strings with no validation, creating a path-traversal
vulnerability. Classified as P1/security because it can lead to arbitrary
filesystem access.
