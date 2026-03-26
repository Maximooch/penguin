# Penguin File Tool Stress Test Report

## Summary

This report documents an interactive stress test of Penguin's file editing tools in the workspace at `/Users/maximusputnam/Code/test4` on `Darwin`.

Short version:
- `write_file` successfully created new files.
- `patch_file` successfully handled `replace_lines`, `regex_replace`, `delete_lines`, and `unified_diff` edits.
- `patch_file` with `insert_lines` failed with a `NoneType` error.
- `patch_files` failed due a workspace permission denial.
- `write_file` could create files, but overwriting an existing file was blocked by policy.
- Backup behavior worked and preserved pre-edit state.

## Test Environment

- Workspace: `/Users/maximusputnam/Code/test4`
- Visible project content at start: `errors_log/`
- No `context/` directory existed in this workspace
- Primary sandbox files created during testing:
  - `file_tool_test.txt`
  - `notes_test.md`

## Test Sequence

### 1. Initial Workspace Check

Observed that the workspace was mostly empty except for:
- `errors_log/`

Attempting to inspect `context/` failed because that directory did not exist.

### 2. New File Creation With `write_file`

Created `file_tool_test.txt` with content:

```text
line one
line two
line three
```

Result:
- Success
- File was created as expected

Created `notes_test.md` with content:

```md
# Tool Test

- alpha
- beta
```

Result:
- Success
- File was created as expected

### 3. Line Replacement With `patch_file` / `replace_lines`

Applied a line replacement to `file_tool_test.txt`:
- Replaced line 2: `line two`
- New line 2: `line two edited`

Result:
- Success
- Backup file created: `file_tool_test.txt.bak`
- Diff output was correct

### 4. Insert Operation With `patch_file` / `insert_lines`

Attempted to insert a new line into `notes_test.md`.

Result:
- Failure
- Tool returned:

```json
{"error": "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'", "tool": "patch_file"}
```

Interpretation:
- The `insert_lines` operation path appears buggy or has parameter handling defects.
- This was not a content issue in the file; reading the file afterward showed normal line numbering.

### 5. Insert Fallback With `patch_file` / `unified_diff`

Retried the same logical insert using a unified diff to append:
- `- inserted gamma`

Result:
- Success
- `notes_test.md` now contained:

```md
# Tool Test

- alpha
- beta
- inserted gamma
```

Interpretation:
- `unified_diff` is a safer fallback when structured line-insert operations are unstable.

### 6. Multi-File Edit With `patch_files`

Attempted atomic multi-file edits:
- Change `line three` in `file_tool_test.txt`
- Change `- beta` in `notes_test.md`

Result:
- Failure
- Tool returned:

```json
{"error": "permission_denied", "tool": "patch_files", "reason": "Operation 'filesystem.write' denied for 'patch_files'"}
```

Interpretation:
- This does not necessarily mean the tool implementation is broken.
- It does mean this workspace or policy layer denied writes through `patch_files` specifically.
- Single-file edits remained allowed afterward, so this looks like a policy/tool permission mismatch rather than a global filesystem failure.

### 7. Regex Replacement With `patch_file`

Retried one of the failed multi-file edits as a single-file operation using `regex_replace` on `file_tool_test.txt`.

Change:
- `line three`
- to `line three patched via regex_replace`

Result:
- Success

File content became:

```text
line one
line two edited
line three patched via regex_replace
```

### 8. Delete Operation With `patch_file` / `delete_lines`

Deleted line 5 from `notes_test.md`, which removed:
- `- inserted gamma`

Result:
- Success
- Backup file created: `notes_test.md.bak`

Final file content became:

```md
# Tool Test

- alpha
- beta
```

### 9. Full-File Overwrite With `write_file`

Attempted to overwrite existing `file_tool_test.txt` using `write_file` with new content:

```text
overwrite one
overwrite two
overwrite three
```

Result:
- Failure
- Tool returned:

```text
Error applying changes: Path not allowed by policy: /Users/maximusputnam/Code/test4/file_tool_test.txt
```

Interpretation:
- In this environment, `write_file` was allowed for file creation but not for replacing an existing file.
- That is a policy behavior worth documenting clearly because it will surprise users who treat `write_file` as both create and overwrite.

### 10. Whole-File Replacement With `patch_file` / `replace_lines`

Used `patch_file` to replace lines 1-3 in `file_tool_test.txt` with:

```text
overwrite one
overwrite two
overwrite three
```

Result:
- Success
- Backup file created or updated: `file_tool_test.txt.bak`
- Diff output matched expectations

Final file content became:

```text
overwrite one
overwrite two
overwrite three
```

## Final State of Files

### `file_tool_test.txt`

Final content:

```text
overwrite one
overwrite two
overwrite three
```

### `notes_test.md`

Final content:

```md
# Tool Test

- alpha
- beta
```

## Backup Verification

### `file_tool_test.txt.bak`

Verified backup content:

