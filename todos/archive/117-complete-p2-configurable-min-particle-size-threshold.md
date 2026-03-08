---
status: complete
priority: p2
issue_id: "117"
tags: [code-review, measure, cli, feature]
dependencies: []
---

# Make minimum particle size filter configurable in grouped intensity thresholding

## Problem Statement

The grouped intensity thresholding pipeline has a minimum particle area filter of 5 pixels hardcoded in `ParticleAnalyzer.__init__()`. This value is not user-configurable from the CLI menu. Users need the ability to set a larger minimum size to exclude noise/artifacts, or a smaller size to capture tiny particles.

The filter exists at `ParticleAnalyzer` (line 75 in `measure/particle_analyzer.py`) but `menu.py:1711` instantiates it with the default: `ParticleAnalyzer()`.

## Findings

- **Found by:** user request + code investigation
- **Location:** `src/percell3/measure/particle_analyzer.py:75` (default=5), `src/percell3/cli/menu.py:1711` (no param passed)
- `ParticleAnalyzer.__init__(min_particle_area=5)` already accepts the parameter
- The CLI thresholding handler (`_apply_threshold`) does not collect this parameter
- The filter is applied during connected component analysis at `particle_analyzer.py:166-167`
- Small particles below the threshold are silently skipped — they don't appear in the particle labels or the exported data

## Proposed Solutions

### Solution A: Add CLI prompt for min particle area (Recommended)

1. Add a step to the thresholding CLI handler asking for minimum particle area
2. Pass the value to `ParticleAnalyzer(min_particle_area=user_value)`
3. Default to 5 pixels (current behavior)

- **Pros:** Simple, backwards-compatible, uses existing parameter
- **Cons:** One more step in the already multi-step thresholding flow
- **Effort:** Small
- **Risk:** None

### Solution B: Also filter the binary mask

In addition to Solution A, update `write_particle_labels()` to also update the binary threshold mask, removing small components so the mask and labels stay consistent.

- **Pros:** Mask and labels are consistent — no small blobs in the mask that don't have labels
- **Cons:** More invasive change
- **Effort:** Medium
- **Risk:** Low

## Technical Details

**Affected files:**
- `src/percell3/cli/menu.py` — add min area prompt, pass to `ParticleAnalyzer()`
- (Optional) `src/percell3/measure/particle_analyzer.py` — already supports the parameter

## Acceptance Criteria

- [ ] CLI prompts for minimum particle area with default of 5
- [ ] ParticleAnalyzer receives the user-specified value
- [ ] Particles below the threshold are excluded from labels and measurements
- [ ] Default behavior (5 pixels) is unchanged when user accepts default
