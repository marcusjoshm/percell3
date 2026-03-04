"""Shared constants for the PerCell 3 core module.

Defines metric names, scope values, and batch parameters used across
core and measure modules.
"""

from __future__ import annotations

# Particle summary metrics stored per-cell in the measurements table.
PARTICLE_SUMMARY_METRICS: list[str] = [
    "particle_count",
    "total_particle_area",
    "mean_particle_area",
    "max_particle_area",
    "total_particle_area_pixels",
    "mean_particle_area_pixels",
    "max_particle_area_pixels",
    "particle_coverage_fraction",
    "mean_particle_mean_intensity",
    "mean_particle_integrated_intensity",
    "total_particle_integrated_intensity",
]

# Particle area metrics stored in pixels, converted to um2 at export time.
PARTICLE_AREA_METRICS: list[str] = [
    "total_particle_area",
    "mean_particle_area",
    "max_particle_area",
]

# Aggregate metrics computed per (channel, condition, bio_rep) group during
# Prism export.  These are derived from per-cell particle_count data -- they
# are NOT stored in the database.
PARTICLE_AGGREGATE_METRICS: list[str] = [
    "pct_cells_with_particles",
]

# Valid measurement scopes.
VALID_SCOPES: frozenset[str] = frozenset({"whole_cell", "mask_inside", "mask_outside"})

# Maximum number of bind parameters per batch for IN-clause queries.
# SQLite default limit is 999; we use 900 for safety.
DEFAULT_BATCH_SIZE: int = 900
