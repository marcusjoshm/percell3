"""Tests for ThresholdBGSubtractionPlugin — integration with ExperimentStore.

Uses the two-FOV workflow: histogram FOV (dilute-phase) provides background
estimate, apply FOV (full image) receives the subtraction.
"""

from __future__ import annotations

import numpy as np
import pytest

from percell3.core import ExperimentStore
from percell3.plugins.builtin.threshold_bg_subtraction import (
    ThresholdBGSubtractionPlugin,
)


@pytest.fixture
def bg_sub_experiment(tmp_path):
    """Create an experiment with two FOVs and two channels.

    Layout:
        - 2 channels: ch00, ch01
        - histogram FOV (64x64), condition "dilute" — has threshold mask
        - apply FOV (64x64), condition "control" — no threshold, receives subtraction
        - ch00 on histogram FOV: background ~50 everywhere (dilute-phase)
        - ch00 on apply FOV: background ~150, bright spots ~300 in mask region
        - ch01 on both: uniform ~100
        - 1 threshold layer on histogram FOV covering the ROI
        - bg estimate from masked pixels on histogram FOV → ~50
        - after global subtraction: apply ~100 outside mask, ~250 inside mask
    """
    store = ExperimentStore.create(tmp_path / "bgsub_test.percell")
    store.add_channel("ch00")
    store.add_channel("ch01")
    store.add_condition("dilute")
    store.add_condition("control")

    # Histogram FOV (dilute-phase) — background-level signal everywhere
    hist_fov_id = store.add_fov(
        "dilute", width=64, height=64, pixel_size_um=0.65,
    )

    rng = np.random.default_rng(42)
    hist_image = rng.normal(loc=50, scale=5, size=(64, 64)).clip(10, 300)
    hist_image = hist_image.astype(np.uint16)
    store.write_image(hist_fov_id, "ch00", hist_image)
    store.write_image(
        hist_fov_id, "ch01",
        np.full((64, 64), 100, dtype=np.uint16),
    )

    # Apply FOV (full image) — bright spots in the ROI region
    apply_fov_id = store.add_fov(
        "control", width=64, height=64, pixel_size_um=0.65,
    )

    apply_image = np.full((64, 64), 150, dtype=np.uint16)
    apply_image[20:40, 20:40] = 300  # bright signal in ROI
    store.write_image(apply_fov_id, "ch00", apply_image)
    store.write_image(
        apply_fov_id, "ch01",
        np.full((64, 64), 100, dtype=np.uint16),
    )

    # Create a threshold on the histogram FOV
    threshold_id = store.add_threshold(
        name="threshold_g1",
        method="otsu",
        width=64,
        height=64,
        source_fov_id=hist_fov_id,
        source_channel="ch00",
    )

    # Write mask: 255 in ROI, 0 elsewhere
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    store.write_mask(mask, threshold_id)

    yield store, hist_fov_id, apply_fov_id, threshold_id
    store.close()


def _make_pairings(hist_fov_id: int, apply_fov_id: int) -> list[dict[str, int]]:
    return [{"histogram_fov_id": hist_fov_id, "apply_fov_id": apply_fov_id}]


class TestPluginMetadata:
    """Tests for plugin info and discovery."""

    def test_info_name(self) -> None:
        plugin = ThresholdBGSubtractionPlugin()
        assert plugin.info().name == "threshold_bg_subtraction"

    def test_info_version(self) -> None:
        plugin = ThresholdBGSubtractionPlugin()
        assert plugin.info().version == "2.0.0"

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
        store, _, _, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()
        errors = plugin.validate(store)
        assert errors == []


