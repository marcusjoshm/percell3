---
title: "User Prefix Naming for Thresholds and Derived FOVs"
date: 2026-03-05
type: feat
---

# User Prefix Naming for Thresholds and Derived FOVs

## What We're Building

Add a required naming prefix prompt to threshold and derived-FOV creation flows. Instead of opaque auto-generated names like `thresh_group_GFP_mean_intensity_g1_GFP_1`, the user enters a prefix (e.g., `"First_threshold"`) and the program generates structured names combining the prefix with the FOV display name and operation-specific suffix.

### Naming Patterns

**Thresholds (grouped):**
```
{user_prefix}_{FOV_display_name}_g{N}
```
Example: User enters `"First_threshold"`, FOVs are `As_WT_1`, `As_WT_2`, `As_WT_3`, each with 2 groups:
- `First_threshold_As_WT_1_g1`
- `First_threshold_As_WT_1_g2`
- `First_threshold_As_WT_2_g1`
- `First_threshold_As_WT_2_g2`
- `First_threshold_As_WT_3_g1`
- `First_threshold_As_WT_3_g2`

**Thresholds (whole-FOV, no groups):**
```
{user_prefix}_{FOV_display_name}
```
Example: `First_threshold_As_WT_1`

**Derived FOVs (bg subtraction, image calculator, split-halo):**
```
{user_prefix}_{FOV_display_name}_{auto_suffix}
```
Where `auto_suffix` preserves operation context (e.g., `bgsub_GFP`, `divide_DAPI`, `condensed_phase`).

### Scope

| Entity | Change | Example |
|--------|--------|---------|
| Thresholds | Add prefix prompt, restructure name | `First_threshold_As_WT_1_g1` |
| Derived FOVs | Add prefix prompt, restructure name | `Round1_As_WT_1_bgsub_GFP` |
| Segmentations | No change | `cyto3_DAPI_1` (unchanged) |

## Why This Approach

The current auto-naming produces verbose, opaque names that lack FOV identity:
- `thresh_group_GFP_mean_intensity_g1_GFP_1` — no FOV name, hard to identify
- `HS_N1_FOV_001_bgsub_thresh_GFP_GFP_1_GFP` — embeds threshold name noise

This forces users to manually rename every entity after creation, which is the biggest workflow bottleneck for long analyses.

A simple prefix prompt solves this with minimal complexity:
- User controls the semantic meaning via the prefix
- FOV name provides identity
- Auto-suffix preserves operation context
- No template syntax to learn

## Key Decisions

1. **Prefix is required** — no default value, user must type something every time
2. **FOV name uses full display name** — unambiguous, even if long
3. **Segmentations excluded** — current naming is acceptable
4. **Auto-suffix preserved for derived FOVs** — keeps operation context without user effort
5. **Prefix prompt appears once per batch** — user enters it once, applies to all FOVs in that run
6. **Simple approach** — one new prompt per flow, no template/placeholder system

## Affected Flows

1. **Grouped intensity thresholding** (`_apply_threshold` in menu.py) — prompt before FOV loop
2. **Whole-FOV thresholding** — same flow, simpler name (no group suffix)
3. **Background subtraction plugin** (`threshold_bg_subtraction.py`) — prompt before processing
4. **Image calculator plugin** (`image_calculator.py`) — prompt before processing
5. **Split-halo condensate analysis** (`split_halo_condensate_analysis.py`) — prompt before processing

## Open Questions

None — all key decisions resolved during brainstorming.
