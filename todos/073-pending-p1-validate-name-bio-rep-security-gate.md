---
status: pending
priority: p1
issue_id: "073"
tags: [plan-review, security, code-review]
dependencies: []
---

# _validate_name() Security Gate for Bio Rep Names

## Problem Statement

The plan correctly states _validate_name() must be applied to add_bio_rep(), but this is the single most critical security requirement for the restructure. Bio rep names become the FIRST segment in all Zarr filesystem paths ({bio_rep}/{condition}/{fov}/0). A path traversal via bio_rep name (e.g., "../../etc") would escape the zarr store directory.

## Findings

- **Security sentinel**: "If _validate_name() is omitted, this is CRITICAL severity. With it applied, LOW severity." The existing regex `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$` prevents slashes, null bytes, and `..` sequences.
- **Learnings researcher**: Past P1 fix documented in docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md shows this exact pattern was added to fix a prior vulnerability.
- **Security sentinel** also recommends: apply `sanitize_name()` in the CLI import pipeline BEFORE calling `store.add_bio_rep()` (defense in depth, matching the condition pattern).

## Proposed Solutions

### A) Validate and sanitize at both layers

Ensure `_validate_name(name, "bio_rep name")` is the FIRST line of `add_bio_rep()`. Add security-focused tests: path traversal (`../evil`, `N1/../N2`), empty string, slashes, null bytes. Add `sanitize_name()` in CLI pipeline.

- **Pros**: Complete security, defense in depth.
- **Cons**: None.
- **Effort**: Small.
- **Risk**: None.

## Technical Details

Affected files:
- `src/percell3/core/experiment_store.py` (`add_bio_rep`)
- `src/percell3/cli/import_cmd.py` (sanitize input)
- `tests/test_core/` (security tests)

## Acceptance Criteria

- [ ] add_bio_rep() calls _validate_name() as first operation
- [ ] CLI --bio-rep input goes through sanitize_name() before store call
- [ ] Tests cover: ../evil, empty string, slashes, null bytes, too-long names
- [ ] BioRepNotFoundError exception class created

## Work Log

- 2026-02-17 — Identified by security sentinel during plan review. Confirmed by learnings researcher (past P1 fix).

## Resources

- docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md
- Plan: docs/plans/2026-02-17-feat-data-model-bio-rep-fov-restructure-plan.md
