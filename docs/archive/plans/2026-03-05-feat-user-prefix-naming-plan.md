---
title: "feat: User prefix naming for thresholds and derived FOVs"
type: feat
date: 2026-03-05
---

# feat: User Prefix Naming for Thresholds and Derived FOVs

## Overview

Add a required naming prefix prompt to threshold and derived-FOV creation flows. Instead of opaque auto-generated names like `thresh_group_GFP_mean_intensity_g1_GFP_1`, the user enters a prefix (e.g., `"First_threshold"`) and the program generates structured names combining the prefix with the FOV display name and a context suffix.

## Problem Statement / Motivation

Current auto-naming produces verbose, opaque names that lack FOV identity:
- Threshold: `thresh_group_GFP_mean_intensity_g1_GFP_1` — no FOV, hard to identify
- Derived FOV: `HS_N1_FOV_001_bgsub_thresh_GFP_GFP_1_GFP` — embeds threshold name noise

This forces users to manually rename every entity after creation, which is the biggest workflow bottleneck for long analyses with many FOVs and groups.

## Proposed Solution

Add a prefix prompt at the start of each batch operation. The program constructs names as `{prefix}_{FOV_display_name}_{context_suffix}`. The prefix is entered once and applies to all entities in that batch.

### Naming Patterns

| Entity | Pattern | Example |
|--------|---------|---------|
| Grouped threshold | `{prefix}_{FOV_name}_g{N}` | `First_threshold_As_WT_1_g1` |
| Whole-FOV threshold | `{prefix}_{FOV_name}` | `First_threshold_As_WT_1` |
| BG subtraction FOV | `{prefix}_{FOV_name}_{channel}` | `Round1_As_WT_1_GFP` |
| Image calculator FOV | `{prefix}_{FOV_name}_{op}_{operand}` | `Norm_As_WT_1_divide_DAPI` |
| Split-halo FOV | `{prefix}_{FOV_name}_{phase}` | `Exp1_As_WT_1_condensed_phase` |

## Technical Approach

### Architecture