```text
line one
line two edited
line three patched via regex_replace
```

This confirms the backup preserved the pre-overwrite state.

### `notes_test.md.bak`

Verified backup content:

```md
# Tool Test

- alpha
- beta
- inserted gamma
```

This confirms the backup preserved the pre-delete state.

## Reliability Assessment

### Worked Reliably

- `write_file` for new file creation
- `patch_file` with `replace_lines`
- `patch_file` with `regex_replace`
- `patch_file` with `delete_lines`
- `patch_file` with `unified_diff`
- Backup generation during successful patch operations
- `read_file` and file verification flow

### Did Not Work Reliably

- `patch_file` with `insert_lines`
- `patch_files` in this workspace/policy context
- `write_file` for overwriting an existing file

## Likely Root Causes

### 1. `insert_lines` Parameter Handling Bug

The `NoneType` error strongly suggests one of these:
- missing validation for required numeric fields
- internal misuse of `start_line` / `end_line`
- a code path expecting an integer but receiving `None`

This smells like implementation defect, not user error.

### 2. `patch_files` Permission Layer Inconsistency

Since single-file writes succeeded while `patch_files` was denied, likely causes are:
- a separate permission policy for atomic multi-file writes
- a missing allowlist for `patch_files`
- a sandbox guard treating batch writes more strictly than single-file writes

### 3. `write_file` Create vs Overwrite Policy Split

Behavior observed:
- create new file: allowed
- overwrite existing file: denied

That means either:
- the tool is routed through different policy checks for create vs overwrite, or
- overwrite is intentionally blocked in this environment

Either way, documentation should stop implying that `write_file` is always a drop-in replacement for existing files.

## Recommendations For Penguin Dev

### High Priority

1. Fix `patch_file` `insert_lines`
   - Add strict payload validation
   - Return clear parameter errors instead of internal `NoneType` crashes
   - Add tests for insert-before, insert-after, insert-at-end cases

2. Audit `patch_files` permission behavior
   - Confirm whether denial is expected policy or accidental misconfiguration
   - Ensure error messaging distinguishes policy block from tool failure
   - Add an integration test under realistic workspace permissions

3. Clarify `write_file` semantics
   - Document whether overwrite is supported everywhere or policy-dependent
   - If overwrite may fail by policy, error message should say so explicitly

### Medium Priority

4. Improve fallback guidance in docs
   - Recommend `unified_diff` when structured line edits fail
   - Recommend `patch_file` over `write_file` for modifying existing files in restricted environments

5. Standardize backup behavior docs
   - State when `.bak` files are created
   - State whether repeated edits replace or refresh the same backup file

### Suggested Test Matrix

The tool suite needs explicit coverage for:
- create new file with `write_file`
- overwrite existing file with `write_file`
- `replace_lines` on first, middle, and last lines
- `insert_lines` at beginning, middle, and EOF
- `delete_lines` single and multi-line
- `regex_replace` with one match, many matches, and no matches
- `unified_diff` happy path and malformed diff path
- `patch_files` under both allowed and denied permission contexts
- backup creation and backup content validation

## Practical Guidance For Users

If someone asked me what to trust today, the answer is:
- use `patch_file` first for edits to existing files
- use `write_file` for creating brand new files
- use `unified_diff` as the escape hatch when line-oriented operations misbehave
- do not assume `patch_files` will be allowed in restricted workspaces

## Conclusion

The good news: the core editing path is real, usable, and verifiable.

The bad news: there are clear rough edges in batch writes, insert operations, and overwrite policy handling. In plain English, `patch_file` is the dependable hammer here, while `insert_lines`, `patch_files`, and overwrite-via-`write_file` still need engineering attention.

## Post-Fix Retest

After the initial report was written, the Penguin developer indicated fixes had been made. The previously failing paths were retested in the same workspace.

### Retest 1: `patch_file` / `insert_lines`

First, the old-style payload was retried using `start_line`.

Result:
- Failure, but now with a clear validation message instead of an internal crash

```json
{"error": "patch_file insert_lines requires integer 'after_line'", "tool": "patch_file"}
```

Then the operation was retried using the documented parameter:
- `after_line: 4`
- inserted content: `- inserted gamma retest`

Result:
- Success

Interpretation:
- This is a real improvement.
- The tool contract is now explicit, and invalid input produces a useful error instead of a `NoneType` exception.

### Retest 2: `patch_files`

Retried atomic multi-file edits affecting both sandbox files.

Result:
- Success
- Tool returned `success: true`
- Both files were edited
- No rollback was required

Interpretation:
- The earlier permission issue appears resolved.
- `patch_files` is now functioning correctly in this workspace.

### Retest 3: `write_file` Overwrite Existing File

Retried overwriting the existing `file_tool_test.txt` with new content.

Result:
- Success
- Diff output rendered correctly

Interpretation:
- The previous overwrite policy block appears resolved.
- `write_file` now behaves as expected for both file creation and replacement.

