---
status: pending
priority: p1
issue_id: 152
tags: [code-review, quality, cli, ux]
dependencies: []
---

# _MenuCancel Swallowed in _prompt_tile_config — Infinite Loop

## Problem Statement

In `src/percell3/cli/menu.py` lines 1101-1125, the `_prompt_tile_config` function catches `_MenuCancel` alongside `ValueError` during grid dimension prompts:

```python
except (ValueError, _MenuCancel):
    console.print("[red]Enter an integer >= 1[/red]")
    continue
```

Catching `_MenuCancel` here means the user cannot escape the prompt by pressing Ctrl+C or typing "back". The `_MenuCancel` exception is designed to bubble up and let the user navigate out of the current prompt flow. By catching it, the loop becomes effectively infinite — the user is trapped.

## Findings

- **Source**: kieran-python-reviewer
- **Location**: `src/percell3/cli/menu.py:1101-1125`
- **Evidence**: The `except (ValueError, _MenuCancel)` clause catches both input validation errors and user cancellation in the same handler, treating them identically

## Proposed Solutions

### Option A: Only catch ValueError (Recommended)
- **Pros**: Simple, follows existing pattern in other prompts
- **Cons**: None
- **Effort**: Small
- **Risk**: Low

```python
except ValueError:
    console.print("[red]Enter an integer >= 1[/red]")
    continue
```

Let `_MenuCancel` propagate naturally to the caller.

## Technical Details

- **Affected files**: `src/percell3/cli/menu.py`

## Acceptance Criteria

- [ ] `_MenuCancel` is NOT caught in the grid dimension prompt loops
- [ ] User can exit tile config prompt by pressing back/cancel
- [ ] ValueError still shows the "Enter an integer" message

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-02 | Created from code review | Found by kieran-python-reviewer |
