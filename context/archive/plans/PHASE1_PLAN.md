# Phase 1: Extract Display Logic

## Objective
Move display logic from PenguinCLI to UnifiedRenderer to reduce code duplication and separation of concerns.

## Current State
- cli.py: 5,806 lines
- PenguinCLI has ~698 lines of display methods
- UnifiedRenderer exists but is underutilized
- Code duplication: LANGUAGE_DETECTION_PATTERNS, LANGUAGE_DISPLAY_NAMES, diff rendering

## Methods to Move (from PenguinCLI to UnifiedRenderer)

### High Priority (core display methods)
1. `display_message` → delegate to `UnifiedRenderer.render_message`
2. `_format_code_block` → use `UnifiedRenderer.render_code_block`
3. `_extract_and_display_reasoning` → use `UnifiedRenderer.render_reasoning`
4. `_detect_language` → use `UnifiedRenderer.detect_language`
5. `_looks_like_diff` → use `UnifiedRenderer.is_diff`

### Medium Priority (specialized display)
6. `display_action_result` → use `UnifiedRenderer.render_tool_result`
7. `_display_file_read_result` → add to `UnifiedRenderer`
8. `_display_diff_result` → add to `UnifiedRenderer`
9. `_render_diff_message` → add to `UnifiedRenderer`
10. `_split_diff_sections` → add to `UnifiedRenderer`
11. `_compute_diff_stats` → add to `UnifiedRenderer`

### Low Priority (command-specific)
12. `_display_list_response` → add to `UnifiedRenderer`
13. `_display_checkpoints_response` → add to `UnifiedRenderer`
14. `_display_token_usage_response` → add to `UnifiedRenderer`
15. `_display_truncations_response` → add to `UnifiedRenderer`
16. `_display_code_output_panel` → add to `UnifiedRenderer`

## Code Duplication to Remove
1. `LANGUAGE_DETECTION_PATTERNS` - exists in both PenguinCLI and UnifiedRenderer
2. `LANGUAGE_DISPLAY_NAMES` - exists in both PenguinCLI and UnifiedRenderer
3. Diff rendering logic - duplicated in multiple methods

## Expected Outcome
- cli.py: ~5,100 lines (706 lines removed)
- UnifiedRenderer: More comprehensive display methods
- No code duplication
- Clear separation: CLI handles logic, Renderer handles display

## Execution Steps
1. Read UnifiedRenderer to understand current implementation
2. Add missing display methods to UnifiedRenderer
3. Remove duplicated constants from PenguinCLI
4. Update PenguinCLI to delegate to UnifiedRenderer
5. Run tests to verify no regressions
