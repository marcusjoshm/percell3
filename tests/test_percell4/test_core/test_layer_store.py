"""Tests for LayerStore — Zarr I/O with staging and path validation."""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import dask.array as da
import numpy as np
import pytest
import zarr
from numcodecs import Blosc, Zstd

from percell4.core.exceptions import PathTraversalError
from percell4.core.layer_store import LayerStore


@pytest.fixture
def store(tmp_path: Path) -> LayerStore:
    """Create an initialized LayerStore in a temporary directory."""
    return LayerStore.init_store(tmp_path)


# ------------------------------------------------------------------
# 1. init_store creates directories
# ------------------------------------------------------------------


def test_init_store_creates_directories(tmp_path: Path) -> None:
    """All 4 subdirectories are created by init_store."""
    store = LayerStore.init_store(tmp_path)
    zarr_root = tmp_path / "zarr"
    assert (zarr_root / "images").is_dir()
    assert (zarr_root / "segmentations").is_dir()
    assert (zarr_root / "masks").is_dir()
    assert (zarr_root / ".pending").is_dir()


# ------------------------------------------------------------------
# 2. Image round-trip
# ------------------------------------------------------------------


def test_write_read_image_round_trip(store: LayerStore) -> None:
    """Write 2 channels, read back, arrays match."""
    ch0 = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
    ch1 = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
    store.write_image_channels("abc123", {0: ch0, 1: ch1})

    result0 = store.read_image_channel_numpy("abc123", 0)
    result1 = store.read_image_channel_numpy("abc123", 1)
    np.testing.assert_array_equal(result0, ch0)
    np.testing.assert_array_equal(result1, ch1)


# ------------------------------------------------------------------
# 3. read_image_channel returns dask
# ------------------------------------------------------------------


def test_read_image_channel_returns_dask(store: LayerStore) -> None:
    """read_image_channel returns a dask Array."""
    data = np.ones((32, 32), dtype=np.float32)
    store.write_image_channels("dask_test", {0: data})
    result = store.read_image_channel("dask_test", 0)
    assert isinstance(result, da.Array)
    np.testing.assert_array_equal(result.compute(), data)


# ------------------------------------------------------------------
# 4. read_image_channel_numpy returns ndarray
# ------------------------------------------------------------------


def test_read_image_channel_numpy_returns_ndarray(store: LayerStore) -> None:
    """read_image_channel_numpy returns a numpy ndarray."""
    data = np.ones((32, 32), dtype=np.float32)
    store.write_image_channels("np_test", {0: data})
    result = store.read_image_channel_numpy("np_test", 0)
    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, data)


# ------------------------------------------------------------------
# 5. Label round-trip
# ------------------------------------------------------------------


def test_write_read_labels_round_trip(store: LayerStore) -> None:
    """Write integer labels, read back."""
    labels = np.array([[0, 1, 1], [2, 2, 0], [0, 3, 3]], dtype=np.int32)
    store.write_labels("seg_aaa", "fov_bbb", labels)
    result = store.read_labels("seg_aaa", "fov_bbb")
    np.testing.assert_array_equal(result, labels)


# ------------------------------------------------------------------
# 6. Mask round-trip
# ------------------------------------------------------------------


def test_write_read_mask_round_trip(store: LayerStore) -> None:
    """Write boolean mask, read back."""
    mask = np.array([[True, False], [False, True]])
    store.write_mask("mask_aaa", mask)
    result = store.read_mask("mask_aaa")
    np.testing.assert_array_equal(result, mask)


# ------------------------------------------------------------------
# 7. Staging path used
# ------------------------------------------------------------------


def test_staging_path_used(store: LayerStore, tmp_path: Path) -> None:
    """During write, staging directory is used."""
    staging = store._staging_path("stage_test")
    assert ".pending" in str(staging)
    assert staging == tmp_path / "zarr" / ".pending" / "stage_test"


# ------------------------------------------------------------------
# 8. Commit staging removes pending entry
# ------------------------------------------------------------------


def test_commit_staging_removes_pending(store: LayerStore, tmp_path: Path) -> None:
    """After write, .pending entry is gone."""
    data = np.ones((16, 16), dtype=np.uint16)
    store.write_image_channels("commit_test", {0: data})
    pending = tmp_path / "zarr" / ".pending" / "commit_test"
    assert not pending.exists()
    final = tmp_path / "zarr" / "images" / "commit_test"
    assert final.exists()


# ------------------------------------------------------------------
# 9. delete_path removes directory
# ------------------------------------------------------------------


def test_delete_path_removes_directory(store: LayerStore, tmp_path: Path) -> None:
    """delete_path removes a zarr directory."""
    data = np.ones((16, 16), dtype=np.uint16)
    store.write_image_channels("del_test", {0: data})
    assert (tmp_path / "zarr" / "images" / "del_test").exists()
    store.delete_path("zarr/images/del_test")
    assert not (tmp_path / "zarr" / "images" / "del_test").exists()


# ------------------------------------------------------------------
# 10. delete_path rejects traversal
# ------------------------------------------------------------------


