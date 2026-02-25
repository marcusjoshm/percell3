"""Tests for pure-numpy mesh construction (_surface_mesh.build_surface)."""

from __future__ import annotations

import numpy as np
import pytest

from percell3.plugins.builtin._surface_mesh import build_surface


class TestBuildSurface:
    """Tests for the build_surface function."""

    def test_basic_shape(self) -> None:
        """4x4 height -> 16 vertices, 18 faces."""
        height = np.ones((4, 4), dtype=np.float32)
        color = np.ones((4, 4), dtype=np.float32)
        verts, faces, vals = build_surface(height, color)

        assert verts.shape == (16, 3)
        # 2 triangles per 2x2 quad: 2 * (4-1) * (4-1) = 18
        assert faces.shape == (18, 3)
        assert vals.shape == (16,)

    def test_larger_grid(self) -> None:
        """10x8 height -> 80 vertices, 126 faces."""
        height = np.random.rand(10, 8).astype(np.float32)
        color = np.random.rand(10, 8).astype(np.float32)
        verts, faces, vals = build_surface(height, color)

        assert verts.shape == (80, 3)
        assert faces.shape == (2 * 9 * 7, 3)  # 126
        assert vals.shape == (80,)

    def test_dtype(self) -> None:
        """Vertices float32, faces int32, values float32."""
        height = np.ones((3, 3), dtype=np.float64)
        color = np.ones((3, 3), dtype=np.float64)
        verts, faces, vals = build_surface(height, color)

        assert verts.dtype == np.float32
        assert faces.dtype == np.int32
        assert vals.dtype == np.float32

    def test_z_scale(self) -> None:
        """z_scale changes the max Z vertex value."""
        height = np.array([[0, 1], [0, 1]], dtype=np.float32)
        color = np.zeros((2, 2), dtype=np.float32)

        verts_50, _, _ = build_surface(height, color, z_scale=50.0)
        verts_100, _, _ = build_surface(height, color, z_scale=100.0)

        z_max_50 = verts_50[:, 2].max()
        z_max_100 = verts_100[:, 2].max()

        # Height is normalized to [0,1] first, then scaled
        assert z_max_50 == pytest.approx(50.0)
        assert z_max_100 == pytest.approx(100.0)

    def test_sigma_smoothing(self) -> None:
        """sigma > 0 produces smoother Z than sigma = 0."""
        np.random.seed(42)
        height = np.random.rand(20, 20).astype(np.float32)
        color = np.zeros((20, 20), dtype=np.float32)

        verts_raw, _, _ = build_surface(height, color, sigma=0.0, z_scale=1.0)
        verts_smooth, _, _ = build_surface(height, color, sigma=2.0, z_scale=1.0)

        z_std_raw = verts_raw[:, 2].std()
        z_std_smooth = verts_smooth[:, 2].std()

        assert z_std_smooth < z_std_raw

    def test_nan_handling(self) -> None:
        """NaN in height is replaced with 0 — no crash."""
        height = np.array([[1.0, np.nan], [0.0, 1.0]], dtype=np.float32)
        color = np.zeros((2, 2), dtype=np.float32)

        verts, faces, vals = build_surface(height, color)
        assert np.all(np.isfinite(verts))

    def test_inf_handling(self) -> None:
        """Inf in height is replaced with 0 — no crash."""
        height = np.array([[1.0, np.inf], [0.0, 1.0]], dtype=np.float32)
        color = np.zeros((2, 2), dtype=np.float32)

        verts, _, _ = build_surface(height, color)
        assert np.all(np.isfinite(verts))

    def test_uniform_height(self) -> None:
        """All-same height -> flat surface (no crash, Z all same)."""
        height = np.full((5, 5), 42.0, dtype=np.float32)
        color = np.zeros((5, 5), dtype=np.float32)

        verts, faces, vals = build_surface(height, color)
        # Uniform height normalizes to 0, so all Z = 0
        assert np.allclose(verts[:, 2], 0.0)

    def test_minimum_size_1x1_raises(self) -> None:
        """1x1 input raises ValueError."""
        with pytest.raises(ValueError, match="at least 2x2"):
            build_surface(
                np.ones((1, 1), dtype=np.float32),
                np.ones((1, 1), dtype=np.float32),
            )

    def test_minimum_size_1x3_raises(self) -> None:
        """1xN input raises ValueError."""
        with pytest.raises(ValueError, match="at least 2x2"):
            build_surface(
                np.ones((1, 3), dtype=np.float32),
                np.ones((1, 3), dtype=np.float32),
            )

    def test_minimum_size_2x2_works(self) -> None:
        """2x2 is the minimum valid size."""
        height = np.array([[0, 1], [1, 0]], dtype=np.float32)
        color = np.zeros((2, 2), dtype=np.float32)

        verts, faces, vals = build_surface(height, color)
        assert verts.shape == (4, 3)
        assert faces.shape == (2, 3)

    def test_color_values_match_shape(self) -> None:
        """values array length equals number of vertices."""
        height = np.random.rand(7, 9).astype(np.float32)
        color = np.random.rand(7, 9).astype(np.float32)

        verts, _, vals = build_surface(height, color)
        assert len(vals) == len(verts)

    def test_mismatched_shapes_raises(self) -> None:
        """Different height and color shapes raises ValueError."""
        with pytest.raises(ValueError, match="shape"):
            build_surface(
                np.ones((3, 4), dtype=np.float32),
                np.ones((4, 3), dtype=np.float32),
            )

    def test_non_2d_raises(self) -> None:
        """3D input raises ValueError."""
        with pytest.raises(ValueError, match="2D"):
            build_surface(
                np.ones((3, 3, 3), dtype=np.float32),
                np.ones((3, 3, 3), dtype=np.float32),
            )

    def test_face_indices_valid(self) -> None:
        """All face indices reference valid vertex indices."""
        height = np.random.rand(6, 8).astype(np.float32)
        color = np.random.rand(6, 8).astype(np.float32)

        verts, faces, _ = build_surface(height, color)
        n_verts = len(verts)
        assert faces.min() >= 0
        assert faces.max() < n_verts

    def test_vertex_row_col_coordinates(self) -> None:
        """Vertex row/col values span the expected grid range."""
        H, W = 5, 7
        height = np.random.rand(H, W).astype(np.float32)
        color = np.zeros((H, W), dtype=np.float32)

        verts, _, _ = build_surface(height, color)
        rows = verts[:, 0]
        cols = verts[:, 1]

        assert rows.min() == pytest.approx(0.0)
        assert rows.max() == pytest.approx(H - 1)
        assert cols.min() == pytest.approx(0.0)
        assert cols.max() == pytest.approx(W - 1)
