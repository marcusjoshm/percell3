"""Recent experiment history — never raises, degrades gracefully."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_RECENT = 10
_CONFIG_DIR = Path("~/.config/percell3").expanduser()
_RECENT_FILE = _CONFIG_DIR / "recent.json"


def load_recent() -> list[str]:
    """Load recent experiment paths, pruning any that no longer exist.

    Returns an empty list on any error (corrupted JSON, permissions, etc.).
    """
    try:
        if not _RECENT_FILE.exists():
            return []
        data = json.loads(_RECENT_FILE.read_text())
        if not isinstance(data, list):
            return []
        # Prune invalid paths eagerly
        valid = [p for p in data if isinstance(p, str) and Path(p).exists()]
        if len(valid) != len(data):
            _save(valid)
        return valid
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load recent experiments: %s", e)
        return []


def add_to_recent(path: str | Path) -> None:
    """Add an experiment path to the front of the recent list."""
    path_str = str(Path(path).resolve())
    try:
        recent = load_recent()
        # Remove if already present, then prepend
        recent = [p for p in recent if p != path_str]
        recent.insert(0, path_str)
        _save(recent[:_MAX_RECENT])
    except OSError as e:
        logger.warning("Failed to save recent experiments: %s", e)


def _save(paths: list[str]) -> None:
    """Atomically write the recent list to disk."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Write to temp file then atomic rename
        fd, tmp = tempfile.mkstemp(dir=_CONFIG_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(paths, f)
            os.replace(tmp, _RECENT_FILE)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        logger.warning("Failed to write recent experiments: %s", e)
