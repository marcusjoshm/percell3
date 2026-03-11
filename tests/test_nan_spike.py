"""NaN Spike — Validate NaN pixel behavior through the full pipeline.

This test suite validates that PerCell4's single-derived-FOV approach
(NaN outside ROI) works correctly with all downstream operations:
measurement metrics, Zarr I/O, SQLite storage, scipy/skimage labeling,
CSV export, and performance benchmarks.

Gate target: validates threshold_bg_subtraction redesign feasibility.
"""

from __future__ import annotations

import math
import sqlite3
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr
from numcodecs import Blosc
from scipy import ndimage
from skimage import measure


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def image_with_nans():
    """Create a 512x512 float32 image with known values inside two ROIs,
    NaN everywhere else.

    ROI 1: rows 50-149, cols 50-149 (100x100), all pixels = 10.0
    ROI 2: rows 300-399, cols 300-399 (100x100), all pixels = 20.0
    Everything else: NaN
    """
    img = np.full((512, 512), np.nan, dtype=np.float32)
    img[50:150, 50:150] = 10.0
    img[300:400, 300:400] = 20.0
    return img


@pytest.fixture
def roi_mask_1():
    """Boolean mask for ROI 1 (rows 50-149, cols 50-149)."""
    mask = np.zeros((512, 512), dtype=bool)
    mask[50:150, 50:150] = True
    return mask


@pytest.fixture
def roi_mask_2():
    """Boolean mask for ROI 2 (rows 300-399, cols 300-399)."""
    mask = np.zeros((512, 512), dtype=bool)
    mask[300:400, 300:400] = True
    return mask


@pytest.fixture
def all_nan_mask():
    """Boolean mask covering a region that is entirely NaN."""
    mask = np.zeros((512, 512), dtype=bool)
    mask[200:250, 200:250] = True  # 50x50 region in the NaN zone
    return mask


@pytest.fixture
def border_mask():
    """Boolean mask for an ROI at the image border, partially outside."""
    mask = np.zeros((512, 512), dtype=bool)
    mask[0:30, 0:30] = True  # top-left corner, fully NaN region
    return mask


@pytest.fixture
def tmp_zarr_path(tmp_path):
    """Temporary Zarr store path."""
    return tmp_path / "test.zarr"


@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test.db"


# ---------------------------------------------------------------------------
# 1. Core NaN-safe measurement metrics
# ---------------------------------------------------------------------------


class TestNanSafeMetrics:
    """Verify np.nan* functions produce correct results with NaN pixels."""

    def test_nanmean_roi1(self, image_with_nans, roi_mask_1):
        pixels = image_with_nans[roi_mask_1]
        result = float(np.nanmean(pixels))
        assert result == pytest.approx(10.0)

    def test_nanmean_roi2(self, image_with_nans, roi_mask_2):
        pixels = image_with_nans[roi_mask_2]
        result = float(np.nanmean(pixels))
        assert result == pytest.approx(20.0)

    def test_nanmax(self, image_with_nans, roi_mask_1):
        result = float(np.nanmax(image_with_nans[roi_mask_1]))
        assert result == pytest.approx(10.0)

    def test_nanmin(self, image_with_nans, roi_mask_1):
        result = float(np.nanmin(image_with_nans[roi_mask_1]))
        assert result == pytest.approx(10.0)

    def test_nanstd_uniform(self, image_with_nans, roi_mask_1):
        """Uniform ROI should have std = 0."""
        result = float(np.nanstd(image_with_nans[roi_mask_1]))
        assert result == pytest.approx(0.0)

    def test_nanstd_mixed(self, image_with_nans):
        """ROI spanning both value regions and NaN should compute correctly."""
        # Create a mask that covers parts of ROI1 and some NaN
        mask = np.zeros((512, 512), dtype=bool)
        mask[50:150, 50:150] = True  # all 10.0
        # Add a few pixels of different value
        img = image_with_nans.copy()
        img[50, 50] = 20.0
        pixels = img[mask]
        result = float(np.nanstd(pixels))
        assert result > 0.0  # should not be zero since we changed one pixel

    def test_nanmedian(self, image_with_nans, roi_mask_1):
        result = float(np.nanmedian(image_with_nans[roi_mask_1]))
        assert result == pytest.approx(10.0)

    def test_nansum_integrated_intensity(self, image_with_nans, roi_mask_1):
        """Integrated intensity = sum of non-NaN pixels."""
        result = float(np.nansum(image_with_nans[roi_mask_1]))
        # 100x100 pixels * 10.0 = 100000.0
        assert result == pytest.approx(100_000.0)

    def test_nansum_roi2(self, image_with_nans, roi_mask_2):
        result = float(np.nansum(image_with_nans[roi_mask_2]))
        # 100x100 pixels * 20.0 = 200000.0
        assert result == pytest.approx(200_000.0)


