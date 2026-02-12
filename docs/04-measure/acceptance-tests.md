# Module 4: Measure — Acceptance Tests

## Test 1: Measure mean intensity

```python
def test_measure_mean_intensity(experiment_with_cells):
    """Measure GFP mean intensity using DAPI segmentation boundaries."""
    store = experiment_with_cells  # Has DAPI/GFP images + cells from DAPI segmentation

    measurer = Measurer(store)
    count = measurer.measure_region("region_1", "control",
                                    channels=["GFP"],
                                    metrics=["mean_intensity"])
    assert count > 0

    df = store.get_measurements(channels=["GFP"], metrics=["mean_intensity"])
    assert len(df) == store.get_cell_count()
    assert all(df["value"] >= 0)
```

## Test 2: Measure multiple channels independently

```python
def test_measure_multiple_channels(experiment_with_cells):
    """Key PerCell 3 feature: measure GFP and RFP using same DAPI segmentation."""
    store = experiment_with_cells
    measurer = Measurer(store)

    measurer.measure_region("region_1", "control", channels=["GFP", "RFP"])

    pivot = store.get_measurement_pivot()
    assert "GFP_mean_intensity" in pivot.columns
    assert "RFP_mean_intensity" in pivot.columns
    assert len(pivot) == store.get_cell_count()
```

## Test 3: All built-in metrics compute correctly

```python
def test_all_metrics_on_known_image():
    """Verify metric computations on a synthetic image with known values."""
    image = np.array([[10, 20], [30, 40]], dtype=np.uint16)
    mask = np.array([[True, True], [True, True]])

    registry = MetricRegistry()
    assert registry.compute("mean_intensity", image, mask) == 25.0
    assert registry.compute("max_intensity", image, mask) == 40.0
    assert registry.compute("min_intensity", image, mask) == 10.0
    assert registry.compute("integrated_intensity", image, mask) == 100.0
```

## Test 4: Otsu thresholding

```python
def test_otsu_threshold(experiment_with_images):
    store = experiment_with_images
    engine = ThresholdEngine()

    result = engine.threshold_region(store, "region_1", "control", "GFP",
                                     method="otsu")

    assert result.threshold_value > 0
    assert 0 < result.positive_fraction < 1

    # Mask should be stored in masks.zarr
    mask = store.read_mask("region_1", "control", "GFP",
                           threshold_run_id=result.threshold_run_id)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 255})
```

## Test 5: Manual thresholding

```python
def test_manual_threshold(experiment_with_images):
    store = experiment_with_images
    engine = ThresholdEngine()

    result = engine.threshold_region(store, "region_1", "control", "GFP",
                                     method="manual", manual_value=1000)
    assert result.threshold_value == 1000
```

## Test 6: Batch measurement

```python
def test_batch_measure(experiment_with_cells_multi_region):
    store = experiment_with_cells_multi_region
    batch = BatchMeasurer()

    result = batch.measure_experiment(store, channels=["GFP", "RFP"])
    assert result.total_measurements > 0
    assert result.channels_measured == 2

    pivot = store.get_measurement_pivot()
    assert len(pivot) == store.get_cell_count()
```

## Test 7: Positive/negative classification

```python
def test_cell_classification(experiment_with_cells_and_threshold):
    store = experiment_with_cells_and_threshold
    measurer = Measurer(store)

    classified = measurer.classify_cells(store, channel="GFP")
    assert classified == store.get_cell_count()

    df = store.get_measurements(metrics=["positive_fraction"])
    assert all(0 <= v <= 1 for v in df["value"])
```
