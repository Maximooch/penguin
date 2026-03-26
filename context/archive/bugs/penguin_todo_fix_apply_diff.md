# Fix plan: apply_diff + tool guidance

## Summary of issues
- prompt_actions examples still show backtick syntax for apply_diff/insert_lines and malformed closing tags for find_files_enhanced/perplexity_search
- new line-based tools are implemented but not wired into parser ActionType/ActionExecutor, so tags never execute
- apply_diff is strict on context match; fallback is narrow and fails on small drift
- core_tools plugin apply_diff handler passes a dict to apply_diff_to_file (signature mismatch)

## Recent commits (last 5)
- b213d52 update tool call format to angle brackets, but left some backticks and malformed tags
- 26e0f6d add line-based editing tools; parser not updated
- 7167693 merge prompt v2
- f71823d personality tweak
- 3cf4795 finish_response placeholder fix

## Plan
1. Normalize prompt examples to <tool>...</tool> and fix malformed closing tags in prompt_actions.py; wrap examples in actionxml fences.
2. Add replace_lines/insert_lines/delete_lines to ActionType and ActionExecutor in utils/parser.py; update cli/tui regex to recognize new tags.
3. Harden apply_diff: accept fenced diffs, fall back to apply_unified_patch (optionally git-apply) on context mismatch; improve error output with diff analysis + hint to use line tools.
4. Fix core_tools plugin apply_diff handler to call apply_diff_to_file(file_path, diff_content, ...).
5. Add regression tests for action tags and apply_diff fallback (tests/test_action_tag_parser.py, tests/test_diff_tools.py).

## Suggested verification
- pytest tests/test_action_tag_parser.py
- pytest tests/test_diff_tools.py
