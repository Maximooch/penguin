# Bug: `analyze_project` Emits Invalid-Escape Warnings and Produces Misleading Cross-Language Results

## Status
Open

## Observed On
2026-09-22

## Summary

While comparing Penguin with `reference/unreal-agent`, the `analyze_project` tool emitted repeated Python `SyntaxWarning` messages for invalid escape sequences and returned materially misleading project statistics.

The workspace-level scan traversed unrelated and generated content such as `.venv`, `.worktrees`, and other reference repositories despite `include_external=false`. The targeted scan of `reference/unreal-agent`, which is predominantly Go, reported only 11 files and 1,629 lines, almost entirely from its Python benchmark harness, while omitting the main Go implementation from the analysis totals.

This appears to be two related tool-quality problems:

1. Python source parsing/compilation is surfacing invalid-escape warnings from scanned text without identifying the source file.
2. The analyzer presents partial, Python-centric results as if they describe the requested project, without language-coverage or skipped-file diagnostics.

The warnings may be non-fatal, but the resulting analysis is not trustworthy for a mixed-language or non-Python repository.

## Reproduction

From the Penguin repository root, invoke:

```text
analyze_project(directory=".", include_external=false)
analyze_project(directory="reference/unreal-agent", include_external=false)
```

The first call returned statistics including:

```text
Files analyzed: 26143
Total lines: 8905278

.venv/lib/python3.12/site-packages/...
.worktrees/prompt-economy/.venv/lib/python3.12/site-packages/...
reference/hermes-agent/...
```

The targeted Unreal Agent call returned:

```text
Files analyzed: 11
Total lines: 1629
Total functions: 44
Total classes: 9
```

Its file breakdown listed only `benchmarks/harbor/*.py` files, even though the repository's primary implementation is under Go packages including `harness/`, `cmd/`, and `internal/`.

Shortly after the tool call, the Penguin server emitted:

```text
<unknown>:4241: SyntaxWarning: invalid escape sequence '\ '
<unknown>:61: SyntaxWarning: invalid escape sequence '\.'
<unknown>:4241: SyntaxWarning: invalid escape sequence '\ '
<unknown>:61: SyntaxWarning: invalid escape sequence '\.'
<unknown>:4241: SyntaxWarning: invalid escape sequence '\ '
<unknown>:625: SyntaxWarning: invalid escape sequence '\d'
```

The provider request itself completed successfully and requested four tool calls, so this was not an upstream model-stream failure.

## Expected Behavior

- `include_external=false` should exclude virtual environments, dependency trees, worktrees, generated artifacts, tool-result logs, and unrelated sibling/reference projects unless explicitly requested.
- A targeted directory scan should inventory supported source files in that directory, including the repository's principal language.
- If the analyzer only supports Python AST analysis, it should say so explicitly and report unsupported/skipped files by language rather than presenting partial totals as project totals.
- Parser warnings should include the actual source path and should be captured as structured diagnostics rather than leaking as `<unknown>` warnings to server stderr.
- Invalid Python files or string literals should not abort or distort the rest of the inventory.

## Actual Impact

- The initial comparison incorrectly suggested that Unreal Agent consisted of only 11 files and 1,629 lines.
- Penguin's scan was dominated by `.venv`, `.worktrees`, and unrelated reference code, making its totals unusable.
- The `<unknown>` warning locations provide no actionable path to the offending input.
- An agent can mistake the output for a valid cross-language architecture analysis and draw incorrect conclusions.

Impact is **medium-high** for repository surveys and comparisons. The tool returns plausible-looking numbers, which is more dangerous than a clear unsupported-language error. *Confident nonsense remains nonsense, but now it has a table.*

## Suspected Areas

- File discovery/default ignore rules used by the `analyze_project` tool.
- Reliance on Python `ast.parse`, `compile`, or equivalent for arbitrary scanned text.
- Warning handling around parser calls (`warnings.catch_warnings`, filename propagation, and per-file diagnostic capture).
- Language detection and analyzer dispatch.
- Aggregation logic that labels analyzed Python files as the complete project inventory.

The implementation was not located in the Penguin application tree during this report; it may live in the external tool host/runtime. That should be confirmed before assigning the fix.

## Suggested Investigation

1. Add a fixture repository containing Python, Go, JavaScript/TypeScript, generated files, a virtual environment-shaped directory, and a Python file with invalid escapes.
2. Verify that default discovery ignores `.git`, `.venv`, `venv`, `.worktrees`, `node_modules`, build outputs, caches, and tool-result/log directories.
3. Separate generic inventory metrics from language-specific AST metrics.
4. Add explicit fields such as:
   - discovered files by language
   - analyzed files by analyzer
   - skipped files and reasons
   - parse warnings/errors with source paths
5. Pass the real filename into parser/compiler APIs and capture warnings per file.
6. For unsupported languages, either provide a lightweight structural analyzer or clearly mark the result as partial.
7. Add regression assertions that a Go repository's `.go` files appear in its inventory and that `include_external=false` does not traverse `.venv` or `.worktrees`.

## Workaround

For the resumed comparison, avoid `analyze_project` and use targeted file listing, language-aware search, direct source reads, and native test/build metadata instead.
