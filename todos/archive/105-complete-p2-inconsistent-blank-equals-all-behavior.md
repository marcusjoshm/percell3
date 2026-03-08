---
status: complete
priority: p2
issue_id: "105"
tags: [code-review, cli, ux, consistency]
dependencies: []
---

# Inconsistent blank="all" behavior across the app

## Problem Statement

Some selection prompts treat blank input as "all" (pressing Enter selects everything), while others require typing "all" explicitly. This is confusing — users can't predict which behavior they'll get.

## Findings

- **Found by:** User testing
- **Location:** `src/percell3/cli/menu.py`
- **Blank = all (default="all"):**
  - `_select_fovs_from_table()` line 986: `default="all"` — blank selects all FOVs
- **Must type "all" explicitly:**
  - `numbered_select_many()` line 132-169: no default, user must type "all"
  - Used for channel selection, metric selection, threshold channel selection, etc.
  - `_parse_group_selection()` line 877: requires typing "all" for groups
  - `_query_bio_reps()` line 1967: `default=""` — blank means "no filter" (all), but the prompt says "blank = all"

## Proposed Solutions

### Solution A: Make blank consistently mean "all" everywhere (Recommended)
1. Update `numbered_select_many()` to accept `default="all"` and treat blank as "all"
2. Update all multi-select prompts to use this pattern
3. Update prompt text to say "(blank=all)" consistently
4. Keep `_parse_group_selection()` consistent — blank means "all" unassigned groups
- **Effort:** Small | **Risk:** Low

### Solution B: Make blank consistently require typing "all"
- Remove `default="all"` from `_select_fovs_from_table()`
- Less convenient but more explicit
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] All multi-select prompts behave the same way on blank input
- [ ] Prompt text clearly indicates what blank does
- [ ] `numbered_select_many()` supports default="all" for blank=all
- [ ] FOV selection, channel selection, metric selection all consistent

## Work Log

- 2026-02-25: Identified during user interface testing
