"""Tests for the save-on-close SHA-256 change detection logic."""

from __future__ import annotations

import numpy as np

from percell4.viewer._viewer import compute_labels_hash


def test_same_array_produces_same_hash():
    """Identical arrays should produce the same hash."""
    labels = np.array([[1, 2], [3, 0]], dtype=np.int32)
    h1 = compute_labels_hash(labels)
    h2 = compute_labels_hash(labels.copy())
    assert h1 == h2


def test_different_array_produces_different_hash():
    """Different arrays should produce different hashes."""
    a = np.array([[1, 2], [3, 0]], dtype=np.int32)
    b = np.array([[1, 2], [3, 1]], dtype=np.int32)
    assert compute_labels_hash(a) != compute_labels_hash(b)


def test_hash_is_hex_string():
    """Hash should be a hex string (SHA-256 = 64 characters)."""
    labels = np.zeros((10, 10), dtype=np.int32)
    h = compute_labels_hash(labels)
    assert isinstance(h, str)
    assert len(h) == 64
    # Should be valid hex
    int(h, 16)


def test_empty_vs_nonempty():
    """All-zero labels should differ from labels with cells."""
    empty = np.zeros((10, 10), dtype=np.int32)
    with_cell = np.zeros((10, 10), dtype=np.int32)
    with_cell[3:7, 3:7] = 1

    assert compute_labels_hash(empty) != compute_labels_hash(with_cell)


def test_hash_deterministic():
    """Same content on different calls should give same result."""
    rng = np.random.default_rng(42)
    labels = rng.integers(0, 100, size=(50, 50), dtype=np.int32)
    hashes = [compute_labels_hash(labels) for _ in range(5)]
    assert len(set(hashes)) == 1
