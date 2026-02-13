---
topic: CLI Interactive Menu Design
date: 2026-02-13
status: decided
---

# CLI Interactive Menu Design

## What We're Building

A dual-mode command-line interface for PerCell 3:

1. **Interactive menu mode** (`percell3` with no args) — a persistent numbered menu where users navigate options, similar to PerCell 2's custom interactive menu. Built with Rich for colors and formatting.

2. **Direct command mode** (`percell3 import ...` with args) — standard Click commands for scriptability, automation, and testing.

Both modes call the same underlying functions. The menu is a thin dispatcher over Click command logic.

## Why Now

Three of seven modules are complete (Core, IO, Workflow). This is enough to make several commands fully functional:

- `percell3 create` — create experiments (Core)
- `percell3 import` — import TIFF directories (Core + IO)
- `percell3 query` — inspect channels, regions, conditions (Core)
- `percell3 workflow list` — list available workflows (Workflow)
- `percell3 workflow run` — run import-only workflows (Workflow + IO)

Building the CLI now lets the user exercise the system interactively as remaining modules (Segment, Measure, Plugins) are built. Each new module adds functional menu items without rearchitecting the interface.

## Why This Approach

**Dual-mode (menu + commands) over menu-only:**
- Scriptability matters for batch processing and CI
- Click commands are independently testable with `CliRunner`
- Menu is trivial — a `while True` loop with `rich.prompt`
- No code duplication: menu items call Click command functions directly

**Simple Rich menus over full Textual TUI:**
- Textual is heavy investment before all modules exist
- Simple numbered menus match PerCell 2's interaction pattern
- Can upgrade to Textual later without changing underlying logic
- Rich is already a dependency; Textual would be new

**Build now over waiting:**
- Enough modules to make core workflows functional
- Interactive testing catches integration issues early
- Menu grows incrementally as modules are added

## Key Decisions

1. **Dual-mode entry:** No args = interactive menu, with args = direct command
2. **Rich-based menus:** Simple numbered menus with Rich formatting. No Textual yet.
3. **Unbuilt modules shown as disabled:** Menu shows all planned commands; unbuilt ones display "Coming soon" and are not selectable
4. **External GUI launching:** Commands can spawn external tools (napari for viewing, Cellpose GUI for segmentation, ImageJ for ROIs) as subprocesses
5. **Start simple, upgrade later:** Build minimal viable menu now, upgrade to Textual TUI if/when needed after all modules are complete

## Functional Commands (Now)

| Command | Menu Item | Module Deps | Status |
|---------|-----------|-------------|--------|
| `create` | Create experiment | Core | Ready |
| `import` | Import images | Core, IO | Ready |
| `query` | Query experiment | Core | Ready |
| `export` | Export to CSV | Core | Ready |
| `workflow list` | List workflows | Workflow | Ready |
| `workflow run` | Run workflow | Workflow, IO | Ready (import-only) |

## Disabled Commands (Coming Soon)

| Command | Menu Item | Module Deps | Status |
|---------|-----------|-------------|--------|
| `segment` | Segment cells | Segment | Coming soon |
| `measure` | Measure channels | Measure | Coming soon |
| `threshold` | Apply threshold | Measure | Coming soon |
| `plugin list/run` | Manage plugins | Plugins | Coming soon |

## Interactive Menu Structure

```
PerCell 3 — Single-Cell Microscopy Analysis

  Experiment: ~/experiments/my_exp (or: No experiment selected)

  [1] Create experiment
  [2] Import images
  [3] Segment cells          (coming soon)
  [4] Measure channels       (coming soon)
  [5] Apply threshold        (coming soon)
  [6] Query experiment
  [7] Export to CSV
  [8] Run workflow
  [9] Plugin manager         (coming soon)
  [0] Settings / Help

  [q] Quit

Select an option:
```

## Technology Stack

- **Click** — command structure, argument parsing, help text
- **Rich** — console output, tables, progress bars, prompts, menus
- **subprocess** — launching external GUI tools (napari, Cellpose, ImageJ)
- **tkinter.filedialog** (optional) — native OS file/folder picker for import paths

## Resolved Questions

1. **File selection UX:** Both options. Default to native OS folder picker (tkinter.filedialog) in interactive menu mode. Also accept path as a CLI argument for scriptable use. Tkinter is bundled with Python — no extra dependency.

2. **Experiment context:** Set once at launch. The menu remembers the current experiment across all commands. A menu option allows switching experiments. Direct CLI commands still take `--experiment/-e` explicitly.

3. **External GUI blocking:** Blocking. When launching napari, Cellpose, or ImageJ, PerCell 3 waits for the tool to close before returning to the menu. Simpler flow — user finishes in the GUI, then returns to PerCell 3.

## References

- CLI spec: `docs/07-cli/spec.md`
- CLI conventions: `docs/07-cli/CLAUDE.md`
- CLI acceptance tests: `docs/07-cli/acceptance-tests.md`
- PerCell 2 migration: `docs/00-overview/migration-from-v2.md`
- ADR-005 (Click): `docs/tracking/decisions-log.md`
