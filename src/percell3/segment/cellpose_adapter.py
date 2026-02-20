"""Cellpose segmentation adapter — wraps Cellpose behind BaseSegmenter interface."""

from __future__ import annotations

from typing import Any

import numpy as np

from percell3.segment.base_segmenter import BaseSegmenter, SegmentationParams


KNOWN_CELLPOSE_MODELS = frozenset({
    "cpsam",  # Cellpose 4.x default (SAM-based)
    "cyto", "cyto2", "cyto3", "nuclei",  # 3.x models (map to cpsam on 4.x)
    "tissuenet", "livecell",
    "tissuenet_cp3", "livecell_cp3",
    "deepbacs_cp3", "cyto2_cp3",
    "yeast_PhC_cp3", "yeast_BF_cp3",
    "bact_phase_cp3", "bact_fluor_cp3",
    "plant_cp3",
})


class CellposeAdapter(BaseSegmenter):
    """Cellpose segmentation backend with lazy import and model caching.

    Cellpose is imported lazily inside ``_get_model()`` to avoid slow
    module-level imports. Models are cached by ``(model_name, gpu)``
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
            model_name: Cellpose model name (e.g., "cpsam", "cyto3") or a
                filesystem path to a custom-trained model.
            gpu: Whether to use GPU acceleration.

        Returns:
            A Cellpose model instance (``CellposeModel`` in 4.x, ``Cellpose`` in 3.x).

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
                    "Install it with: pip install 'percell3[all]' or pip install cellpose"
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

    def segment(self, image: np.ndarray, params: SegmentationParams) -> np.ndarray:
        """Run Cellpose segmentation on a single 2D image.

        Args:
            image: 2D array (Y, X) of the channel to segment.
            params: Segmentation parameters.

        Returns:
            Label image (Y, X) as int32 where pixel value = cell ID, 0 = background.
        """
        model = self._get_model(params.model_name, params.gpu)
        results = model.eval(
            image,
            diameter=params.diameter,
            flow_threshold=params.flow_threshold,
            cellprob_threshold=params.cellprob_threshold,
            min_size=params.min_size,
            normalize=params.normalize,
            channels=params.channels_cellpose or [0, 0],
        )
        # Cellpose 3.x returns 4 values, 4.x returns 3
        masks = results[0]
        return np.asarray(masks, dtype=np.int32)