# ---------------------------------------------------------------------------
# 2. Area calculation with NaN exclusion
# ---------------------------------------------------------------------------


class TestAreaWithNaN:
    """Verify area calculation excludes NaN pixels."""

    def test_naive_area_counts_all_mask_pixels(self, image_with_nans, roi_mask_1):
        """np.sum(mask) counts ALL mask pixels regardless of NaN — this is the
        current behavior that needs fixing for derived FOVs."""
        naive_area = float(np.sum(roi_mask_1))
        assert naive_area == 10_000.0  # 100x100

    def test_nan_safe_area_excludes_nan(self, image_with_nans):
        """Area should use mask & ~np.isnan(image) for derived FOVs."""
        # Create a mask that covers ROI1 (valid) + some NaN region
        mask = np.zeros((512, 512), dtype=bool)
        mask[50:150, 50:150] = True   # 10000 valid pixels
        mask[200:210, 200:210] = True  # 100 NaN pixels

        naive_area = float(np.sum(mask))
        assert naive_area == 10_100.0  # counts NaN region too

        nan_safe_area = float(np.sum(mask & ~np.isnan(image_with_nans)))
        assert nan_safe_area == 10_000.0  # correctly excludes NaN

    def test_nan_safe_area_all_valid(self, image_with_nans, roi_mask_1):
        """When no NaN pixels in mask, nan-safe area equals naive area."""
        nan_safe = float(np.sum(roi_mask_1 & ~np.isnan(image_with_nans)))
        naive = float(np.sum(roi_mask_1))
        assert nan_safe == naive == 10_000.0


# ---------------------------------------------------------------------------
# 3. Edge case: All pixels NaN
# ---------------------------------------------------------------------------


