---
status: pending
priority: p2
issue_id: 166
tags: [code-review, agent-native, image-calculator, cli]
dependencies: []
---

# Image Calculator crashes from interactive CLI menu

## Problem Statement

The `_make_plugin_runner` dispatch in `cli/menu.py` falls through to `_run_generic_plugin()` for `image_calculator`, which calls `registry.run_plugin()` with `parameters=None`. The plugin immediately raises `RuntimeError("Parameters are required")`. A user selecting "image_calculator" from the Plugins menu sees an unhandled crash.

## Findings

- **Source**: agent-native-reviewer (Finding #1 - Critical)
- **Location**: `src/percell3/cli/menu.py:373-383`
- The programmatic API works perfectly. Only the interactive CLI menu path is broken.
- Existing plugins (`local_bg_subtraction`, `split_halo_condensate_analysis`) have custom handlers that collect parameters via `numbered_select_one()`.

## Proposed Solutions

### Option A: Add dedicated menu handler (Recommended)

Add `_run_image_calculator(state, registry)` that prompts for mode, operation, FOV, channels, and constant using `numbered_select_one()`. Wire into `_make_plugin_runner` dispatch.

- **Pros**: Matches existing pattern, full parameter collection
- **Cons**: More code in menu.py
- **Effort**: Medium
- **Risk**: Low

### Option B: Make generic runner schema-aware

Make `_run_generic_plugin` introspect `get_parameter_schema()` and generate prompts automatically.

- **Pros**: Future-proofs all plugins
- **Cons**: More complex, schema-to-prompt mapping is non-trivial
- **Effort**: Large
- **Risk**: Medium

## Acceptance Criteria

- [ ] Selecting "image_calculator" from Plugins menu collects all required parameters
- [ ] Single-channel and two-channel modes work through the menu
- [ ] Plugin runs successfully and shows derived FOV ID

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-03 | Created from code review | Generic plugin runner needs parameter collection |
