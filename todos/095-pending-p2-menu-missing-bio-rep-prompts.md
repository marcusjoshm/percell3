---
status: pending
priority: p2
issue_id: "095"
tags: [code-review, cli, menu, agent-native, bio-rep]
dependencies: []
---

# Interactive Menu Missing `bio_rep` Prompts for Import and Segment

## Problem Statement

The interactive menu's `_import_images` and `_segment_cells` functions do not prompt for or pass `bio_rep`. Users going through the menu always get the default N1. With multiple bio reps, there is no way to select a specific one through the interactive menu, even though the CLI flags (`--bio-rep`) support it.

## Findings

- **Found by:** agent-native-reviewer
- **Evidence:**
  - `menu.py:199-280`: `_import_images` doesn't prompt for bio_rep
  - `menu.py:283-395`: `_segment_cells` doesn't prompt for bio_rep, doesn't pass to `engine.run()`

## Proposed Solutions

### Solution A: Add bio_rep prompt with auto-resolve (Recommended)
- After condition selection, add `Prompt.ask("Biological replicate", default="N1")`
- Use auto-resolve pattern: if only 1 bio rep exists, skip the prompt
- Pass bio_rep to `_run_import()` and `engine.run()`
- **Effort:** Small | **Risk:** Low

## Acceptance Criteria

- [ ] Menu prompts for bio_rep when >1 exists
- [ ] Auto-resolves when only 1 bio rep exists (no prompt)
- [ ] Selected bio_rep is passed through to import and segment operations

## Work Log

- 2026-02-17: Identified during code review
