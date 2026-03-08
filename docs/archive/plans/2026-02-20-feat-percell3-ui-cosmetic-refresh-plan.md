---
title: "feat: PerCell 3 UI cosmetic refresh to match original PerCell"
type: feat
date: 2026-02-20
---

# PerCell 3 UI Cosmetic Refresh

## Overview

Update PerCell 3's terminal UI to visually match the original PerCell app's distinctive look: ASCII art banner with green/magenta coloring, welcome message, and styled menu header. These are purely cosmetic changes to `menu.py` — no functionality changes.

## Problem Statement

PerCell 3's current menu header is plain text:
```
PerCell 3 — Single-Cell Microscopy Analysis

  Experiment: PerCell3 Test (/path/to/exp)

  [1] Create experiment
  [2] Import images
  ...
```

The original PerCell has a recognizable ASCII art banner with per-character coloring (green for "PER", magenta for "CELL"), a welcome message with microscope emoji, and a "MAIN MENU:" section header. Users should see the same branding in PerCell 3.

## Files to modify

| File | Changes |
|------|---------|
| `src/percell3/cli/menu.py` | Replace `_show_header()` with ASCII banner + welcome message, add "MAIN MENU:" label above items |

**Only one file changes.** This is purely cosmetic.

## Implementation

### 1. Replace `_show_header()` in `menu.py`

Replace the current header (lines 284-292) with an ASCII art banner using Rich markup for coloring.

**Current:**
```python
def _show_header(state: MenuState) -> None:
    console.print("\n[bold]PerCell 3[/bold] — Single-Cell Microscopy Analysis\n")
    if state.experiment_path:
        ...
```

**New:**
```python
_BANNER_LINES = [
    "          ███████╗ ████████╗███████╗ ███████╗████████╗██╗      ██╗              ",
    "          ██╔═══██╗██╔═════╝██╔═══██╗██╔════╝██╔═════╝██║      ██║              ",
    "          ███████╔╝███████╗ ███████╔╝██║     ███████╗ ██║      ██║              ",
    "          ██╔════╝ ██╔════╝ ██╔═══██╗██║     ██╔════╝ ██║      ██║              ",
    "          ██║      ████████╗██║   ██║███████╗████████╗████████╗████████╗        ",
    "          ╚═╝      ╚═══════╝╚═╝   ╚═╝╚══════╝╚═══════╝╚═══════╝╚═══════╝        ",
]


def _colorize_banner_line(line: str) -> str:
    """Color a banner line: green for PER (cols 1-35), magenta for CELL (cols 36-80)."""
    parts = []
    for j, char in enumerate(line):
        if char == " ":
            parts.append(char)
        elif 1 <= j <= 35:
            parts.append(f"[green]{char}[/green]")
        elif 36 <= j <= 80:
            parts.append(f"[magenta]{char}[/magenta]")
        else:
            parts.append(char)
    return "".join(parts)


def _show_header(state: MenuState) -> None:
    """Display the ASCII art banner, welcome message, and experiment context."""
    console.print()
    for line in _BANNER_LINES:
        console.print(_colorize_banner_line(line))
    console.print()
    console.print("[bold]              🔬 Welcome to PerCell 3 — Single-Cell Microscopy Analysis 🔬[/bold]")
    console.print()
    if state.experiment_path:
        name = state.store.name if state.store else ""
        label = f"{name} ({state.experiment_path})" if name else str(state.experiment_path)
        console.print(f"  Experiment: [cyan]{label}[/cyan]\n")
    else:
        console.print("  Experiment: [dim]None selected[/dim]\n")
```

**Note on coloring approach:** The original PerCell uses raw ANSI codes with per-character `colorize()` calls. PerCell 3 uses Rich markup. Rather than wrapping every single character, we group runs of non-space characters in the same color zone. Spaces are left uncolored to avoid markup overhead. The visual result is identical.

### 2. Keep `_show_menu()` as-is

The current PerCell 3 menu format (`  [key] Label`) is cleaner than the original's (`1. Title - Description`) and already works well with Rich. No changes needed here — the banner alone creates the visual identity match.

### 3. No new dependencies

The ASCII art and coloring use Rich markup already available in the project. No new imports or packages needed.

## Verification

- [ ] `pytest tests/test_cli/ -v` — no regressions
- [ ] Manual: `percell3` shows colored ASCII banner with green "PER" and magenta "CELL"
- [ ] Manual: Welcome message with microscope emoji appears below banner
- [ ] Manual: Experiment context still displays correctly below welcome message
- [ ] Manual: Menu items render correctly below the header
