"""Tests for ThresholdBGSubtractionPlugin — integration with ExperimentStore."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.plugins.builtin.threshold_bg_subtraction import (
    ThresholdBGSubtractionPlugin,
)


@pytest.fixture
def bg_sub_experiment(tmp_path):
    """Create an experiment with a FOV, channel, and threshold layer.

    Layout:
        - 1 channel: ch00
        - 1 FOV (64x64), condition "control"
        - ch00: background ~50, masked region ~200
        - 1 threshold layer with a mask covering part of the image
    """
    store = ExperimentStore.create(tmp_path / "bgsub_test.percell")
    store.add_channel("ch00")
    store.add_condition("control")

    fov_id = store.add_fov("control", width=64, height=64, pixel_size_um=0.65)

    # Create image: background ~50, bright region ~200
    rng = np.random.default_rng(42)
    image = rng.normal(loc=50, scale=5, size=(64, 64)).clip(10, 300)
    image[20:40, 20:40] = rng.normal(loc=200, scale=10, size=(20, 20)).clip(100, 400)
    image = image.astype(np.uint16)
    store.write_image(fov_id, "ch00", image)

    # Create a threshold with a mask covering the bright region
    threshold_id = store.add_threshold(
        name="threshold_g1",
        method="otsu",
        width=64,
        height=64,
        source_fov_id=fov_id,
        source_channel="ch00",
    )

    # Write mask: 255 where bright, 0 elsewhere
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    store.write_mask(mask, threshold_id)

    yield store, fov_id, threshold_id
    store.close()


class TestPluginMetadata:
    """Tests for plugin info and discovery."""

    def test_info_name(self) -> None:
        plugin = ThresholdBGSubtractionPlugin()
        assert plugin.info().name == "threshold_bg_subtraction"

    def test_info_version(self) -> None:
        plugin = ThresholdBGSubtractionPlugin()
        assert plugin.info().version == "1.0.0"

    def test_required_inputs(self) -> None:
        plugin = ThresholdBGSubtractionPlugin()
        inputs = plugin.required_inputs()
        assert len(inputs) == 1
        assert inputs[0].kind.value == "threshold"


class TestValidation:
    """Tests for plugin validation."""

    def test_validate_no_thresholds(self, tmp_path) -> None:
        store = ExperimentStore.create(tmp_path / "empty.percell")
        store.add_channel("ch00")

        plugin = ThresholdBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert len(errors) == 1
        assert "threshold" in errors[0].lower()
        store.close()

    def test_validate_no_channels(self, tmp_path) -> None:
        store = ExperimentStore.create(tmp_path / "no_ch.percell")

        plugin = ThresholdBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert any("channel" in e.lower() for e in errors)
        store.close()

    def test_validate_ok(self, bg_sub_experiment) -> None:
        store, _, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert errors == []


class TestRun:
    """Tests for plugin execution."""

    def test_creates_derived_fov(self, bg_sub_experiment) -> None:
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        result = plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        # Should have created a derived FOV
        all_fovs = store.get_fovs()
        derived_fovs = [f for f in all_fovs if "bgsub" in f.display_name]
        assert len(derived_fovs) == 1
        assert "threshold_g1" in derived_fovs[0].display_name
        assert "ch00" in derived_fovs[0].display_name

    def test_derived_fov_inherits_metadata(self, bg_sub_experiment) -> None:
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        source_fov = store.get_fov_by_id(fov_id)
        all_fovs = store.get_fovs()
        derived = [f for f in all_fovs if "bgsub" in f.display_name][0]

        assert derived.condition == source_fov.condition
        assert derived.bio_rep == source_fov.bio_rep
        assert derived.width == source_fov.width
        assert derived.height == source_fov.height
        assert derived.pixel_size_um == source_fov.pixel_size_um

    def test_derived_image_correct(self, bg_sub_experiment) -> None:
        """Derived image should have background subtracted in masked region."""
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        all_fovs = store.get_fovs()
        derived = [f for f in all_fovs if "bgsub" in f.display_name][0]
        derived_image = store.read_image_numpy(derived.id, "ch00")
        source_image = store.read_image_numpy(fov_id, "ch00")

        # Pixels outside mask should be zero
        assert np.all(derived_image[:20, :] == 0)
        assert np.all(derived_image[40:, :] == 0)
        assert np.all(derived_image[:, :20] == 0)
        assert np.all(derived_image[:, 40:] == 0)

        # Pixels inside mask should be <= source (subtracted)
        mask_region = derived_image[20:40, 20:40]
        source_region = source_image[20:40, 20:40]
        assert np.all(mask_region <= source_region)

    def test_no_underflow_on_uint16(self, bg_sub_experiment) -> None:
        """Subtraction should not produce underflow artifacts."""
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        all_fovs = store.get_fovs()
        derived = [f for f in all_fovs if "bgsub" in f.display_name][0]
        derived_image = store.read_image_numpy(derived.id, "ch00")

        # No values should be > 65000 (underflow would produce ~65535)
        assert np.all(derived_image < 60000)
        # dtype should match source
        assert derived_image.dtype == np.uint16

    def test_idempotent_rerun(self, bg_sub_experiment) -> None:
        """Running twice should reuse the derived FOV, not create a duplicate."""
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()
        params = {"channel": "ch00", "fov_ids": [fov_id]}

        plugin.run(store, parameters=params)
        fovs_after_first = store.get_fovs()

        plugin.run(store, parameters=params)
        fovs_after_second = store.get_fovs()

        derived_first = [f for f in fovs_after_first if "bgsub" in f.display_name]
        derived_second = [f for f in fovs_after_second if "bgsub" in f.display_name]

        assert len(derived_first) == len(derived_second)

    def test_empty_mask_produces_warning(self, tmp_path) -> None:
        """A threshold with an all-zero mask should be skipped with a warning."""
        store = ExperimentStore.create(tmp_path / "empty_mask.percell")
        store.add_channel("ch00")
        store.add_condition("control")
        fov_id = store.add_fov("control", width=32, height=32)

        image = np.full((32, 32), 100, dtype=np.uint16)
        store.write_image(fov_id, "ch00", image)

        threshold_id = store.add_threshold(
            name="t1", method="otsu", width=32, height=32,
            source_fov_id=fov_id, source_channel="ch00",
        )
        empty_mask = np.zeros((32, 32), dtype=np.uint8)
        store.write_mask(empty_mask, threshold_id)

        plugin = ThresholdBGSubtractionPlugin()
        result = plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        assert len(result.warnings) > 0
        assert any("no non-zero" in w.lower() or "no valid" in w.lower() for w in result.warnings)

        # No derived FOV should be created
        all_fovs = store.get_fovs()
        derived = [f for f in all_fovs if "bgsub" in f.display_name]
        assert len(derived) == 0

        store.close()

    def test_histogram_png_saved(self, bg_sub_experiment) -> None:
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        result = plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
        )

        histograms_dir = result.custom_outputs.get("histograms_dir")
        assert histograms_dir is not None

        from pathlib import Path
        hist_path = Path(histograms_dir)
        assert hist_path.exists()
        png_files = list(hist_path.glob("*.png"))
        assert len(png_files) == 1

    def test_progress_callback(self, bg_sub_experiment) -> None:
        store, fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        progress_calls = []

        def on_progress(current, total, msg):
            progress_calls.append((current, total, msg))

        plugin.run(
            store,
            parameters={"channel": "ch00", "fov_ids": [fov_id]},
            progress_callback=on_progress,
        )

        assert len(progress_calls) > 0

    def test_requires_parameters(self, bg_sub_experiment) -> None:
        store, _, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        with pytest.raises(RuntimeError, match="Parameters are required"):
            plugin.run(store)