def test_delete_path_rejects_traversal(store: LayerStore) -> None:
    """../../etc raises PathTraversalError."""
    with pytest.raises(PathTraversalError):
        store.delete_path("../../etc")


# ------------------------------------------------------------------
# 11. validate_zarr_group valid
# ------------------------------------------------------------------


def test_validate_zarr_group_valid(store: LayerStore) -> None:
    """Returns True for a written zarr group."""
    data = np.ones((16, 16), dtype=np.uint16)
    store.write_image_channels("valid_test", {0: data})
    assert store.validate_zarr_group("zarr/images/valid_test") is True


# ------------------------------------------------------------------
# 12. validate_zarr_group invalid
# ------------------------------------------------------------------


def test_validate_zarr_group_invalid(store: LayerStore, tmp_path: Path) -> None:
    """Returns False for an empty directory."""
    empty_dir = tmp_path / "zarr" / "images" / "empty"
    empty_dir.mkdir(parents=True)
    assert store.validate_zarr_group("zarr/images/empty") is False


# ------------------------------------------------------------------
# 13. cleanup_pending removes old
# ------------------------------------------------------------------


def test_cleanup_pending_removes_old(store: LayerStore, tmp_path: Path) -> None:
    """Old entries in .pending are cleaned up."""
    old_entry = tmp_path / "zarr" / ".pending" / "old_entry"
    old_entry.mkdir(parents=True)
    # Set mtime to 10 minutes ago
    old_time = time.time() - 600
    os.utime(old_entry, (old_time, old_time))
    removed = store.cleanup_pending(max_age_seconds=300.0)
    assert "old_entry" in removed
    assert not old_entry.exists()


# ------------------------------------------------------------------
# 14. cleanup_pending keeps recent
# ------------------------------------------------------------------


def test_cleanup_pending_keeps_recent(store: LayerStore, tmp_path: Path) -> None:
    """Recent entries in .pending are kept."""
    recent_entry = tmp_path / "zarr" / ".pending" / "recent_entry"
    recent_entry.mkdir(parents=True)
    removed = store.cleanup_pending(max_age_seconds=300.0)
    assert "recent_entry" not in removed
    assert recent_entry.exists()


# ------------------------------------------------------------------
# 15. Image compression is Blosc lz4
# ------------------------------------------------------------------


def test_image_compression_lz4(store: LayerStore, tmp_path: Path) -> None:
    """Verify image compressor is Blosc lz4."""
    data = np.ones((32, 32), dtype=np.uint16)
    store.write_image_channels("comp_test", {0: data})
    arr = zarr.open(str(tmp_path / "zarr" / "images" / "comp_test" / "0"), mode="r")
    assert isinstance(arr.compressor, Blosc)
    assert arr.compressor.cname == "lz4"


# ------------------------------------------------------------------
# 16. Mask compression is Zstd
# ------------------------------------------------------------------


def test_mask_compression_zstd(store: LayerStore, tmp_path: Path) -> None:
    """Verify mask compressor is Zstd."""
    mask = np.array([[True, False], [False, True]])
    store.write_mask("zstd_test", mask)
    arr = zarr.open(
        str(tmp_path / "zarr" / "masks" / "zstd_test" / "mask"), mode="r"
    )
    assert isinstance(arr.compressor, Zstd)


# ------------------------------------------------------------------
# 17. NGFF metadata present
# ------------------------------------------------------------------


def test_ngff_metadata_present(store: LayerStore, tmp_path: Path) -> None:
    """multiscales is present in .zattrs after writing images."""
    data = np.ones((32, 32), dtype=np.uint16)
    store.write_image_channels("ngff_test", {0: data, 1: data})
    group = zarr.open_group(
        str(tmp_path / "zarr" / "images" / "ngff_test"), mode="r"
    )
    assert "multiscales" in group.attrs
    ms = group.attrs["multiscales"]
    assert len(ms) == 1
    assert ms[0]["version"] == "0.4"
    assert len(ms[0]["datasets"]) == 2
    assert ms[0]["datasets"][0]["path"] == "0"
    assert ms[0]["datasets"][1]["path"] == "1"
    assert ms[0]["name"] == "ngff_test"
    axes = ms[0]["axes"]
    assert axes[0]["name"] == "y"
    assert axes[1]["name"] == "x"


# ------------------------------------------------------------------
# 18. Boundary: no sqlite, no uuid imports
# ------------------------------------------------------------------


def test_boundary_no_sqlite_no_uuid(tmp_path: Path) -> None:
    """AST scan of layer_store.py ensures no sqlite3 or uuid imports."""
    layer_store_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "percell4"
        / "core"
        / "layer_store.py"
    )
    source = layer_store_path.read_text()
    tree = ast.parse(source)

    forbidden = {"sqlite3", "uuid"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, (
                    f"layer_store.py imports forbidden module '{alias.name}'"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                top_module = node.module.split(".")[0]
                assert top_module not in forbidden, (
                    f"layer_store.py imports from forbidden module '{node.module}'"
                )
