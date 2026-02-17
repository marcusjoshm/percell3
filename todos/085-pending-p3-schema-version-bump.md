---
status: pending
priority: p3
issue_id: "085"
tags: [plan-review, architecture, migration]
dependencies: []
---

# Schema Version Bump

## Problem Statement

The schema change is breaking. The percell_version field exists in the experiments table but is not checked on open. Bumping it would let open_database() detect old-format databases and raise a clear error.

## Findings

Architecture strategist: "Set percell_version to '3.1.0' in Phase 2's create_schema(). Add a check in open_database() that compares stored version against expected version."

## Proposed Solutions

### A) Bump percell_version and add version check on open

- **Effort:** Small
- **Risk:** Low

1. Set percell_version to "3.1.0" in create_schema() when creating new experiments.
2. Add a version check in open_database() that reads the stored percell_version and compares it against the expected version.
3. If the stored version is older than expected, raise a clear error message explaining the schema incompatibility and suggesting re-import.

## Technical Details

The experiments table already has a percell_version column. Currently it stores a version string but open_database() does not validate it. The check should use simple string comparison or semantic versioning (packaging.version.Version) to determine compatibility. For now, an exact match or major.minor match is sufficient — no need for a full migration framework.

## Acceptance Criteria

- [ ] New experiments have percell_version "3.1.0"
- [ ] open_database() detects old version and raises informative error

## Work Log

_No work performed yet._

## Resources

- Plan review: architecture strategist feedback
- Current schema: `src/percell3/core/schema.py`
