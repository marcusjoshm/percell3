---
status: complete
priority: p1
issue_id: "119"
tags: [code-review, schema, data-integrity, transaction-safety]
dependencies: []
resolution: "The function `delete_stale_particles_for_fov_channel()` no longer exists. It was replaced by simpler, focused functions: `delete_particles_for_fov()`, `delete_particles_for_threshold()`, `delete_particles_for_fov_threshold()`, and `delete_measurements_for_fov_threshold()`. Each commits unconditionally after deletion. Cleanup on threshold unassignment is handled by `experiment_store.unassign_threshold_from_fov()` which calls both measurement and particle deletion. Verified 2026-03-08."
---

# Transaction safety gap in delete_stale_particles_for_fov_channel

## Problem Statement

`delete_stale_particles_for_fov_channel()` in `queries.py` conditionally commits only when `total_deleted > 0`, but the measurement deletion block runs unconditionally. If particles were already deleted but summary measurements still exist, the measurement DELETE executes but `conn.commit()` is never called — leaving the transaction uncommitted.

## Resolution

The problematic function was removed during a refactor. Particle and measurement cleanup is now handled by separate, simpler functions that each commit unconditionally:
- `queries.delete_particles_for_fov()` (line 942)
- `queries.delete_particles_for_threshold()` (line 958)
- `queries.delete_particles_for_fov_threshold()` (line 981)
- `queries.delete_measurements_for_fov_threshold()` (line 1005)

The higher-level `experiment_store.unassign_threshold_from_fov()` orchestrates cleanup by calling both measurement and particle deletion functions.
