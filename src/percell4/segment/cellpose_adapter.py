"""Cellpose segmentation adapter and MockSegmenter for testing.

Ported from percell3.segment.cellpose_adapter with a simplified interface:
    segment(image, **kwargs) -> label_image

CellposeSegmenter wraps the Cellpose library with lazy importing and model
caching.  MockSegmenter provides a test double using threshold + connected
components.
"""

from __future__ import annotations

from typing import Any

import numpy as np


KNOWN_CELLPOSE_MODELS = frozenset({
    "cpsam",  # Cellpose 4.x default (SAM-based)
    "cyto", "cyto2", "cyto3", "nuclei",  # 3.x models
    "tissuenet", "livecell",
    "tissuenet_cp3", "livecell_cp3",
    "deepbacs_cp3", "cyto2_cp3",
    "yeast_PhC_cp3", "yeast_BF_cp3",
    "bact_phase_cp3", "bact_fluor_cp3",
    "plant_cp3",
})


class CellposeSegmenter:
    """Cellpose segmentation backend with lazy import and model caching.

    Cellpose is imported lazily inside ``_get_model()`` to avoid slow
    module-level imports.  Models are cached by ``(model_name, gpu)``
    to prevent redundant loading.
    """

    def __init__(self) -> None:
        self._model_cache: dict[tuple[str, bool], Any] = {}
        self._cellpose_major: int | None = None

    @staticmethod
    def _is_custom_path(model_name: str) -> bool:
        """Check if model_name is a filesystem path rather than a known model."""
        return "/" in model_name or "\\" in model_name

    def _get_model(self, model_name: str, gpu: bool) -> Any:
        """Get or create a cached Cellpose model instance.

        Args:
            model_name: Cellpose model name or filesystem path.
            gpu: Whether to use GPU acceleration.

        Returns:
            A Cellpose model instance.

        Raises:
            ImportError: If cellpose is not installed.
            ValueError: If model_name is not a known model or valid path.
        """
        is_custom = self._is_custom_path(model_name)
        if not is_custom and model_name not in KNOWN_CELLPOSE_MODELS:
            raise ValueError(
                f"Unknown model {model_name!r}. "
                f"Known models: {sorted(KNOWN_CELLPOSE_MODELS)}"
            )
        key = (model_name, gpu)
        if key not in self._model_cache:
            try:
                from cellpose import models  # Lazy import
            except ImportError as exc:
                raise ImportError(
                    "cellpose is required for segmentation. "
                    "Install it with: pip install 'percell4[all]' or pip install cellpose"
                ) from exc
            if self._cellpose_major is None:
                from importlib.metadata import version as _pkg_version
                self._cellpose_major = int(_pkg_version("cellpose").split(".")[0])
            model_cls = getattr(models, "CellposeModel", None) or getattr(
                models, "Cellpose"
            )
            if is_custom or self._cellpose_major >= 4:
                self._model_cache[key] = model_cls(
                    pretrained_model=model_name, gpu=gpu,
                )
            else:
                self._model_cache[key] = model_cls(
                    model_type=model_name, gpu=gpu,
                )
        return self._model_cache[key]

    def segment(
        self,
        image: np.ndarray,
        model_name: str = "cyto3",
        diameter: float = 30.0,
        gpu: bool = False,
        **kwargs: Any,
    ) -> np.ndarray:
        """Run Cellpose segmentation on a single 2D image.

        Args:
            image: 2D array (Y, X) of the channel to segment.
            model_name: Cellpose model name.
            diameter: Expected cell diameter in pixels.
            gpu: Whether to use GPU acceleration.
            **kwargs: Additional eval parameters (flow_threshold,
                cellprob_threshold, min_size, normalize, etc.).

        Returns:
            Label image (Y, X) as int32 where pixel value = ROI ID,
            0 = background.
        """
        model = self._get_model(model_name, gpu)
        eval_kwargs: dict[str, object] = {
            "diameter": diameter,
        }
        for key in ("flow_threshold", "cellprob_threshold", "min_size", "normalize"):
            if key in kwargs:
                eval_kwargs[key] = kwargs[key]

        # Cellpose 4.x deprecated the channels parameter; only pass on 3.x
        if self._cellpose_major is not None and self._cellpose_major < 4:
            eval_kwargs["channels"] = kwargs.get("channels_cellpose", [0, 0])

        results = model.eval(image, **eval_kwargs)
        # Cellpose 3.x returns 4 values, 4.x returns 3
        masks = results[0]
        return np.asarray(masks, dtype=np.int32)


class MockSegmenter:
    """Test double for segmentation — uses threshold + connected components.

    Produces a label image by thresholding the input above 0 and
    labelling connected components with ``scipy.ndimage.label``.
    """

    def segment(self, image: np.ndarray, **kwargs: Any) -> np.ndarray:
        """Segment by thresholding at the image mean and labelling components.

        Args:
            image: 2D array (Y, X).
            **kwargs: Ignored (present for API compatibility).

        Returns:
            Label image (Y, X) as int32.
        """
        from scipy.ndimage import label as ndimage_label

        threshold = image.mean()
        binary = image > threshold
        labels, _ = ndimage_label(binary)
        return np.asarray(labels, dtype=np.int32)