class TestRun:
    """Tests for plugin execution."""

    def test_creates_derived_fov(self, bg_sub_experiment) -> None:
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        all_fovs = store.get_fovs()
        derived_fovs = [f for f in all_fovs if "bgsub" in f.display_name]
        assert len(derived_fovs) == 1
        assert "threshold_g1" in derived_fovs[0].display_name
        assert "ch00" in derived_fovs[0].display_name

    def test_derived_fov_named_from_apply_fov(self, bg_sub_experiment) -> None:
        """Derived FOV name should be based on the APPLY FOV, not histogram."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        apply_fov = store.get_fov_by_id(apply_fov_id)
        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]
        assert derived.display_name.startswith(apply_fov.display_name)

    def test_derived_fov_inherits_apply_metadata(self, bg_sub_experiment) -> None:
        """Derived FOV metadata should come from the APPLY FOV."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        apply_fov = store.get_fov_by_id(apply_fov_id)
        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]

        assert derived.condition == apply_fov.condition
        assert derived.bio_rep == apply_fov.bio_rep
        assert derived.width == apply_fov.width
        assert derived.height == apply_fov.height
        assert derived.pixel_size_um == apply_fov.pixel_size_um

    def test_derived_fov_has_all_channels(self, bg_sub_experiment) -> None:
        """Derived FOV should have ALL channels from the apply FOV."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]

        # Both channels should exist
        ch00_image = store.read_image_numpy(derived.id, "ch00")
        ch01_image = store.read_image_numpy(derived.id, "ch01")
        assert ch00_image is not None
        assert ch01_image is not None

        # ch01 should be a copy of apply FOV's ch01
        apply_ch01 = store.read_image_numpy(apply_fov_id, "ch01")
        np.testing.assert_array_equal(ch01_image, apply_ch01)

    def test_derived_fov_inherits_fov_config(self, bg_sub_experiment) -> None:
        """Derived FOV should inherit fov_config entries from apply FOV."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]
        derived_config = store.get_fov_config(derived.id)

        # Apply FOV has at least a whole_field segmentation config entry
        apply_config = store.get_fov_config(apply_fov_id)

        # Derived should have at least as many entries as apply
        assert len(derived_config) >= len(apply_config)

    def test_derived_image_uses_apply_fov(self, bg_sub_experiment) -> None:
        """Background estimated from histogram FOV, subtracted from apply FOV."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]
        derived_image = store.read_image_numpy(derived.id, "ch00")
        apply_image = store.read_image_numpy(apply_fov_id, "ch00")

        # Background subtracted globally — all pixels should be <= apply
        assert np.all(derived_image <= apply_image)

        # Pixels outside mask should also be subtracted (not zeroed)
        assert np.any(derived_image[:20, :] > 0)
        assert np.any(derived_image[40:, :] > 0)

    def test_no_underflow_on_uint16(self, bg_sub_experiment) -> None:
        """Subtraction should not produce underflow artifacts."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name][0]
        derived_image = store.read_image_numpy(derived.id, "ch00")

        # No values should be > 65000 (underflow would produce ~65535)
        assert np.all(derived_image < 60000)
        assert derived_image.dtype == np.uint16

    def test_idempotent_rerun(self, bg_sub_experiment) -> None:
        """Running twice should reuse the derived FOV, not create a duplicate."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()
        params = {
            "channel": "ch00",
            "pairings": _make_pairings(hist_fov_id, apply_fov_id),
        }

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
        store.add_condition("dilute")
        store.add_condition("control")

        hist_fov_id = store.add_fov("dilute", width=32, height=32)
        apply_fov_id = store.add_fov("control", width=32, height=32)

        image = np.full((32, 32), 100, dtype=np.uint16)
        store.write_image(hist_fov_id, "ch00", image)
        store.write_image(apply_fov_id, "ch00", image)

        threshold_id = store.add_threshold(
            name="t1", method="otsu", width=32, height=32,
            source_fov_id=hist_fov_id, source_channel="ch00",
        )
        empty_mask = np.zeros((32, 32), dtype=np.uint8)
        store.write_mask(empty_mask, threshold_id)

        plugin = ThresholdBGSubtractionPlugin()
        result = plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        assert len(result.warnings) > 0
        assert any(
            "no non-zero" in w.lower() or "no valid" in w.lower()
            for w in result.warnings
        )

        # No derived FOV should be created
        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name]
        assert len(derived) == 0

        store.close()

    def test_histogram_png_saved(self, bg_sub_experiment) -> None:
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        result = plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        histograms_dir = result.custom_outputs.get("histograms_dir")
        assert histograms_dir is not None

        from pathlib import Path
        hist_path = Path(histograms_dir)
        assert hist_path.exists()
        png_files = list(hist_path.glob("*.png"))
        assert len(png_files) == 1

    def test_progress_callback(self, bg_sub_experiment) -> None:
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        progress_calls = []

        def on_progress(current, total, msg):
            progress_calls.append((current, total, msg))

        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
            progress_callback=on_progress,
        )

        assert len(progress_calls) > 0

    def test_derived_fov_can_be_deleted(self, bg_sub_experiment) -> None:
        """Derived FOVs should be deletable without errors."""
        store, hist_fov_id, apply_fov_id, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()
        plugin.run(
            store,
            parameters={
                "channel": "ch00",
                "pairings": _make_pairings(hist_fov_id, apply_fov_id),
            },
        )

        derived = [f for f in store.get_fovs() if "bgsub" in f.display_name]
        assert len(derived) == 1

        store.delete_fov(derived[0].id)
        remaining = [f for f in store.get_fovs() if "bgsub" in f.display_name]
        assert len(remaining) == 0

    def test_requires_parameters(self, bg_sub_experiment) -> None:
        store, _, _, _ = bg_sub_experiment
        plugin = ThresholdBGSubtractionPlugin()

        with pytest.raises(RuntimeError, match="Parameters are required"):
            plugin.run(store)
