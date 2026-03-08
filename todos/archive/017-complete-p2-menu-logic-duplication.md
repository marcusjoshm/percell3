---
status: pending
priority: p2
issue_id: "017"
tags: [code-review, architecture, cli]
dependencies: []
---
# Menu Duplicates Business Logic Instead of Delegating to CLI Commands

## Problem Statement
The interactive menu (`menu.py`, 404 LOC) reimplements business logic that already exists in Click commands instead of delegating to them. This creates maintenance risk — bug fixes in CLI commands won't propagate to the menu and vice versa. The menu's query tables already diverge from the CLI version (missing "Pixel Size" column).

## Findings
- `menu.py:296-353` (`_query_experiment`): Copy-pastes table rendering from `query.py` lines 49-56, 82-91, 124-128
- `menu.py:179-258` (`_import_images`): Duplicates `import_cmd.py` lines 62-119; `_run_import` was extracted for sharing but menu doesn't use it
- `menu.py:312-313`: Dead imports (`from percell3.cli.query import channels`, `from click import Context`) suggest abandoned refactor to delegate
- `menu.py:157-177` (`_create_experiment`): Manually manages `state.experiment_path` and `state.store` instead of calling `state.set_experiment()`
- `menu.py:260-293`: tkinter folder picker introduces GUI dependency into CLI tool
- `menu.py:369-391` (`_run_workflow`): Hardcodes same messages from `workflow.py`

**Source:** kieran-python-reviewer HIGH-4/5/8, code-simplicity-reviewer #1/#3, agent-native-reviewer CRITICAL-1/2

## Proposed Solutions
### Option A: Refactor menu to delegate to Click commands (Recommended)
Extract shared rendering functions from query.py (e.g., `render_channels_table`, `render_regions_table`). Menu handlers call these shared functions or invoke Click commands via `ctx.invoke()`. Remove tkinter dependency.

Pros: Single source of truth, menu stays thin, testable via CliRunner
Cons: Requires refactoring both menu.py and command files
Effort: Medium

### Option B: Remove menu.py entirely
Remove interactive menu. `percell3` with no args shows help. Add menu back when more modules are built.

Pros: Eliminates 404 LOC of duplication, simplest solution
Cons: Loses interactive mode (which was a planned feature)
Effort: Small

### Option C: Keep menu as-is, accept divergence risk
Document that menu is a convenience layer and may diverge from CLI commands.

Pros: No code changes needed
Cons: Bugs will diverge, violates DRY, technical debt accumulates
Effort: None

## Acceptance Criteria
- [ ] No duplicated rendering logic between menu.py and command files
- [ ] Menu handlers delegate to shared functions or Click commands
- [ ] Dead imports removed from menu.py
- [ ] _create_experiment uses state.set_experiment() properly
- [ ] tkinter dependency removed or isolated
- [ ] All existing tests still pass

## Work Log
### 2026-02-13 - Code Review Discovery
Three independent reviewers (kieran-python, code-simplicity, agent-native) flagged menu logic duplication as the highest-severity architectural issue.
