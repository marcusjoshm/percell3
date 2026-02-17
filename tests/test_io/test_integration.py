"""End-to-end integration tests for percell3.io module."""

from pathlib import Path

import numpy as np
import tifffile

from percell3.core import ExperimentStore
from percell3.io import (
    ChannelMapping,
    DiscoveredFile,
    FileScanner,
    ImportEngine,
    ImportPlan,
    ImportResult,
    ScanResult,
    TokenConfig,
    ZTransform,
    scan,
)


def _make_tiff_dir(base: Path, layout: dict[str, np.ndarray]) -> Path:
    d = base / "tiffs"
    d.mkdir(exist_ok=True)
    for name, data in layout.items():
        tifffile.imwrite(str(d / name), data)
    return d


class TestEndToEnd:
    def test_scan_plan_execute(self, tmp_path):
        """Full pipeline: scan -> plan -> execute -> verify."""
        dapi = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        gfp = np.random.randint(0, 65535, (64, 64), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {
            "region1_ch00.tif": dapi,
            "region1_ch01.tif": gfp,
        })

        # Step 1: Scan
        result = scan(tiff_dir)
        assert len(result.channels) == 2
        assert len(result.fovs) == 1
        assert result.files

        # Step 2: Create plan from scan result
        plan = ImportPlan(
            source_path=tiff_dir,
            condition="control",
            channel_mappings=[
                ChannelMapping(token_value="00", name="DAPI"),
                ChannelMapping(token_value="01", name="GFP"),
            ],
            fov_names={"region1": "Well_A1"},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=0.65,
            token_config=TokenConfig(),
        )

        # Step 3: Execute
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            engine = ImportEngine()
            import_result = engine.execute(plan, store)

            assert import_result.fovs_imported == 1
            assert import_result.channels_registered == 2
            assert import_result.images_written == 2

            # Step 4: Verify store contents
            channels = store.get_channels()
            assert {ch.name for ch in channels} == {"DAPI", "GFP"}

            fovs = store.get_fovs(condition="control")
            assert len(fovs) == 1
            assert fovs[0].name == "Well_A1"

            img = store.read_image_numpy("Well_A1", "control", "DAPI")
            np.testing.assert_array_equal(img, dapi)

    def test_scan_plan_yaml_round_trip_execute(self, tmp_path):
        """Full pipeline with YAML persistence: scan -> plan -> save YAML -> load -> execute."""
        data = np.random.randint(0, 65535, (32, 32), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        # Scan and create plan
        scan_result = scan(tiff_dir)
        plan = ImportPlan(
            source_path=tiff_dir,
            condition="treated",
            channel_mappings=[ChannelMapping(token_value="00", name="DAPI")],
            fov_names={"img": "FOV1"},
            z_transform=ZTransform(method="mip"),
            pixel_size_um=None,
            token_config=TokenConfig(),
        )

        # Save to YAML and reload
        yaml_path = tmp_path / "import_plan.yaml"
        plan.to_yaml(yaml_path)
        loaded_plan = ImportPlan.from_yaml(yaml_path)

        # Execute the loaded plan
        with ExperimentStore.create(tmp_path / "test.percell") as store:
            engine = ImportEngine()
            result = engine.execute(loaded_plan, store)

            assert result.fovs_imported == 1
            assert result.images_written == 1

            img = store.read_image_numpy("FOV1", "treated", "DAPI")
            np.testing.assert_array_equal(img, data)


class TestPublicAPI:
    def test_all_public_names_importable(self):
        """Verify all names in __all__ are importable from percell3.io."""
        import percell3.io as io_module

        for name in io_module.__all__:
            assert hasattr(io_module, name), f"{name} not found in percell3.io"

    def test_scan_convenience_function(self, tmp_path):
        """The scan() convenience function works like FileScanner.scan()."""
        data = np.zeros((16, 16), dtype=np.uint16)
        tiff_dir = _make_tiff_dir(tmp_path, {"img_ch00.tif": data})

        result = scan(tiff_dir)
        assert isinstance(result, ScanResult)
        assert len(result.files) == 1
