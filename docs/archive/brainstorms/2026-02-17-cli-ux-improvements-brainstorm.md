---
title: CLI UX Improvements — Recent Experiments, Channel Reuse, Numbered Selection, Editing, Navigation
type: feat
date: 2026-02-17
status: decided
---

# CLI UX Improvements Brainstorm

## What We're Building

Five interconnected UX improvements to the percell3 interactive menu that reduce repetitive typing, prevent user errors, and make navigation feel natural. These bring the CLI closer to the original PerCell's interaction model while leveraging Rich's capabilities.

## Why These Changes

The current menu uses `rich.prompt.Prompt.ask` with freeform text entry for most inputs. This means:
- Users retype full experiment paths every session
- Channel names are typed repeatedly during import (error-prone)
- Conditions/regions must be typed exactly (no numbered pick-lists)
- Mistakes require quitting and relaunching
- No way to rename entities after creation

## Key Decisions

### 1. Recent Experiments — Auto-Load + History

**Decision:** Auto-load the last experiment on startup AND maintain a recent experiments list.

**Behavior:**
- On startup, if a recent history exists, auto-load the last-used experiment
- Show `[Last: experiment_name.percell]` in the header
- New menu option `e` becomes "Select experiment" with a sub-menu:
  - `[1]-[N]` Recent experiments (most recent first, up to 10)
  - `[n]` Enter new path
  - `[b]` Back
- History stored in `~/.config/percell3/recent.json` — list of paths with last-accessed timestamps
- Invalid/deleted paths silently removed from history on access

**Current state:** No history mechanism. Users type full paths via `Prompt.ask` every time.

### 2. Channel Reuse — Auto-Match + Numbered Pick List

**Decision:** Auto-match discovered tokens to existing channels first, then show a numbered list for unmatched tokens.

**Behavior:**
- Scanner discovers channel tokens from filenames (existing behavior)
- For each token, check if it matches an existing channel name in the experiment
- Auto-matched channels shown as `[auto] 00 → DAPI`
- Unmatched tokens get a numbered pick list:
  ```
  Channel '02' not in experiment. Assign to:
    [1] DAPI
    [2] GFP
    [3] RFP
    [n] New channel name
  ```
- If experiment has no channels yet (first import), fall back to current freeform prompting
- `--channel-map` CLI flag behavior unchanged (non-interactive path unaffected)

**Current state:** Each channel token prompts freeform `Prompt.ask(f"Name for channel '{ch}'")` with no reuse.

### 3. Numbered Selection System — Space-Separated + 'all'

**Decision:** Replace typed-name selection with numbered lists. Multi-select uses space-separated numbers or `'all'`.

**Behavior:**
- Anywhere the user picks from a list (conditions, regions, channels), show numbered options:
  ```
  Conditions:
    [1] control
    [2] treated
    [3] vehicle
  Select (space-separated, or 'all'): 1 3
  ```
- Single-select: enter one number
- Multi-select: space-separated numbers or `all`
- Auto-select when only one option exists (existing behavior, keep)
- `'b'` to go back is always available in numbered prompts

**Where this applies:**
- Condition selection (view, segment, export)
- Region selection (view, segment)
- Channel selection (segment, export, view `--channels`)
- Any future list-based prompts

**Current state:** Users type exact names validated by `choices=`. Some prompts use freeform comma-separated strings.

### 4. Entity Editing — Sub-Menu Under Query

**Decision:** Add rename/edit capabilities as a sub-option under the existing query menu. All entity types editable: experiment name, conditions, regions, channels.

**Behavior:**
- Query menu gets new option:
  ```
  [1] List channels
  [2] List regions
  [3] List conditions
  [4] Edit / rename
  [b] Back
  ```
- Edit sub-menu:
  ```
  Edit:
    [1] Rename experiment
    [2] Rename condition
    [3] Rename region
    [4] Rename channel
    [b] Back
  ```
- For rename: show numbered list of entities, pick one, type new name
- Validation: new name can't conflict with existing names
- Updates propagate: renaming a condition updates all regions under it, renaming a channel updates all measurements, etc.

**Current state:** No edit/rename capability exists. Users would need to create a new experiment.

**Implementation note:** Requires new `ExperimentStore` methods: `rename_condition()`, `rename_region()`, `rename_channel()`, `rename_experiment()`. These update the SQLite metadata and (for conditions/regions) the Zarr group paths.

### 5. Universal Navigation — 'h' for Home, 'b' for Back

**Decision:** Two navigation commands available everywhere: `'h'` jumps to the home menu, `'b'` goes back one level.

**Behavior:**
- `'h'` — return to home menu immediately from any depth. Cancels current operation.
- `'b'` — go back one level (to parent menu or previous prompt). Same as current `_MenuCancel` but consistent.
- `'q'` — quit the app, but ONLY from the home menu. Typing `'q'` in a sub-prompt acts like `'b'`.
- Every `Prompt.ask` call shows available navigation: `(h=home, b=back)`
- Implemented via a wrapper around `Prompt.ask` that intercepts `'h'` and `'b'` before passing to the handler

**Current state:** `'b'` works in some prompts but not all. `'q'` quits from the top menu only. No `'h'` home shortcut. No consistent navigation hints.

**Implementation approach:** Create a `menu_prompt()` helper that wraps `Prompt.ask`:
```python
def menu_prompt(prompt_text: str, **kwargs) -> str:
    """Prompt with universal navigation. Raises _MenuHome or _MenuCancel."""
    hint = "(h=home, b=back)"
    result = Prompt.ask(f"{prompt_text} {hint}", **kwargs)
    if result.lower() == "h":
        raise _MenuHome()
    if result.lower() == "b":
        raise _MenuCancel()
    return result
```
Main loop catches `_MenuHome` to reset to top level.

## Implementation Order

These features have natural dependencies:

1. **Navigation (#5)** — Foundation. The `menu_prompt()` wrapper affects all other features.
2. **Numbered selection (#3)** — Core interaction change. Build `numbered_select()` helper.
3. **Recent experiments (#1)** — Uses numbered selection for the history list.
4. **Channel reuse (#2)** — Uses numbered selection for the pick list.
5. **Entity editing (#4)** — Uses numbered selection + requires new `ExperimentStore` methods.

## Open Questions

None — all key decisions resolved through brainstorming.
