---
title: "CLI Module Integration Review: ImportEngine Channel Registration and Rich Markup Bugs"
date: 2026-02-13
category: integration-issues
tags:
  - integration-bug
  - io-module
  - cli-module
  - channel-registration
  - rich-markup
  - code-review
modules:
  - io
  - cli
  - core
severity: high
status: documented
problem_type:
  - ImportEngine channel registration failure on single-channel TIFF files
  - Rich console markup consuming letter-key menu indicators
---

# CLI Module Integration Review: Two Critical Bugs

Found during a targeted review of the interactive menu's interfaces with the core and IO modules on branch `feat/cli-module`.

## Problem Symptoms

### Bug 1: Import fails for plain TIFF files
```
ChannelNotFoundError: Channel not found: ch0
```
Any TIFF files without `_ch00`/`_ch01` suffixes fail to import. This includes most single-channel microscopy files (e.g., `image001.tif`, `cell_region1.tif`).

### Bug 2: Menu letter keys invisible
The interactive menu renders:
```
  [1] Create experiment       <-- visible
  [2] Import images           <-- visible
  ...
   Select experiment          <-- [e] MISSING
   Help                       <-- [h] MISSING
   Quit                       <-- [q] MISSING
```
Users cannot see the key indicators for letter-based menu items.

## Investigation Steps

### Bug 1 investigation
1. Tested `ExperimentStore.create()` and `.open()` directly -- both work (core module is fine)
2. Tested `FileScanner.scan()` on plain TIFF files -- works, returns `channels=[]`
3. Tested `ImportEngine.execute()` end-to-end -- `ChannelNotFoundError`
4. Traced through engine code line by line (see Root Cause below)
5. Confirmed ALL existing IO tests use `img_ch00.tif` naming -- no coverage for plain filenames
6. Confirmed default `TokenConfig.channel` pattern is `r"_ch(\d+)"` -- only matches `_ch00`, `_ch01`, etc.

### Bug 2 investigation
1. Observed invisible keys in piped menu output
2. Tested Rich directly: `console.print("[1] Test")` renders correctly; `console.print("[e] Test")` loses `[e]`
3. Confirmed all numeric keys `[1]`-`[9]` render fine; all letter keys `[e]`, `[h]`, `[q]` are consumed
4. Tested fix: escaped brackets `console.print("\\[e] Test")` renders correctly as `[e] Test`

## Root Cause Analysis

### Bug 1: ImportEngine default channel registration

**File**: `src/percell3/io/engine.py`

The `ImportEngine.execute()` has a mismatch between channel registration and channel usage:

1. **Lines 60-71**: Channel registration iterates `scan_result.channels`:
   ```python
   for ch_token in scan_result.channels:  # EMPTY for plain filenames
       ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))
       store.add_channel(ch_name, ...)
   ```

2. **Line 107**: File grouping uses default channel token `"0"`:
   ```python
   channel_files = _group_by_token(files, "channel", "0")
   ```

3. **Line 125**: Name derived as `"ch0"`:
   ```python
   ch_name = channel_name_map.get(ch_token, sanitize_name(f"ch{ch_token}"))  # -> "ch0"
   ```

4. **Line 139**: Write fails because `"ch0"` was never registered:
   ```python
   store.write_image(region_name, condition, ch_name, data)  # ChannelNotFoundError
   ```

**Gap**: When `scan_result.channels` is empty (no `_ch` tokens in filenames), the registration loop body never executes, but the grouping and naming logic still generates `"ch0"` as the channel name.

### Bug 2: Rich markup consumes letter menu keys

**File**: `src/percell3/cli/menu.py:145-151`

```python
console.print(f"  [{item.key}] {item.label}")
```

Rich's markup parser treats `[letter]` as style tags. Single-letter sequences like `[e]`, `[h]`, `[q]` are consumed as (unrecognized) markup. Numeric keys `[1]`-`[9]` are not valid Rich style names, so they pass through as literal text.

## Proposed Solutions

### Bug 1 fix: Register default channel when none discovered

In `ImportEngine.execute()`, after the channel registration loop (after line 71):

```python
# Register default channel if no channel tokens were discovered
if not scan_result.channels:
    default_ch_name = sanitize_name("ch0")
    try:
        store.add_channel(default_ch_name)
        channels_registered += 1
    except DuplicateError:
        pass
```

### Bug 2 fix: Escape brackets in menu rendering

In `_show_menu()`, escape the opening bracket so Rich treats it as literal text:

```python
# Replace:
console.print(f"  [{item.key}] {item.label}")
# With:
console.print(f"  \\[{item.key}] {item.label}")
```

Alternative: use `markup=False` or Rich's `Text` object for the menu line.

## Prevention: Test Cases to Add

### For Bug 1 (`tests/test_io/test_engine.py`)

1. **`test_imports_plain_tiff_no_channel_token`**: Create `image001.tif`, `image002.tif` (no `_ch` pattern). Assert `result.channels_registered >= 1` and `result.images_written >= 1`. Verify `store.get_channels()` returns non-empty list.

2. **`test_single_file_no_tokens`**: Single file `data.tif` with no channel/region/z tokens. Verify full import pipeline succeeds end-to-end.

### For Bug 2 (`tests/test_cli/test_menu.py`)

1. **`test_letter_key_indicators_visible`**: Render the menu and assert that literal `[e]`, `[h]`, `[q]` strings appear in the plain-text output.

2. **`test_all_menu_keys_visible`**: For every `MenuItem`, verify `[{key}]` appears literally in rendered output.

## Prevention: Code Review Checklist

- [ ] When using `f"[{variable}]"` in `console.print()`, verify the variable is escaped or `markup=False` is used
- [ ] When iterating a scanner result list to register entities, check what happens when the list is empty but a default value is used downstream
- [ ] Ensure IO tests include plain filenames without token patterns (real microscopy files often lack structured naming)
- [ ] Test Rich output by checking the plain-text content, not just exit codes

## Module Ownership Summary

| Feature | Module | Works? |
|---------|--------|--------|
| Create experiment | Core (`ExperimentStore.create`) | Yes |
| Select experiment | Core (`ExperimentStore.open`) | Yes |
| Scan TIFF directory | IO (`FileScanner.scan`) | Yes |
| Import pipeline | IO (`ImportEngine.execute`) | **No** -- channel registration bug |
| Menu display | CLI (`menu.py`) | **No** -- Rich markup bug |

**No new modules need to be built.** Core and IO are complete. The fixes are:
1. A ~6-line patch in `io/engine.py` for channel registration
2. A ~1-line fix in `cli/menu.py` for bracket escaping

## Cross-References

- `docs/solutions/logic-errors/io-module-p1-z-projection-and-input-validation-fixes.md` -- prior IO module P1 fixes
- `docs/solutions/architecture-decisions/cli-module-code-review-findings.md` -- CLI module review findings
- `docs/solutions/security-issues/core-module-p1-security-correctness-fixes.md` -- core module validation patterns
- `todos/017-pending-p2-menu-logic-duplication.md` -- menu delegation (related, already addressed in Phase D)
