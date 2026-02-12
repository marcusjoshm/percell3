# Module 2: IO — Acceptance Tests

## Test 1: LIF import metadata preview

```python
def test_lif_read_metadata(sample_lif_path):
    reader = LifReader()
    assert reader.can_read(sample_lif_path)
    meta = reader.read_metadata(sample_lif_path)
    assert meta.format == "lif"
    assert meta.series_count > 0
    assert len(meta.channel_names) > 0
    assert meta.pixel_size_um > 0
```

## Test 2: LIF import into ExperimentStore

```python
def test_lif_import(sample_lif_path, tmp_path):
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        reader = LifReader()
        result = reader.import_into(sample_lif_path, store, condition="control")

        assert result.regions_imported > 0
        assert result.channels_registered > 0
        assert len(store.get_channels()) > 0
        assert len(store.get_regions(condition="control")) == result.regions_imported

        # Verify pixel data round-trips
        regions = store.get_regions(condition="control")
        channels = store.get_channels()
        img = store.read_image_numpy(regions[0].name, "control", channels[0].name)
        assert img.ndim == 2  # Single-channel 2D
        assert img.dtype in (np.uint8, np.uint16)
```

## Test 3: TIFF directory import

```python
def test_tiff_directory_import(tiff_dir, tmp_path):
    """tiff_dir fixture creates a PerCell 2-style directory."""
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        reader = TiffDirectoryReader()
        assert reader.can_read(tiff_dir)
        result = reader.import_into(tiff_dir, store)

        assert result.regions_imported >= 1
        assert "DAPI" in [ch.name for ch in store.get_channels()]
```

## Test 4: Channel name mapping

```python
def test_channel_mapping(sample_lif_path, tmp_path):
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        reader = LifReader()
        reader.import_into(sample_lif_path, store,
                          channel_mapping={"Channel_0": "DAPI", "Channel_1": "GFP"})

        channel_names = [ch.name for ch in store.get_channels()]
        assert "DAPI" in channel_names
        assert "Channel_0" not in channel_names
```

## Test 5: Idempotent import

```python
def test_reimport_no_duplicates(sample_lif_path, tmp_path):
    with ExperimentStore.create(tmp_path / "test.percell") as store:
        reader = LifReader()
        result1 = reader.import_into(sample_lif_path, store, condition="control")
        result2 = reader.import_into(sample_lif_path, store, condition="control")
        # Second import should detect existing data
        assert result2.warnings  # Should warn about existing data
```

## Test 6: Bit depth handling

```python
def test_8bit_tiff_import(tmp_path):
    """8-bit TIFF should be stored as uint8."""
    tiff_path = tmp_path / "8bit.tif"
    data = np.random.randint(0, 255, (256, 256), dtype=np.uint8)
    tifffile.imwrite(str(tiff_path), data)

    # ... import and verify dtype preserved ...

def test_16bit_tiff_import(tmp_path):
    """16-bit TIFF should be stored as uint16."""
    tiff_path = tmp_path / "16bit.tif"
    data = np.random.randint(0, 65535, (256, 256), dtype=np.uint16)
    tifffile.imwrite(str(tiff_path), data)

    # ... import and verify dtype preserved ...
```