### Post-Fix End State

Verified final content after retest:

`file_tool_test.txt`

```text
overwrite one final
overwrite two final
overwrite three final via write_file retest
```

`notes_test.md`

```md
# Tool Test

- alpha
- beta via patch_files retest
- inserted gamma retest
```

### Revised Assessment

Based on the retest, the original issues were not all permanent defects. At least in this environment, the tool behavior is now materially better:

- `insert_lines` now has clear parameter validation and a working success path
- `patch_files` now performs atomic multi-file writes successfully
- `write_file` now overwrites existing files successfully

Bottom line: the original report captured real failures, but the post-fix retest shows meaningful progress. The remaining risk is mostly around documentation clarity and ensuring these fixes are covered by regression tests so they do not quietly break again.

## Output Consistency Retest

A follow-up retest was performed after additional cleanup work to check whether output formatting had become more consistent.

### Findings

- Canonical edit paths continued to work:
  - `patch_file` `regex_replace`
  - `patch_file` `replace_lines`
  - `patch_file` `unified_diff`
  - `write_file` overwrite on existing files
- `patch_file` with `unified_diff` now returned the actual diff body in the tool result, not just a success message.
- `write_file` overwrite diff headers improved from odd absolute-path output like `a//Users/...` to sane relative-path output like `a/round3-retest.txt`.

Interpretation:
- This is not a correctness change so much as a trust and UX improvement.
- More consistent diff output makes the TUI easier to read and easier to trust.

## Stress-Test Round 4

A more aggressive stress test was then performed to probe malformed payload handling, no-op behavior, malformed diffs, and multi-file rollback semantics.

### Stress Test Setup

Created sandbox files:
- `stress-a.txt`
- `stress-b.txt`

### 1. Malformed `insert_lines` Payload

Tested `patch_file` `insert_lines` without the required `after_line` field.

Result:

```json
{"error": "patch_file insert_lines requires integer 'after_line'", "tool": "patch_file"}
```

Interpretation:
- Good failure mode.
- The tool now rejects malformed input explicitly instead of crashing internally.

### 2. Out-of-Range `replace_lines`

Tested `replace_lines` with `end_line` beyond the file length.

Result:

```text
Error: end_line (12) exceeds file length (4)
```

Interpretation:
- Good failure mode.
- Bounds checking is explicit and readable.

### 3. No-Match `regex_replace`

Tested a regex replacement using a pattern not present in the file.

Result:

```text
No matches found for pattern in /Users/maximusputnam/Code/test4/stress-a.txt
```

Interpretation:
- Good semantics.
- The tool does not pretend success when nothing changed.

### 4. Malformed / Context-Mismatched Unified Diff

Tested a unified diff with incorrect context so the patch could not apply cleanly.

Result:
- Failure with explicit context mismatch messaging
- Error artifacts logged under `errors_log/diffs/`
- The tool suggested falling back to line-based edits for small changes

Representative error text:

```text
Error applying diff: Context mismatch while applying diff (file changed since diff was generated) (hunks=1, adds=1, dels=1, ctx=3) ... Consider replace_lines/insert_lines/delete_lines for small edits.
```

Interpretation:
- The good news is that failure is loud, diagnosable, and logged.
- The rough edge is that the error text is somewhat repetitive/noisy.

### 5. `patch_files` Rollback Behavior

Tested atomic multi-file editing with one valid target and one missing file.

Result:
- `success: false`
- `files_edited` temporarily included `stress-a.txt`
- `files_failed` included `stress-missing.txt`
- `rollback_performed: true`

The supposedly edited file was then re-read and verified to have been restored to its original content:

```text
apple
banana
carrot
date
```

Interpretation:
- This is a strong result.
- Rollback appears real, not cosmetic.
- That materially increases trust in `patch_files` as an atomic operation.

## Updated Reliability Assessment

### Now Working Reliably In This Workspace

- `write_file` for new file creation
- `write_file` for overwriting existing files
- `patch_file` with `replace_lines`
- `patch_file` with `regex_replace`
- `patch_file` with `delete_lines`
- `patch_file` with `insert_lines` when using the explicit `after_line` contract
- `patch_file` with `unified_diff`
- `patch_files` for atomic multi-file edits
- `patch_files` rollback on failure
- Backup generation during successful patch operations
- `read_file` and verification flow

### Remaining Rough Edges

- `insert_lines` still needs users to know the exact `after_line` contract; docs matter here
- Unified-diff failure output is informative but somewhat noisy and repetitive
- Output formatting consistency should stay covered by regression tests because it directly affects TUI trust

## Updated Conclusion

The original failures were real, but many of them have now been fixed. At this point the file toolchain looks substantially more mature.

The biggest shift is not just that edits succeed. It is that failures are now more explicit, rollback appears trustworthy, and diff output is more consistent. That combination is what turns file editing from “probably works” into something a user can confidently lean on.