class TestAllNaNEdgeCase:
    """Test behavior when all pixels under the mask are NaN."""

    def test_nanmean_all_nan_returns_nan(self, image_with_nans, all_nan_mask):
        """np.nanmean of all-NaN slice returns NaN (with RuntimeWarning)."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = float(np.nanmean(image_with_nans[all_nan_mask]))
        assert math.isnan(result)

    def test_nanmax_all_nan_returns_nan_with_warning(self, image_with_nans, all_nan_mask):
        """np.nanmax on all-NaN slice: NumPy 2.x returns NaN with RuntimeWarning
        (NumPy 1.x raised ValueError). Must handle both cases."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = float(np.nanmax(image_with_nans[all_nan_mask]))
        assert math.isnan(result)

    def test_nanmin_all_nan_returns_nan_with_warning(self, image_with_nans, all_nan_mask):
        """np.nanmin on all-NaN slice: NumPy 2.x returns NaN with RuntimeWarning."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = float(np.nanmin(image_with_nans[all_nan_mask]))
        assert math.isnan(result)

    def test_nanstd_all_nan_returns_nan(self, image_with_nans, all_nan_mask):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = float(np.nanstd(image_with_nans[all_nan_mask]))
        assert math.isnan(result)

    def test_nanmedian_all_nan_returns_nan(self, image_with_nans, all_nan_mask):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = float(np.nanmedian(image_with_nans[all_nan_mask]))
        assert math.isnan(result)

    def test_nansum_all_nan_returns_zero(self, image_with_nans, all_nan_mask):
        """np.nansum of all NaN returns 0.0 — surprising but correct per NumPy docs."""
        result = float(np.nansum(image_with_nans[all_nan_mask]))
        assert result == 0.0

    def test_nan_safe_area_all_nan_returns_zero(self, image_with_nans, all_nan_mask):
        """Area with NaN exclusion should be 0 when all pixels are NaN."""
        area = float(np.sum(all_nan_mask & ~np.isnan(image_with_nans)))
        assert area == 0.0

    def test_safe_wrapper_for_nanmax(self, image_with_nans, all_nan_mask):
        """Demonstrate safe wrapper that handles both NumPy 1.x and 2.x behavior.
        NumPy 1.x: raises ValueError on all-NaN.
        NumPy 2.x: returns NaN with RuntimeWarning."""
        import warnings

        def safe_nanmax(pixels):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    result = float(np.nanmax(pixels))
                except ValueError:
                    result = float("nan")
            return result

        result = safe_nanmax(image_with_nans[all_nan_mask])
        assert math.isnan(result)

        # Works normally for valid pixels
        valid = np.array([1.0, 2.0, np.nan, 3.0])
        assert safe_nanmax(valid) == 3.0


# ---------------------------------------------------------------------------
# 4. Edge case: Border ROI
# ---------------------------------------------------------------------------


class TestBorderROI:
    """Test ROI at image border with NaN pixels."""

    def test_border_roi_all_nan(self, image_with_nans, border_mask):
        """Top-left corner is NaN in our test image. Metrics should handle it."""
        pixels = image_with_nans[border_mask]
        assert np.all(np.isnan(pixels))

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_val = float(np.nanmean(pixels))
        assert math.isnan(mean_val)

    def test_border_roi_partial_valid(self):
        """ROI at border with some valid and some NaN pixels."""
        img = np.full((512, 512), np.nan, dtype=np.float32)
        img[0:20, 0:20] = 5.0  # partially valid at border

        mask = np.zeros((512, 512), dtype=bool)
        mask[0:30, 0:30] = True  # extends beyond valid region

        pixels = img[mask]
        result = float(np.nanmean(pixels))
        assert result == pytest.approx(5.0)

        nan_safe_area = float(np.sum(mask & ~np.isnan(img)))
        assert nan_safe_area == 400.0  # 20x20 valid pixels


# ---------------------------------------------------------------------------
# 5. Zarr read/write NaN preservation
# ---------------------------------------------------------------------------


class TestZarrNaNPreservation:
    """Verify Zarr round-trips NaN values correctly."""

    @pytest.mark.parametrize("dtype", [np.float32, np.float64])
    def test_zarr_nan_roundtrip(self, tmp_zarr_path, dtype):
        """NaN values survive Zarr write/read cycle."""
        img = np.full((512, 512), np.nan, dtype=dtype)
        img[100:200, 100:200] = 42.0

        store = zarr.open(str(tmp_zarr_path), mode="w")
        store.create_dataset(
            "test",
            data=img,
            chunks=(512, 512),
            compressor=Blosc(cname="lz4", clevel=5),
            fill_value=float("nan"),
        )

        # Read back
        store_r = zarr.open(str(tmp_zarr_path), mode="r")
        result = np.array(store_r["test"])

        # Check NaN positions match
        assert np.array_equal(np.isnan(img), np.isnan(result))
        # Check non-NaN values match
        valid = ~np.isnan(img)
        np.testing.assert_array_equal(result[valid], img[valid])

    def test_zarr_default_fill_value_is_zero(self, tmp_zarr_path):
        """CRITICAL: Default fill_value is 0.0, NOT NaN.
        Derived FOVs MUST set fill_value=float('nan')."""
        store = zarr.open(str(tmp_zarr_path), mode="w")
        arr = store.zeros("test", shape=(10, 10), dtype=np.float32)
        assert arr.fill_value == 0.0  # default is 0, not NaN

    def test_zarr_nan_fill_value_explicit(self, tmp_zarr_path):
        """Verify explicit NaN fill_value works."""
        store = zarr.open(str(tmp_zarr_path), mode="w")
        arr = store.create_dataset(
            "test",
            shape=(10, 10),
            dtype=np.float32,
            fill_value=float("nan"),
        )
        assert math.isnan(arr.fill_value)

    def test_zarr_compression_with_nan(self, tmp_zarr_path):
        """Zarr with Blosc compresses NaN-containing arrays without error."""
        img = np.full((512, 512), np.nan, dtype=np.float32)
        img[100:200, 100:200] = 42.0

        store = zarr.open(str(tmp_zarr_path), mode="w")
        store.create_dataset(
            "test",
            data=img,
            chunks=(512, 512),
            compressor=Blosc(cname="lz4", clevel=5),
            fill_value=float("nan"),
        )

        result = np.array(zarr.open(str(tmp_zarr_path), mode="r")["test"])
        valid = ~np.isnan(img)
        np.testing.assert_array_equal(result[valid], img[valid])
        assert np.sum(np.isnan(result)) == np.sum(np.isnan(img))

    def test_zarr_cyx_nan_roundtrip(self, tmp_zarr_path):
        """Test NaN in CYX layout (multi-channel), simulating write_image_channel."""
        num_channels = 3
        h, w = 512, 512

        store = zarr.open(str(tmp_zarr_path), mode="w")
        arr = store.create_dataset(
            "fov_1/0",
            shape=(num_channels, h, w),
            chunks=(1, 512, 512),
            dtype=np.float32,
            compressor=Blosc(cname="lz4", clevel=5),
            fill_value=float("nan"),
        )

        # Channel 0: all valid
        ch0 = np.ones((h, w), dtype=np.float32) * 100.0
        arr[0] = ch0

        # Channel 1: NaN outside ROI (derived FOV pattern)
        ch1 = np.full((h, w), np.nan, dtype=np.float32)
        ch1[50:150, 50:150] = 10.0
        arr[1] = ch1

        # Channel 2: all NaN
        ch2 = np.full((h, w), np.nan, dtype=np.float32)
        arr[2] = ch2

        # Read back
        store_r = zarr.open(str(tmp_zarr_path), mode="r")
        r0 = np.array(store_r["fov_1/0"][0])
        r1 = np.array(store_r["fov_1/0"][1])
        r2 = np.array(store_r["fov_1/0"][2])

        np.testing.assert_array_equal(r0, ch0)
        assert np.sum(np.isnan(r1)) == np.sum(np.isnan(ch1))
        assert np.all(np.isnan(r2))


# ---------------------------------------------------------------------------
# 6. CSV export with NaN
# ---------------------------------------------------------------------------


class TestCSVExportNaN:
    """Verify pandas CSV export handles NaN correctly."""

    def test_csv_nan_values_exported(self, tmp_path):
        """NaN values should appear as empty strings in CSV (pandas default)."""
        df = pd.DataFrame({
            "cell_id": [1, 2, 3],
            "mean_intensity": [10.0, float("nan"), 20.0],
            "area": [100.0, 0.0, 200.0],
        })
        csv_path = tmp_path / "measurements.csv"
        df.to_csv(csv_path, index=False)

        # Read back
        df2 = pd.read_csv(csv_path)
        assert math.isnan(df2.loc[1, "mean_intensity"])
        assert df2.loc[0, "mean_intensity"] == 10.0
        assert df2.loc[2, "mean_intensity"] == 20.0

    def test_csv_nan_read_back_as_nan(self, tmp_path):
        """Pandas reads empty CSV cells as NaN — round-trip works."""
        df = pd.DataFrame({
            "metric": ["mean", "max", "min"],
            "value": [float("nan"), float("nan"), 5.0],
        })
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)

        df2 = pd.read_csv(csv_path)
        assert math.isnan(df2.loc[0, "value"])
        assert math.isnan(df2.loc[1, "value"])
        assert df2.loc[2, "value"] == 5.0


# ---------------------------------------------------------------------------
# 7. scipy.ndimage.label with NaN — CRITICAL
# ---------------------------------------------------------------------------


class TestScipyLabelNaN:
    """CRITICAL: scipy.ndimage.label treats NaN as foreground (non-zero).
    This will silently connect disconnected regions through NaN 'bridges'.
    """

    def test_nan_treated_as_foreground(self):
        """Demonstrate the NaN-as-foreground problem."""
        # Two separate blobs with NaN between them
        img = np.zeros((10, 10), dtype=np.float32)
        img[1:3, 1:3] = 1.0   # blob 1
        img[7:9, 7:9] = 1.0   # blob 2
        img[4:6, 4:6] = np.nan  # NaN region between blobs

        labeled, num_features = ndimage.label(img)

        # With zeros between: should be 3 regions (2 blobs + 1 NaN block)
        # NaN is treated as foreground, so it's counted as a separate region
        # (or merged if adjacent). Key: NaN is NOT ignored.
        assert num_features >= 3  # NaN block is its own "foreground" region

    def test_nan_bridges_connect_blobs(self):
        """NaN pixels connecting two blobs merge them into one region."""
        img = np.zeros((10, 30), dtype=np.float32)
        img[3:7, 2:5] = 1.0    # blob 1
        img[3:7, 25:28] = 1.0  # blob 2
        # NaN bridge connecting them
        img[4:6, 5:25] = np.nan

        labeled, num_features_nan = ndimage.label(img)

        # Now replace NaN with 0 (the fix)
        img_fixed = img.copy()
        img_fixed[np.isnan(img_fixed)] = 0
        labeled_fixed, num_features_fixed = ndimage.label(img_fixed)

        # With NaN bridge: blobs are connected (fewer regions or different labeling)
        # With zeros: blobs are separate
        assert num_features_fixed == 2, "Fixed image should have exactly 2 blobs"
        # NaN bridge makes them connected or adds extra region
        assert num_features_nan != 2, "NaN bridge should not give exactly 2 separate blobs"

    def test_fix_replace_nan_with_zero_before_labeling(self):
        """Demonstrate the correct fix: replace NaN with 0 before labeling."""
        img = np.full((512, 512), np.nan, dtype=np.float32)
        img[50:150, 50:150] = 10.0
        img[300:400, 300:400] = 20.0

        # Wrong: label directly (NaN = foreground)
        _, num_wrong = ndimage.label(img)
        # The entire NaN background is treated as one giant foreground region
        # connecting to both blobs
        assert num_wrong == 1, (
            "With NaN, everything is one connected foreground region"
        )

        # Correct: replace NaN with 0 first
        img_fixed = img.copy()
        img_fixed[np.isnan(img_fixed)] = 0
        _, num_correct = ndimage.label(img_fixed)
        assert num_correct == 2, "After NaN->0, should have exactly 2 separate blobs"

    def test_fix_with_boolean_mask(self):
        """Alternative fix: create binary mask ignoring NaN."""
        img = np.full((512, 512), np.nan, dtype=np.float32)
        img[50:150, 50:150] = 10.0
        img[300:400, 300:400] = 20.0

        # Create mask: non-zero AND not-NaN
        binary = (~np.isnan(img)) & (img > 0)
        labeled, num = ndimage.label(binary)
        assert num == 2


# ---------------------------------------------------------------------------
# 8. skimage.measure.regionprops with NaN
# ---------------------------------------------------------------------------


class TestRegionpropsNaN:
    """skimage.regionprops intensity_mean uses np.mean, not np.nanmean."""

    def test_regionprops_intensity_mean_propagates_nan(self):
        """CRITICAL: regionprops intensity_mean gives NaN if any pixel is NaN."""
        label_img = np.zeros((100, 100), dtype=np.int32)
        label_img[10:30, 10:30] = 1  # region 1

        intensity_img = np.ones((100, 100), dtype=np.float32) * 5.0
        # Add a single NaN pixel inside region 1
        intensity_img[15, 15] = np.nan

        props = measure.regionprops(label_img, intensity_image=intensity_img)
        assert len(props) == 1

        # intensity_mean uses np.mean, which propagates NaN
        mean_val = props[0].intensity_mean
        assert math.isnan(mean_val), (
            "regionprops intensity_mean should return NaN when any pixel is NaN"
        )

    def test_regionprops_with_extra_properties_nanmean(self):
        """Use extra_properties to compute NaN-safe mean with regionprops."""
        label_img = np.zeros((100, 100), dtype=np.int32)
        label_img[10:30, 10:30] = 1

        intensity_img = np.ones((100, 100), dtype=np.float32) * 5.0
        intensity_img[15, 15] = np.nan

        def nan_safe_mean(regionmask, intensity_image):
            pixels = intensity_image[regionmask]
            return float(np.nanmean(pixels))

        props = measure.regionprops(
            label_img,
            intensity_image=intensity_img,
            extra_properties=(nan_safe_mean,),
        )
        assert len(props) == 1
        assert props[0].nan_safe_mean == pytest.approx(5.0)

    def test_percell_metrics_already_nan_safe(self):
        """PerCell3's metrics module already uses np.nanmean etc.
        Confirm this is the right approach (not regionprops)."""
        from percell3.measure.metrics import MetricRegistry

        registry = MetricRegistry()
        img = np.ones((50, 50), dtype=np.float32) * 10.0
        img[5, 5] = np.nan

        mask = np.ones((50, 50), dtype=bool)

        mean_val = registry.compute("mean_intensity", img, mask)
        assert mean_val == pytest.approx(10.0, abs=0.01)
        assert not math.isnan(mean_val)


# ---------------------------------------------------------------------------
# 9. SQLite NaN round-trip
# ---------------------------------------------------------------------------


class TestSQLiteNaN:
    """Test NaN behavior in SQLite REAL columns."""

    def test_nan_stored_as_null_in_sqlite(self, tmp_db_path):
        """FINDING: Python sqlite3 converts float('nan') to NULL on storage.
        This means NaN measurements cannot use NOT NULL columns.
        Must use nullable REAL and convert NULL <-> NaN at the application layer."""
        conn = sqlite3.connect(str(tmp_db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value REAL)")

        # Insert NaN
        conn.execute("INSERT INTO test (id, value) VALUES (1, ?)", (float("nan"),))
        conn.commit()

        # Read back — NaN becomes NULL
        row = conn.execute("SELECT value FROM test WHERE id = 1").fetchone()
        val = row[0]
        assert val is None, (
            f"Expected NULL (NaN->NULL conversion), got {val}. "
            "If this fails, SQLite preserves NaN as IEEE float on this platform."
        )

    def test_nan_with_not_null_constraint(self, tmp_db_path):
        """Test if NaN satisfies NOT NULL constraint.
        Current schema has: value REAL NOT NULL."""
        conn = sqlite3.connect(str(tmp_db_path))
        conn.execute("CREATE TABLE measurements (id INTEGER PRIMARY KEY, value REAL NOT NULL)")

        # Try inserting NaN into NOT NULL column
        try:
            conn.execute("INSERT INTO measurements (id, value) VALUES (1, ?)", (float("nan"),))
            conn.commit()
            nan_passes_not_null = True
        except sqlite3.IntegrityError:
            nan_passes_not_null = False

        if nan_passes_not_null:
            # NaN passes NOT NULL — verify it round-trips
            row = conn.execute("SELECT value FROM measurements WHERE id = 1").fetchone()
            val = row[0]
            if val is None:
                # Stored as NULL despite NOT NULL constraint — unusual
                assert False, "NaN stored as NULL in NOT NULL column — schema conflict"
            else:
                assert math.isnan(val)
        # If NOT NULL rejects NaN, we need nullable columns for derived FOV measurements

    def test_nan_in_where_clause(self, tmp_db_path):
        """NaN comparison behavior in SQL WHERE clauses."""
        conn = sqlite3.connect(str(tmp_db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value REAL)")
        conn.execute("INSERT INTO test (id, value) VALUES (1, ?)", (float("nan"),))
        conn.execute("INSERT INTO test (id, value) VALUES (2, 10.0)")
        conn.commit()

        # NaN comparisons in SQL: NaN != NaN, NaN is not > or < anything
        eq_count = conn.execute("SELECT COUNT(*) FROM test WHERE value = value").fetchone()[0]
        # If NaN is stored: NaN != NaN, so count should be 1 (only the 10.0 row)
        # If NaN is NULL: NULL != NULL, so count should also be 1
        # Document actual behavior
        assert eq_count >= 1  # At least the non-NaN row

    def test_null_as_nan_alternative(self, tmp_db_path):
        """Demonstrate using NULL to represent NaN measurements."""
        conn = sqlite3.connect(str(tmp_db_path))
        conn.execute("CREATE TABLE measurements (id INTEGER PRIMARY KEY, value REAL)")  # nullable

        # Store NaN as NULL
        nan_value = float("nan")
        stored = None if math.isnan(nan_value) else nan_value
        conn.execute("INSERT INTO measurements (id, value) VALUES (1, ?)", (stored,))
        conn.execute("INSERT INTO measurements (id, value) VALUES (2, 10.0)")
        conn.commit()

        # Read back: NULL -> NaN
        rows = conn.execute("SELECT id, value FROM measurements ORDER BY id").fetchall()
        results = []
        for row_id, val in rows:
            results.append((row_id, float("nan") if val is None else val))

        assert math.isnan(results[0][1])
        assert results[1][1] == 10.0

        # AVG ignores NULL (not NaN!) — correct behavior for measurements
        avg = conn.execute("SELECT AVG(value) FROM measurements").fetchone()[0]
        assert avg == 10.0  # NULL excluded from AVG


# ---------------------------------------------------------------------------
# 10. Performance benchmarks
# ---------------------------------------------------------------------------


class TestPerformanceBenchmarks:
    """Benchmark NaN impact on measurement and Zarr operations."""

    @pytest.mark.parametrize("nan_fraction", [0.0, 0.50, 0.95])
    def test_nanmean_performance(self, nan_fraction):
        """Benchmark np.nanmean vs np.mean on images with varying NaN density."""
        rng = np.random.default_rng(42)
        img = rng.random((2048, 2048), dtype=np.float64) * 100.0

        if nan_fraction > 0:
            nan_mask = rng.random((2048, 2048)) < nan_fraction
            img[nan_mask] = np.nan

        mask = np.ones((2048, 2048), dtype=bool)

        # Benchmark np.nanmean
        t0 = time.perf_counter()
        for _ in range(10):
            _ = float(np.nanmean(img[mask]))
        t_nanmean = (time.perf_counter() - t0) / 10

        # Benchmark np.mean (for reference — will give NaN if any NaN)
        t0 = time.perf_counter()
        for _ in range(10):
            _ = float(np.mean(img[mask]))
        t_mean = (time.perf_counter() - t0) / 10

        slowdown = t_nanmean / t_mean if t_mean > 0 else float("inf")

        # Document the slowdown (no hard assertion, just capture data)
        print(f"\nNaN fraction: {nan_fraction:.0%}")
        print(f"  np.mean:    {t_mean*1000:.2f} ms")
        print(f"  np.nanmean: {t_nanmean*1000:.2f} ms")
        print(f"  Slowdown:   {slowdown:.2f}x")

        # Sanity: should complete in reasonable time (< 1 second per call)
        assert t_nanmean < 1.0, f"np.nanmean too slow: {t_nanmean:.3f}s"

    def test_zarr_compression_nan_vs_zero(self, tmp_path):
        """Compare Zarr compressed size: NaN-outside vs zero-outside."""
        rng = np.random.default_rng(42)
        base = rng.random((2048, 2048), dtype=np.float32) * 100.0

        # Version 1: NaN outside ROI
        img_nan = base.copy()
        nan_mask = np.ones((2048, 2048), dtype=bool)
        nan_mask[500:1500, 500:1500] = False  # ROI in center
        img_nan[nan_mask] = np.nan

        zarr_nan = tmp_path / "nan.zarr"
        store = zarr.open(str(zarr_nan), mode="w")
        store.create_dataset(
            "data", data=img_nan, chunks=(512, 512),
            compressor=Blosc(cname="lz4", clevel=5),
            fill_value=float("nan"),
        )

        # Version 2: Zero outside ROI
        img_zero = base.copy()
        img_zero[nan_mask] = 0.0

        zarr_zero = tmp_path / "zero.zarr"
        store = zarr.open(str(zarr_zero), mode="w")
        store.create_dataset(
            "data", data=img_zero, chunks=(512, 512),
            compressor=Blosc(cname="lz4", clevel=5),
        )

        # Compare sizes
        import shutil
        size_nan = sum(f.stat().st_size for f in zarr_nan.rglob("*") if f.is_file())
        size_zero = sum(f.stat().st_size for f in zarr_zero.rglob("*") if f.is_file())

        ratio = size_nan / size_zero if size_zero > 0 else float("inf")
        print(f"\nZarr compression comparison (2048x2048, 75% outside-ROI):")
        print(f"  NaN-outside:  {size_nan / 1024:.1f} KB")
        print(f"  Zero-outside: {size_zero / 1024:.1f} KB")
        print(f"  Ratio (NaN/zero): {ratio:.2f}x")

        # NaN should not be catastrophically worse (< 5x)
        assert ratio < 5.0, f"NaN compression too expensive: {ratio:.2f}x vs zeros"

    @pytest.mark.parametrize("nan_fraction", [0.0, 0.50, 0.95])
    def test_all_seven_metrics_performance(self, nan_fraction):
        """Benchmark all 7 PerCell metrics with NaN."""
        from percell3.measure.metrics import MetricRegistry

        rng = np.random.default_rng(42)
        img = rng.random((512, 512), dtype=np.float32) * 100.0
        mask = np.ones((512, 512), dtype=bool)

        if nan_fraction > 0:
            nan_positions = rng.random((512, 512)) < nan_fraction
            img[nan_positions] = np.nan

        registry = MetricRegistry()

        t0 = time.perf_counter()
        for _ in range(50):
            for metric_name in registry.list_metrics():
                try:
                    registry.compute(metric_name, img, mask)
                except ValueError:
                    pass  # all-NaN for nanmax/nanmin
        elapsed = (time.perf_counter() - t0) / 50

        print(f"\nAll 7 metrics, NaN fraction {nan_fraction:.0%}: {elapsed*1000:.2f} ms")
        # Should be < 500ms for all 7 metrics on 512x512
        assert elapsed < 0.5


# ---------------------------------------------------------------------------
# 11. Integration: Metrics module behavior with NaN images
# ---------------------------------------------------------------------------


class TestMetricsModuleIntegration:
    """Test the existing PerCell3 metrics module with NaN-containing images."""

    def test_area_counts_nan_pixels_bug(self, image_with_nans):
        """Document the bug: current area() counts NaN pixels in mask."""
        from percell3.measure.metrics import area

        # Mask covering ROI1 + NaN region
        mask = np.zeros((512, 512), dtype=bool)
        mask[50:150, 50:150] = True   # 10000 valid pixels
        mask[200:210, 200:210] = True  # 100 NaN pixels

        current_area = area(image_with_nans, mask)
        # BUG: area counts all mask pixels, including NaN regions
        assert current_area == 10_100.0  # includes NaN pixels

        # What it SHOULD be for derived FOVs:
        nan_safe_area = float(np.sum(mask & ~np.isnan(image_with_nans)))
        assert nan_safe_area == 10_000.0

    def test_max_intensity_all_nan_returns_nan(self, image_with_nans, all_nan_mask):
        """max_intensity on all-NaN: returns NaN with RuntimeWarning (NumPy 2.x).
        No crash, but result is NaN — must be handled downstream."""
        import warnings
        from percell3.measure.metrics import max_intensity

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = max_intensity(image_with_nans, all_nan_mask)
        assert math.isnan(result)

    def test_min_intensity_all_nan_returns_nan(self, image_with_nans, all_nan_mask):
        """min_intensity on all-NaN: returns NaN with RuntimeWarning (NumPy 2.x)."""
        import warnings
        from percell3.measure.metrics import min_intensity

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = min_intensity(image_with_nans, all_nan_mask)
        assert math.isnan(result)

    def test_mean_handles_nan_correctly(self, image_with_nans, roi_mask_1):
        """mean_intensity already uses np.nanmean — works correctly."""
        from percell3.measure.metrics import mean_intensity

        result = mean_intensity(image_with_nans, roi_mask_1)
        assert result == pytest.approx(10.0)

    def test_integrated_ignores_nan(self, image_with_nans, roi_mask_1):
        """integrated_intensity uses np.nansum — NaN treated as 0."""
        from percell3.measure.metrics import integrated_intensity

        result = integrated_intensity(image_with_nans, roi_mask_1)
        assert result == pytest.approx(100_000.0)
