---
title: "Data Model Restructure — Biological Replicates, FOV, and Configurable Tech Reps"
type: feat
date: 2026-02-17
status: decided
---

# Data Model Restructure Brainstorm

## What We're Building

Restructure the experiment hierarchy from the current **condition → region** to **biological replicate → condition → FOV**, and make "technical replicate" a configurable grouping at analysis time rather than a structural concept.

### New Hierarchy

```
Experiment
├── N1 (biological replicate, auto-numbered)
│   ├── control (condition)
│   │   ├── FOV_001
│   │   ├── FOV_002
│   │   └── FOV_003
│   └── treated (condition)
│       ├── FOV_001
│       └── FOV_002
├── N2
│   ├── control
│   │   └── FOV_001
│   └── treated
│       └── FOV_001
└── N3
    └── ...
```

### Current Hierarchy (being replaced)

```
Experiment
├── control (condition)
│   ├── region1
│   └── region2
└── treated (condition)
    ├── region3
    └── region4
```

## Why This Change

- **Statistical rigor**: Biological replicates (big N) are the independent units for statistical analysis. The current model has no way to distinguish biological from technical replication.
- **Flexible analysis**: "Technical replicate" means different things in different contexts — sometimes a single FOV, sometimes all cells pooled across FOVs. Making it configurable at analysis time avoids locking in one interpretation.
- **Accurate terminology**: "Region" is ambiguous. "FOV" (field of view) is the standard microscopy term for what's actually being captured.
- **Report generation**: Proper N/n distinction is essential for generating publication-quality statistical reports.

## Key Decisions

### 1. Hierarchy: Bio Rep > Condition > FOV

**Decision:** Biological replicate is the top-level grouping, not condition.

**Rationale:** In real experiments, a biological replicate (e.g., Mouse 1) contains both control and treated conditions. The bio rep is the independent unit — conditions within a bio rep are paired/matched observations.

### 2. Rename "Region" → "FOV"

**Decision:** Replace "region" with "FOV" (field of view) throughout the entire codebase — code, database, Zarr paths, CLI, tests.

**Rationale:** FOV is the precise microscopy term. "Region" was always a proxy for "field of view" but was ambiguous. The user wants a clean rename, not an alias.

### 3. Bio Rep Naming: Auto-Numbered (N1, N2, N3...)

**Decision:** Biological replicates are auto-numbered with the format `N1`, `N2`, `N3`, etc.

**Rationale:** Keeps things simple and consistent. The number is the meaningful part — the bio rep's identity doesn't need a custom name.

### 4. Technical Replicate: Configurable at Analysis Time

**Decision:** "Technical replicate" is NOT a structural element in the data model. Instead, it's a grouping option chosen during measure/export/statistics.

**Options at analysis time:**
- **Per-FOV**: Each FOV is one technical replicate (default). Statistics computed per-FOV, then averaged across bio reps.
- **Pooled**: All cells across all FOVs within a bio rep × condition are pooled into one data point. The bio rep IS the replicate.

**Rationale:** Sometimes tech reps are individual FOVs, sometimes they're all cells across FOVs. Hardcoding one interpretation would be wrong for some experiments.

### 5. Blast Radius

This is a large refactor touching nearly every module:

| Area | Impact |
|------|--------|
| **SQLite schema** | New `biological_replicates` table; `regions` → `fovs`; FK changes |
| **Zarr paths** | Currently `condition/region/channel` → becomes `bio_rep/condition/fov/channel` |
| **Core models** | `RegionInfo` → `FovInfo`; new `BioRepInfo` dataclass |
| **ExperimentStore** | ~50 region methods need renaming; new bio_rep methods |
| **IO (import)** | Import flow needs bio rep assignment step |
| **Segment** | All region references → fov |
| **Viewer** | All region references → fov |
| **CLI** | All `--region` flags → `--fov`; new `--bio-rep` flags |
| **Tests** | 540+ tests, many reference regions |
| **Measure/Export** | Add tech rep grouping option |

## Implementation Approach

### Phase 1: Rename region → FOV (mechanical refactor)
- Rename `regions` table → `fovs`, `RegionInfo` → `FovInfo`
- Rename all methods, variables, CLI flags, test references
- Zarr paths: `condition/region` → `condition/fov`
- No new functionality — pure rename
- All 540+ tests should still pass with updated names

### Phase 2: Add biological replicate layer
- New `biological_replicates` table (id, name auto-numbered N1, N2...)
- FOVs get `bio_rep_id` foreign key
- Zarr hierarchy: `bio_rep/condition/fov/channel`
- Import flow: assign FOVs to bio reps
- CLI: new `--bio-rep` option where needed
- New `ExperimentStore` methods for bio rep CRUD

### Phase 3: Configurable tech rep grouping
- Add grouping option to measure/export/statistics
- Per-FOV (default) vs pooled modes
- Affects how summary statistics are computed and exported

## Resolved Questions

1. **Migration**: Breaking change — re-import required. Old `.percell` experiments won't open in the new version. Acceptable since the app is in alpha with no external users yet.
2. **Default bio rep**: Yes — default `N1`. Everything goes into N1 automatically. The bio rep layer is invisible unless the user adds N2+. Keeps simple experiments simple.
3. **FOV naming**: Auto-numbered (`FOV_001`, `FOV_002`, ...). Consistent and clean. No user-defined names needed.
