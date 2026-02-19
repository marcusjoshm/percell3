"""CellGrouper — GMM-based cell grouping by expression level."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from percell3.core import ExperimentStore

logger = logging.getLogger(__name__)

MIN_CELLS_FOR_GMM = 10


@dataclass(frozen=True)
class GroupingResult:
    """Result of GMM-based cell grouping.

    Attributes:
        n_groups: Number of groups assigned.
        group_labels: Int array (one per cell, 0-indexed, ascending by metric mean).
        group_means: Mean metric value per group (ascending order).
        bic_scores: BIC score for each tested component count.
        tag_names: Tag names created (e.g., ["group:GFP:mean_intensity:g1", ...]).
        cell_ids: Cell IDs in the same order as group_labels.
    """

    n_groups: int
    group_labels: np.ndarray
    group_means: list[float]
    bic_scores: list[float]
    tag_names: list[str]
    cell_ids: list[int]


class CellGrouper:
    """Group cells by metric value using Gaussian Mixture Models with BIC selection."""

    def group_cells(
        self,
        store: ExperimentStore,
        fov: str,
        condition: str,
        channel: str,
        metric: str,
        bio_rep: str | None = None,
        max_components: int = 10,
    ) -> GroupingResult:
        """Group cells in a FOV by metric value using GMM with BIC.

        Args:
            store: Target ExperimentStore.
            fov: FOV name.
            condition: Condition name.
            channel: Channel name for grouping metric.
            metric: Metric name (e.g., "mean_intensity", "area_pixels").
            bio_rep: Biological replicate (auto-resolved if None).
            max_components: Maximum GMM components to test.

        Returns:
            GroupingResult with group assignments and tags.

        Raises:
            ValueError: If no cells found or metric not measured.
        """
        # 1. Get cells for this FOV
        cells_df = store.get_cells(condition=condition, bio_rep=bio_rep, fov=fov)
        if cells_df.empty:
            raise ValueError(f"No cells found in {condition}/{fov}")

        cell_ids = cells_df["id"].tolist()

        # 2. Get metric values
        values = self._get_metric_values(store, cells_df, channel, metric)

        # 3. Fit GMM and assign groups
        tag_prefix = f"group:{channel}:{metric}:"

        # Clean old group tags for these cells
        store.delete_tags_by_prefix(tag_prefix, cell_ids=cell_ids)

        if len(cell_ids) < MIN_CELLS_FOR_GMM:
            logger.warning(
                "Only %d cells in %s/%s — using single group (need %d for GMM)",
                len(cell_ids), condition, fov, MIN_CELLS_FOR_GMM,
            )
            result = self._single_group(cell_ids, values, tag_prefix)
        else:
            result = self._fit_gmm(cell_ids, values, tag_prefix, max_components)

        # 4. Tag cells
        from percell3.core.exceptions import DuplicateError

        for i, tag_name in enumerate(result.tag_names):
            group_cell_ids = [
                cid for cid, label in zip(result.cell_ids, result.group_labels)
                if label == i
            ]
            if group_cell_ids:
                try:
                    store.add_tag(tag_name)
                except DuplicateError:
                    pass  # Tag already exists from previous grouping
                store.tag_cells(group_cell_ids, tag_name)

        return result

    def _get_metric_values(
        self,
        store: ExperimentStore,
        cells_df,
        channel: str,
        metric: str,
    ) -> np.ndarray:
        """Get metric values for cells, from measurements table or cells table."""
        cell_ids = cells_df["id"].tolist()

        # Special case: area_pixels comes from cells table
        if metric == "area_pixels":
            return cells_df["area_pixels"].to_numpy(dtype=np.float64)

        # Otherwise get from measurements
        measurements_df = store.get_measurements(
            cell_ids=cell_ids, channels=[channel], metrics=[metric],
        )
        if measurements_df.empty:
            raise ValueError(
                f"No measurements for metric {metric!r} on channel {channel!r}. "
                "Run measurements first."
            )

        # Align values with cell_ids order
        value_map = dict(zip(measurements_df["cell_id"], measurements_df["value"]))
        values = []
        for cid in cell_ids:
            if cid not in value_map:
                raise ValueError(
                    f"Cell {cid} has no measurement for {channel}/{metric}"
                )
            values.append(value_map[cid])
        return np.array(values, dtype=np.float64)

    def _single_group(
        self,
        cell_ids: list[int],
        values: np.ndarray,
        tag_prefix: str,
    ) -> GroupingResult:
        """Assign all cells to a single group."""
        tag_name = f"{tag_prefix}g1"
        return GroupingResult(
            n_groups=1,
            group_labels=np.zeros(len(cell_ids), dtype=int),
            group_means=[float(np.mean(values))],
            bic_scores=[],
            tag_names=[tag_name],
            cell_ids=cell_ids,
        )

    def _fit_gmm(
        self,
        cell_ids: list[int],
        values: np.ndarray,
        tag_prefix: str,
        max_components: int,
    ) -> GroupingResult:
        """Fit GMM with BIC selection and return groups ordered by ascending mean."""
        from sklearn.mixture import GaussianMixture

        X = values.reshape(-1, 1)
        max_k = min(max_components, len(cell_ids) // 5)
        max_k = max(max_k, 1)

        bic_scores: list[float] = []
        best_bic = float("inf")
        best_gmm: GaussianMixture | None = None

        for k in range(1, max_k + 1):
            gmm = GaussianMixture(
                n_components=k,
                covariance_type="full",
                n_init=5,
                random_state=42,
            )
            gmm.fit(X)
            bic = gmm.bic(X)
            bic_scores.append(bic)
            if bic < best_bic:
                best_bic = bic
                best_gmm = gmm

        assert best_gmm is not None

        n_groups = best_gmm.n_components
        raw_labels = best_gmm.predict(X)

        if n_groups == 1:
            logger.info("GMM selected 1 component — homogeneous population")

        # Compute group means and sort by ascending mean
        group_means_unsorted = []
        for g in range(n_groups):
            mask = raw_labels == g
            group_means_unsorted.append(float(np.mean(values[mask])))

        # Sort order: ascending by mean
        sort_order = np.argsort(group_means_unsorted)
        label_remap = np.zeros(n_groups, dtype=int)
        for new_idx, old_idx in enumerate(sort_order):
            label_remap[old_idx] = new_idx

        group_labels = np.array([label_remap[l] for l in raw_labels], dtype=int)
        group_means = [group_means_unsorted[i] for i in sort_order]
        tag_names = [f"{tag_prefix}g{i + 1}" for i in range(n_groups)]

        return GroupingResult(
            n_groups=n_groups,
            group_labels=group_labels,
            group_means=group_means,
            bic_scores=bic_scores,
            tag_names=tag_names,
            cell_ids=cell_ids,
        )
