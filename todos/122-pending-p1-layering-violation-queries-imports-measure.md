---
status: complete
priority: p1
issue_id: "122"
tags: [code-review, architecture, layering]
dependencies: []
---

> **Resolved.** Verified 2026-03-08: no `from percell3.measure` imports exist in `src/percell3/core/`. `PARTICLE_SUMMARY_METRICS` now lives in `core/constants.py`.

# Layering violation: queries.py imports from percell3.measure

## Problem Statement

`queries.py` (in `percell3.core`) imports `PARTICLE_SUMMARY_METRICS` from `percell3.measure.particle_analyzer`. This creates a circular dependency where the core layer depends on a higher-level module, violating the hexagonal architecture principle stated in CLAUDE.md.

## Findings

- **Found by:** kieran-python-reviewer, architecture-strategist
- `queries.py:delete_stale_particles_for_fov_channel()` has `from percell3.measure.particle_analyzer import PARTICLE_SUMMARY_METRICS`
- `percell3.core` should have zero imports from `percell3.measure`, `percell3.segment`, etc.
- Currently a lazy import (inside the function), so it doesn't cause import-time failures, but it's still a design violation
- If `PARTICLE_SUMMARY_METRICS` changes in the measure module, core queries silently depend on it

## Proposed Solutions

### Solution A: Pass metric names as a parameter (Recommended)

Change `delete_stale_particles_for_fov_channel` to accept a `metric_names: list[str]` parameter. The caller (in `experiment_store.py`) passes the metric names.

**Pros:** Clean separation, no cross-layer imports
**Cons:** Caller needs to know the metrics
**Effort:** Small
**Risk:** Low

### Solution B: Define metric names in core as constants

Move `PARTICLE_SUMMARY_METRICS` to a constants module in `percell3.core`.

**Pros:** Single source of truth in core
**Cons:** Core shouldn't define measure-specific constants
**Effort:** Small
**Risk:** Low — but conceptually wrong

## Acceptance Criteria

- [ ] No imports from `percell3.measure` in `percell3.core`
- [ ] Metric names passed as parameter or defined in appropriate layer
- [ ] Tests still pass

## Technical Details

- **File:** `src/percell3/core/queries.py` — `delete_stale_particles_for_fov_channel()`
- **File:** `src/percell3/measure/particle_analyzer.py` — `PARTICLE_SUMMARY_METRICS`
