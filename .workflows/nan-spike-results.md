# NaN Spike Results

**Date:** 2026-03-10
**Verdict: GO** — NaN-based single-derived-FOV approach is feasible with documented mitigations.

## Test Summary

53 tests, all passing. Test file: `tests/test_nan_spike.py`

## Findings by Category

### 1. Core NaN-safe Metrics — PASS

All `np.nan*` functions work correctly with mixed NaN/valid pixel arrays:
- `np.nanmean`, `np.nanmax`, `np.nanmin`, `np.nanstd`, `np.nanmedian` — correct results
- `np.nansum` — correct for integrated intensity
- PerCell3's `MetricRegistry` already uses `np.nan*` variants — no changes needed for 5 of 7 metrics

### 2. Area Calculation — REQUIRES FIX

**Current bug:** `area()` uses `np.sum(mask)` which counts all mask pixels including NaN regions.
**Fix:** For derived FOVs, use `np.sum(mask & ~np.isnan(image))` to exclude NaN pixels.

### 3. All-NaN Edge Case — REQUIRES HANDLING

- `np.nanmean`, `np.nanstd`, `np.nanmedian` — return NaN (with RuntimeWarning)
- `np.nanmax`, `np.nanmin` — **NumPy 2.x:** return NaN with RuntimeWarning (not ValueError as in NumPy 1.x)
- `np.nansum` — returns 0.0 (surprising but per NumPy docs)
- **Mitigation:** Suppress RuntimeWarning in measurement code; NaN results propagate naturally

### 4. Zarr NaN Preservation — PASS

- float32 and float64 NaN values round-trip correctly through Zarr
- CYX (multi-channel) layout preserves NaN per-channel
- **CRITICAL:** Default `fill_value` is 0.0, not NaN. Derived FOVs MUST set `fill_value=float('nan')`
- Compression with Blosc/LZ4 works without issues

### 5. CSV Export — PASS

- pandas writes NaN as empty string in CSV
- pandas reads empty cells back as NaN
- Round-trip is lossless

### 6. scipy.ndimage.label — CRITICAL, REQUIRES FIX

**NaN is treated as foreground (non-zero).** This silently connects disconnected regions through NaN "bridges."
- Full NaN background + 2 blobs → labeled as 1 connected region (WRONG)
- **Fix:** Replace NaN with 0 before labeling: `img[np.isnan(img)] = 0`
- **Alternative:** Use boolean mask: `(~np.isnan(img)) & (img > 0)`

### 7. skimage.regionprops — REQUIRES MITIGATION

- `intensity_mean` uses `np.mean` (not `np.nanmean`) — propagates NaN
- **Mitigation:** Use PerCell3's own `MetricRegistry` (already NaN-safe), not regionprops for measurements

### 8. SQLite NaN Round-trip — REQUIRES SCHEMA CHANGE

**Python sqlite3 converts `float('nan')` to NULL on storage.**
- NaN does NOT survive round-trip as a REAL value
- NaN passes the `NOT NULL` constraint (stored as NULL, but constraint checks the binding, not the stored value — platform-dependent)
- **Fix:** Change `value REAL NOT NULL` to `value REAL` (nullable) in measurements table
- Use NULL ↔ NaN conversion at the application layer
- Benefit: SQLite `AVG()` correctly ignores NULL values

### 9. Performance Benchmarks

**np.nanmean on 2048x2048 images (10 iterations):**

| NaN fraction | np.mean | np.nanmean | Slowdown |
|---|---|---|---|
| 0% | 2.9 ms | 7.2 ms | 2.5x |
| 50% | 3.1 ms | 22.2 ms | 7.1x |
| 95% | 2.9 ms | 10.3 ms | 3.5x |

**All 7 metrics on 512x512 (50 iterations):**

| NaN fraction | Time |
|---|---|
| 0% | 4.5 ms |
| 50% | 8.1 ms |
| 95% | 3.8 ms |

**Zarr compression (2048x2048, 75% outside-ROI):**
- NaN-outside: 3516 KB
- Zero-outside: 3517 KB
- **Ratio: 1.00x** — No compression penalty for NaN vs zero

**Verdict:** Performance impact is acceptable. Worst case is ~7x slowdown for nanmean at 50% NaN density on 2048x2048, but absolute time (22 ms) is negligible in the pipeline.

## Required Changes for PerCell4

1. **`area()` metric:** Add NaN-aware variant using `mask & ~np.isnan(image)`
2. **`scipy.ndimage.label` calls:** Replace NaN with 0 before labeling
3. **Schema `measurements.value`:** Change from `REAL NOT NULL` to `REAL` (nullable)
4. **Zarr derived FOVs:** Always set `fill_value=float('nan')` and `dtype=np.float32`
5. **Application layer:** Add NULL ↔ NaN conversion for SQLite reads/writes
6. **Do NOT use `regionprops.intensity_mean`** — use PerCell3's `MetricRegistry` instead

## Fallback Assessment

The multi-derived-FOV fallback is NOT needed. All NaN issues have straightforward mitigations:
- No crashes (NumPy 2.x returns NaN instead of ValueError)
- Zarr compression is unaffected
- SQLite NULL-as-NaN is a clean pattern
- scipy.ndimage.label fix is a one-liner
