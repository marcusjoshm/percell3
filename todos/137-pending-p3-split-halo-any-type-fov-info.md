---
status: pending
priority: p3
issue_id: 137
tags: [code-review, quality, plugins]
---

# `_create_derived_fovs` uses `Any` instead of `FovInfo` type

## Problem Statement
`split_halo_condensate_analysis.py` line 429 types `fov_info` parameter as `Any` instead of `FovInfo`. The `TYPE_CHECKING` import is already at file top. Also mixed-type CSV column (`norm_mean_intensity` has `""` vs `float`).

## Acceptance Criteria
- [ ] `fov_info: FovInfo` in type signature
- [ ] CSV columns use consistent types (NaN or empty, not mixed)
