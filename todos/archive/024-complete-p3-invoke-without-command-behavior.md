---
status: pending
priority: p3
issue_id: "024"
tags: [code-review, cli, agent-native]
dependencies: []
---
# invoke_without_command Silently Launches Interactive Menu

## Problem Statement
Running `percell3` with no arguments silently enters the interactive menu, which blocks on stdin. Agents or scripts that accidentally invoke the bare command will hang. Most CLI tools show help text when invoked without arguments.

## Findings
- `main.py:15-23`: `invoke_without_command=True` triggers `run_interactive_menu()` when no subcommand given
- No way to distinguish "user wants interactive mode" from "user forgot subcommand"
- Scripts piping to percell3 or agents invoking it without args will hang on stdin

**Source:** agent-native-reviewer WARNING-7

## Proposed Solutions
### Option A: Show help by default, add explicit `percell3 menu` subcommand
Remove `invoke_without_command=True`. Add a `menu` subcommand that explicitly launches interactive mode. Bare `percell3` shows help.

Pros: Predictable for both humans and agents, explicit intent
Cons: Users must type `percell3 menu` instead of just `percell3`
Effort: Small

### Option B: Keep current behavior, detect non-interactive stdin
Check `sys.stdin.isatty()` before launching menu. If not a TTY, show help instead.

Pros: Smart behavior, no command change
Cons: Slightly magical, harder to test
Effort: Small

## Acceptance Criteria
- [ ] `percell3` (no args, non-TTY) does not hang
- [ ] Interactive menu is still accessible
- [ ] All existing tests pass

## Work Log
### 2026-02-13 - Code Review Discovery
Agent-native-reviewer flagged silent menu launch as hostile to automation.
