"""Cellpose segmentation adapter — wraps Cellpose behind BaseSegmenter interface."""

from __future__ import annotations

from typing import Any

import numpy as np

from percell3.segment.base_segmenter import BaseSegmenter, SegmentationParams


class CellposeAdapter(BaseSegmenter):
    """Cellpose segmentation backend with lazy import and model caching.

    Cellpose is imported lazily inside ``_get_model()`` to avoid slow
    module-level imports. Models are cached by ``(model_name, gpu)``
    to prevent redundant loading.
    """

    def __init__(self) -> None:
        self._model_cache: dict[tuple[str, bool], Any] = {}

    def _get_model(self, model_name: str, gpu: bool) -> Any:
        """Get or create a cached Cellpose model instance.

        Args:
            model_name: Cellpose model type (e.g., "cyto3", "nuclei").
            gpu: Whether to use GPU acceleration.

        Returns:
            A Cellpose model instance (``CellposeModel`` in 4.x, ``Cellpose`` in 3.x).

        Raises:
            ImportError: If cellpose is not installed.
        """
        key = (model_name, gpu)
        if key not in self._model_cache:
            try:
                from cellpose import models  # Lazy import
            except ImportError as exc:
                raise ImportError(
                    "cellpose is required for segmentation. "
                    "Install it with: pip install 'percell3[all]' or pip install cellpose"
                ) from exc
            model_cls = getattr(models, "CellposeModel", None) or getattr(
                models, "Cellpose"
            )
            self._model_cache[key] = model_cls(
                model_type=model_name,
                gpu=gpu,
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
        return masks.astype(np.int32)

    def segment_batch(
        self, images: list[np.ndarray], params: SegmentationParams
    ) -> list[np.ndarray]:
        """Run Cellpose segmentation on multiple images.

        Args:
            images: List of 2D arrays (Y, X).
            params: Segmentation parameters.

        Returns:
            List of label images (Y, X) as int32.
        """
        model = self._get_model(params.model_name, params.gpu)
        results = model.eval(
            images,
            diameter=params.diameter,
            flow_threshold=params.flow_threshold,
            cellprob_threshold=params.cellprob_threshold,
            min_size=params.min_size,
            normalize=params.normalize,
            channels=params.channels_cellpose or [0, 0],
        )
        # model.eval returns (masks, flows, styles[, diams]) — count varies by version
        masks_list = results[0]
        return [m.astype(np.int32) for m in masks_list]