```
CLI (menu.py)
  ├── _prompt_prefix(fov_names, suffix_example) → validated prefix string
  │     ├── Prompt user for prefix (required, no default)
  │     ├── Validate: ^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$
  │     ├── Pre-check composed name length against all FOVs
  │     └── Show preview: "Names will look like: {prefix}_{first_fov}_g1"
  │
  ├── _apply_threshold(state) — threshold flow
  │     ├── _prompt_prefix() before FOV loop
  │     └── _threshold_fov(..., name_prefix=prefix)
  │           └── engine.threshold_group(..., name="prefix_FOV_g1")
  │                 └── store._generate_threshold_name(base_name="prefix_FOV_g1")
  │
  ├── _run_threshold_bg_subtraction(state) — bg subtraction
  │     ├── _prompt_prefix() before plugin.run()
  │     └── parameters["name_prefix"] = prefix
  │           └── plugin constructs: f"{prefix}_{fov_name}_{channel}"
  │
  ├── _run_image_calculator(state) — image calculator
  │     ├── _prompt_prefix() before plugin.run()
  │     └── parameters["name_prefix"] = prefix
  │           └── plugin constructs: f"{prefix}_{fov_name}_{op}_{operand}"
  │
  └── _run_condensate_analysis(state) — split-halo
        ├── _prompt_prefix() before plugin.run()
        └── parameters["name_prefix"] = prefix
              └── plugin constructs: f"{prefix}_{fov_name}_{phase}"
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Prefix validation | `^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$` | Stricter than general name validation; no spaces, max 50 chars |
| Prefix required | Always required, no default | Forces intentional naming; eliminates renaming bottleneck |
| FOV name in composed name | Full display name | Unambiguous identification |
| `g{N}` meaning | Per-FOV group index from GMM (g1, g2...) | Matches what user sees during interactive thresholding |
| Name collision handling | Append `_2`, `_3`... if name exists | Prevents crash on re-run with same prefix |
| Plugin prefix passing | Via `parameters["name_prefix"]` dict | Follows existing plugin parameter architecture |
| Threshold prefix passing | Via `name` param on `threshold_group()` | CLI constructs full name, engine uses it directly |
| Derived FOV idempotency | Preserved — same prefix+FOV+op = same name = reuse | Matches existing plugin behavior |
| Preview before batch | Show first composed name | Catches length/formatting issues early |
| Workflow pipeline | Out of scope | Can be added later; pipeline uses YAML config |
| Segmentation naming | Not affected | User confirmed current naming is acceptable |
| Local BG subtraction | Not affected | Exports CSVs only, no derived FOVs |

### Implementation Phases

#### Phase 1: Prefix Prompt Helper

- [x] Add `_prompt_prefix()` to `menu.py`
  - [x] Prompt: `"Naming prefix (e.g., 'Round1')"`
  - [x] Validate against `^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$`
  - [x] Retry loop on invalid input with clear error message
  - [x] Accept `fov_names: list[str]` and `suffix_example: str` for length pre-check
  - [x] Compute max composed name length: `len(prefix) + 1 + max(len(name) for name in fov_names) + 1 + len(suffix_example)`
  - [x] Reject if max length exceeds 255 chars
  - [x] Show preview: `"Names will look like: {prefix}_{first_fov}_{suffix_example}"`

#### Phase 2: Threshold Prefix Naming

- [x] Modify `ExperimentStore._generate_threshold_name()` (`experiment_store.py:425`)
  - [x] Add `base_name: str = ""` keyword argument
  - [x] If `base_name` provided: use it directly, check uniqueness, append `_2`, `_3`... if collision
  - [x] If `base_name` not provided: existing auto-generate behavior unchanged
- [x] Modify `ThresholdEngine.threshold_group()` (`thresholding.py:211`)
  - [x] Add `name: str = ""` keyword argument
  - [x] If `name` provided: pass as `base_name` to `_generate_threshold_name()`
  - [x] If `name` not provided: existing behavior unchanged
- [x] Modify `ThresholdEngine.threshold_fov()` (`thresholding.py:120`)
  - [x] Add `name: str = ""` keyword argument
  - [x] Same pattern as `threshold_group()`
- [x] Modify `_apply_threshold()` in `menu.py`
  - [x] Add `_prompt_prefix()` call after FOV selection, before the FOV loop
  - [x] Pass `fov_names=[f.display_name for f in selected_fovs]`
  - [x] Pass `suffix_example="g1"` (grouped) or `""` (whole-FOV)
  - [x] Pass `name_prefix` to `_threshold_fov()`
- [x] Modify `_threshold_fov()` in `menu.py`
  - [x] Accept `name_prefix: str = ""` parameter
  - [x] For each group `i`, construct: `name = f"{name_prefix}_{fov_info.display_name}_g{i+1}"`
  - [x] Pass `name=name` to `engine.threshold_group()`
  - [x] For whole-FOV (no groups): `name = f"{name_prefix}_{fov_info.display_name}"`

#### Phase 3: Plugin Derived FOV Prefix Naming

- [x] **Threshold BG Subtraction** (`threshold_bg_subtraction.py:282`)
  - [x] Check `parameters.get("name_prefix")` in `_process_threshold()`
  - [x] If prefix: `derived_name = f"{prefix}_{apply_fov_info.display_name}_{channel}"`
  - [x] If no prefix: existing behavior unchanged (backward compat)
  - [x] Modify `_run_threshold_bg_subtraction()` in `menu.py` to prompt and pass prefix
- [x] **Image Calculator** (`image_calculator.py:157-165`)
  - [x] Check `parameters.get("name_prefix")` in `run()`
  - [x] If prefix: `derived_name = f"{prefix}_{fov_info.display_name}_{operation}_{operand}"`
  - [x] If no prefix: existing behavior unchanged
  - [x] Modify `_run_image_calculator()` in `menu.py` to prompt and pass prefix
- [x] **Split-Halo Condensate Analysis** (`split_halo_condensate_analysis.py:561`)
  - [x] Check `parameters.get("name_prefix")` in `_create_derived_fovs()`
  - [x] If prefix: `derived_name = f"{prefix}_{fov_info.display_name}_{phase_type}"`
  - [x] If no prefix: existing behavior unchanged
  - [x] Modify `_run_condensate_analysis()` in `menu.py` to prompt and pass prefix

#### Phase 4: Tests

- [x] Unit tests for `_prompt_prefix()` validation
  - [x] Valid prefixes accepted
  - [x] Invalid prefixes rejected (spaces, special chars, empty, too long)
  - [x] Length overflow detected
- [x] Unit tests for `_generate_threshold_name(base_name=...)`
  - [x] Direct use when no collision
  - [x] `_2` appended on collision
  - [x] Fallback to auto-generate when no `base_name`
- [x] Integration test: threshold flow with prefix
  - [x] Verify threshold names match `{prefix}_{fov}_g{N}` pattern
  - [x] Verify groups numbered per-FOV (g1, g2 restart for each FOV)
- [x] Integration test: re-run with same prefix
  - [x] Thresholds get `_2` suffix on collision
  - [x] Derived FOVs reuse existing (idempotent)

## Acceptance Criteria

### Functional Requirements

- [x] User is prompted for a naming prefix before each batch threshold or plugin run
- [x] Prefix is required — empty input re-prompts
- [x] Threshold names follow `{prefix}_{FOV_display_name}_g{N}` pattern
- [x] Derived FOV names follow `{prefix}_{FOV_display_name}_{auto_suffix}` pattern
- [x] Name preview shown before batch starts
- [x] Re-run with same prefix doesn't crash (uniqueness counter appended)
- [x] Existing auto-naming behavior preserved when no prefix is provided (backward compat for programmatic callers)

### Non-Functional Requirements

- [x] Prefix validated against strict regex (alphanumeric, underscores, hyphens, max 50 chars)
- [x] Composed name length validated against all target FOVs before batch starts
- [x] Clear error messages for invalid prefix or length overflow

## Technical Considerations

### Existing Code to Modify

| File | Function | Change |
|------|----------|--------|
| `experiment_store.py:425` | `_generate_threshold_name()` | Add `base_name` kwarg |
| `thresholding.py:211` | `threshold_group()` | Add `name` kwarg |
| `thresholding.py:120` | `threshold_fov()` | Add `name` kwarg |
| `menu.py:2635` | `_apply_threshold()` | Add prefix prompt |
| `menu.py:2441` | `_threshold_fov()` | Accept and use prefix |
| `threshold_bg_subtraction.py:282` | `_process_threshold()` | Use prefix in name |
| `image_calculator.py:157` | `run()` | Use prefix in name |
| `split_halo_condensate_analysis.py:561` | `_create_derived_fovs()` | Use prefix in name |
| `menu.py:511` | `_run_threshold_bg_subtraction()` | Add prefix prompt |
| `menu.py:425` | `_run_image_calculator()` | Add prefix prompt |
| `menu.py:807` | `_run_condensate_analysis()` | Add prefix prompt |

### New Code

| New | Purpose |
|-----|---------|
| `_prompt_prefix()` in `menu.py` | Validate prefix, pre-check lengths, show preview |

### Known Limitations

- **Workflow pipeline** not affected — uses YAML config, can be extended later
- **FOV rename after derived creation** may cause name staleness — derived FOV names still embed the old FOV name. This is a pre-existing issue with derived FOV naming.
- **Condensate plugin FOV filter** uses hardcoded `startswith("condensed_phase_")` — with user prefixes, this filter will no longer work. Should be updated to use a different mechanism (e.g., check `source_fov_id` or `parameters["imported"]`).

## References

### Internal References

- Brainstorm: `docs/brainstorms/2026-03-05-user-prefix-naming-brainstorm.md`
- Threshold name generator: `src/percell3/core/experiment_store.py:425`
- Threshold engine: `src/percell3/measure/thresholding.py:120,211`
- CLI threshold flow: `src/percell3/cli/menu.py:2635`
- BG subtraction plugin: `src/percell3/plugins/builtin/threshold_bg_subtraction.py:282`
- Image calculator plugin: `src/percell3/plugins/builtin/image_calculator.py:157`
- Split-halo plugin: `src/percell3/plugins/builtin/split_halo_condensate_analysis.py:561`
- Name validation: `src/percell3/core/experiment_store.py:14`
