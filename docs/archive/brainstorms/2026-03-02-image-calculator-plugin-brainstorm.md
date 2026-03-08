# Image Calculator Plugin Brainstorm

**Date:** 2026-03-02
**Status:** Draft

## What We're Building

An Image Calculator plugin that mirrors ImageJ's `Process > Math` and `Process > Image Calculator` functionality. The plugin operates on a single FOV at a time and supports two modes:

1. **Single-channel math** — Apply an arithmetic operation with a user-specified constant to one channel (e.g., Multiply ch00 by 2).
2. **Two-channel math** — Apply an arithmetic operation between two selected channels (e.g., Subtract ch01 from ch00).

Both modes produce a **new derived FOV** as output, never modifying original data.

## Why This Approach

- **Non-destructive:** All operations create derived FOVs, preserving original data. This follows the existing split_halo_condensate_analysis pattern.
- **Single plugin, two modes:** One `image_calculator` plugin with a `mode` parameter keeps registration simple while covering both use cases.
- **Clip to original dtype:** Results are clipped to the input image's data type (e.g., uint16), matching ImageJ's default behavior and avoiding unexpected type changes.

## Key Decisions

### Operations Supported
Core arithmetic plus common extras (matching ImageJ's most-used operations):

| Operation | Single-channel (with constant) | Two-channel (between channels) |
|-----------|-------------------------------|-------------------------------|
| Add       | pixel + constant              | pixelA + pixelB               |
| Subtract  | pixel - constant              | pixelA - pixelB               |
| Multiply  | pixel * constant              | pixelA * pixelB               |
| Divide    | pixel / constant              | pixelA / pixelB               |
| AND       | pixel & constant              | pixelA & pixelB               |
| OR        | pixel \| constant             | pixelA \| pixelB              |
| XOR       | pixel ^ constant              | pixelA ^ pixelB               |
| Min       | min(pixel, constant)          | min(pixelA, pixelB)           |
| Max       | max(pixel, constant)          | max(pixelA, pixelB)           |
| Abs Diff  | abs(pixel - constant)         | abs(pixelA - pixelB)          |

### Output: Derived FOV Structure

**Single-channel mode** (e.g., Add 50 to ch00 on a 3-channel FOV):
- Derived FOV has 3 channels: `ch00_add_50`, `ch01`, `ch02`
- The modified channel gets a descriptive auto-generated name
- Unmodified channels are copied as-is

**Two-channel mode** (e.g., Multiply ch00 by ch01 on a 3-channel FOV):
- Derived FOV has 2 channels: `ch00_multiply_ch01`, `ch02`
- The two input channels merge into one result channel
- Remaining channels are copied as-is

### Naming Convention
- **Derived FOV name:** `{original_fov_name}_{operation}_{operand}` (auto-generated)
  - Single-channel example: `sample_01_ch00_add_50`
  - Two-channel example: `sample_01_ch00_multiply_ch01`
- **Result channel name:** `{channel}_{operation}_{operand}`
  - Single-channel example: `ch00_add_50`
  - Two-channel example: `ch00_multiply_ch01`

### Data Type Handling
- Results clip to the original image dtype (e.g., uint16 stays uint16)
- Intermediate computation done in float64 to avoid overflow during calculation, then clipped and cast back
- Division by zero produces 0 (not NaN or Inf)

### Parameter Schema
```json
{
  "type": "object",
  "properties": {
    "mode": {
      "type": "string",
      "enum": ["single_channel", "two_channel"],
      "description": "Whether to apply math with a constant or between two channels"
    },
    "operation": {
      "type": "string",
      "enum": ["add", "subtract", "multiply", "divide", "and", "or", "xor", "min", "max", "abs_diff"]
    },
    "fov_id": {
      "type": "integer",
      "description": "FOV to process"
    },
    "channel_a": {
      "type": "string",
      "description": "Primary channel to operate on"
    },
    "channel_b": {
      "type": "string",
      "description": "Second channel (required for two_channel mode)"
    },
    "constant": {
      "type": "number",
      "description": "Constant value (required for single_channel mode)"
    }
  },
  "required": ["mode", "operation", "fov_id", "channel_a"]
}
```

### Plugin Structure
- Plugin class: `ImageCalculatorPlugin` in `src/percell3/plugins/builtin/image_calculator.py`
- Core math logic: `src/percell3/plugins/builtin/image_calculator_core.py` (pure numpy, no store dependency)
- Tests: `tests/test_plugins/test_image_calculator.py`

## Open Questions

None — all key decisions have been resolved through discussion.
