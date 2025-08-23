#!/usr/bin/env python3
"""
Plain-Python tests for diff utilities in penguin.tools.core.support

Covers:
- enhanced_diff (basic and semantic for .py)
- apply_diff_to_file (unified diff application)
- edit_file_with_pattern (regex replacement + diff)

Run with: python test_diff_tools.py
"""

import sys
import tempfile
from pathlib import Path

# Ensure local penguin package is importable when run directly
sys.path.insert(0, str(Path(__file__).parent))

from penguin.tools.core.support import (  # type: ignore
    enhanced_diff,
    apply_diff_to_file,
    generate_diff_patch,
    edit_file_with_pattern,
    preview_unified_diff,
    apply_unified_patch,
)


def assert_true(condition: bool, message: str):
    if condition:
        print(f"✅ {message}")
        return True
    else:
        print(f"❌ {message}")
        return False


def test_enhanced_diff_basic(tmp: Path) -> bool:
    a = tmp / "a.txt"
    b = tmp / "b.txt"
    a.write_text("hello\nworld\n", encoding="utf-8")
    b.write_text("hello\npenguin\n", encoding="utf-8")

    out = enhanced_diff(str(a), str(b), context_lines=1, semantic=False)
    return (
        assert_true("Diff between" in out, "enhanced_diff produced a diff header")
        and assert_true("@@" in out, "enhanced_diff includes unified diff hunk header")
        and assert_true("-world" in out and "+penguin" in out, "enhanced_diff shows changed lines")
    )


def test_enhanced_diff_semantic(tmp: Path) -> bool:
    f1 = tmp / "f1.py"
    f2 = tmp / "f2.py"
    f1.write_text(
        """
def foo():
    return 1
""".lstrip(),
        encoding="utf-8",
    )
    f2.write_text(
        """
def foo():
    return 2

def bar():
    return 3
""".lstrip(),
        encoding="utf-8",
    )

    out = enhanced_diff(str(f1), str(f2), context_lines=2, semantic=True)
    return (
        assert_true("Semantic changes:" in out, "semantic summary present for .py files")
        and assert_true("Added functions:" in out and "bar" in out, "semantic summary lists new function")
        and assert_true("Detailed diff:" in out or "@@" in out, "semantic output includes diff details")
    )


def test_apply_diff_roundtrip(tmp: Path) -> bool:
    target = tmp / "apply_target.txt"
    original = "line1\nline2\nline3"
    updated = "line1\nline-two\nline3"
    target.write_text(original, encoding="utf-8")

    patch = generate_diff_patch(original, updated, str(target))
    res = apply_diff_to_file(str(target), patch, backup=True)

    after = target.read_text(encoding="utf-8")
    # Compare normalized lines to avoid trailing newline sensitivity
    ok = (
        assert_true("Successfully applied diff" in res, "diff application reported success")
        and assert_true(after.splitlines() == updated.splitlines(), "file content matches updated after diff")
    )

    # Backup exists
    backup = target.with_suffix(target.suffix + ".bak")
    return ok and assert_true(backup.exists(), "backup file created")


def test_apply_diff_multihunk_and_context(tmp: Path) -> bool:
    target = tmp / "multi.txt"
    original = (
        "a1\n"
        "a2\n"
        "a3\n"
        "b1\n"
        "b2\n"
        "b3\n"
        "c1\n"
        "c2\n"
        "c3\n"
    )
    updated = (
        "a1\n"
        "A2\n"  # change
        "a3\n"
        "b1\n"
        "B2\n"  # change
        "b3\n"
        "c1\n"
        "c2\n"
        "c3\n"
    )
    target.write_text(original, encoding="utf-8")

    patch = generate_diff_patch(original, updated, str(target))
    res = apply_diff_to_file(str(target), patch, backup=True)
    after = target.read_text(encoding="utf-8")

    return (
        assert_true("Successfully applied diff" in res, "multi-hunk diff applied")
        and assert_true(after == updated, "multi-hunk content matches")
    )


def test_edit_file_with_pattern(tmp: Path) -> bool:
    target = tmp / "pattern.txt"
    target.write_text("alpha beta gamma", encoding="utf-8")

    res = edit_file_with_pattern(str(target), r"beta", "BETA", backup=True)
    after = target.read_text(encoding="utf-8")

    return (
        assert_true("Successfully edited" in res, "pattern edit reported success")
        and assert_true("BETA" in after and "beta" not in after, "pattern replaced in file")
        and assert_true(target.with_suffix(target.suffix + ".bak").exists(), "backup created for pattern edit")
    )


def test_enhanced_diff_missing_file(tmp: Path) -> bool:
    a = tmp / "does_not_exist.txt"
    b = tmp / "exists.txt"
    b.write_text("ok", encoding="utf-8")
    out = enhanced_diff(str(a), str(b))
    return assert_true("Error: File does not exist" in out, "enhanced_diff reports missing file error")


def test_crlf_preservation_and_patch(tmp: Path) -> bool:
    target = tmp / "crlf.txt"
    original = "Line1\r\nLine2\r\n"
    updated = "Line1\r\nLINE2\r\n"
    # Write CRLF explicitly
    target.write_bytes(original.encode("utf-8"))
    patch = generate_diff_patch(original.replace("\r\n", "\n"), updated.replace("\r\n", "\n"), str(target))
    res = apply_diff_to_file(str(target), patch, backup=True)
    after_bytes = target.read_bytes()
    after = after_bytes.decode("utf-8")
    return (
        assert_true("Successfully applied diff" in res, "CRLF diff applied")
        and assert_true("\r\n" in after and after.endswith("\r\n"), "CRLF preserved on write")
        and assert_true("LINE2\r\n" in after, "content updated under CRLF")
    )


def test_whitespace_only_diff(tmp: Path) -> bool:
    target = tmp / "ws.txt"
    original = "a\n    b\n"
    updated = "a\n  b\n"  # indentation change only
    target.write_text(original, encoding="utf-8")
    patch = generate_diff_patch(original, updated, str(target))
    res = apply_diff_to_file(str(target), patch, backup=True)
    after = target.read_text(encoding="utf-8")
    return (
        assert_true("Successfully applied diff" in res, "whitespace-only diff applied")
        and assert_true(after == updated, "whitespace changes reflected")
    )


def test_stale_base_context_mismatch_rollback(tmp: Path) -> bool:
    target = tmp / "stale.txt"
    base = "x\ny\nz\n"
    newer = "x\nyY\nz\n"  # current file is already edited
    patch_against_base = generate_diff_patch(base, "x\nyyy\nz\n", str(target))
    target.write_text(newer, encoding="utf-8")
    res = apply_diff_to_file(str(target), patch_against_base, backup=True)
    # Should error and leave file as-is because of context mismatch
    after = target.read_text(encoding="utf-8")
    return (
        assert_true("Error applying diff:" in res, "stale base detected and reported")
        and assert_true(after == newer, "file unchanged after mismatch")
    )


def test_idempotent_reapply(tmp: Path) -> bool:
    target = tmp / "idem.txt"
    original = "a\n"
    updated = "A\n"
    target.write_text(original, encoding="utf-8")
    patch = generate_diff_patch(original, updated, str(target))
    res1 = apply_diff_to_file(str(target), patch, backup=True)
    res2 = apply_diff_to_file(str(target), patch, backup=True)
    after = target.read_text(encoding="utf-8")
    return (
        assert_true("Successfully applied diff" in res1, "first apply ok")
        and assert_true("Error applying diff:" in res2 or "Successfully applied diff" in res2, "second apply is safe")
        and assert_true(after == updated, "content remains updated")
    )


def test_preview_and_structured_result(tmp: Path) -> bool:
    target = tmp / "structured.txt"
    original = "a\n"
    updated = "A\nB\n"
    target.write_text(original, encoding="utf-8")
    patch = generate_diff_patch(original, updated, str(target))
    # Preview
    preview = preview_unified_diff(patch)
    ok_preview = assert_true("hunks:" in preview and "additions:" in preview, "preview summarizes diff")
    # Structured apply
    res_json = apply_diff_to_file(str(target), patch, backup=True, return_json=True)
    ok_json = assert_true('"status": "success"' in res_json and '"hunks"' in res_json, "structured result returned")
    return ok_preview and ok_json


def test_unicode_emoji_and_combining(tmp: Path) -> bool:
    target = tmp / "unicode.txt"
    original = "naïve café 😊\n"
    updated = "naïve café 🚀\n"
    target.write_text(original, encoding="utf-8")
    patch = generate_diff_patch(original, updated, str(target))
    res = apply_diff_to_file(str(target), patch, backup=True)
    after = target.read_text(encoding="utf-8")
    return (
        assert_true("Successfully applied diff" in res, "unicode diff applied")
        and assert_true("🚀" in after, "emoji updated correctly")
    )


def test_multifile_patch_rejected(tmp: Path) -> bool:
    # Create two files and a combined diff (simulated headers)
    f1 = tmp / "one.txt"
    f2 = tmp / "two.txt"
    f1.write_text("a\n", encoding="utf-8")
    f2.write_text("x\n", encoding="utf-8")

    diff1 = generate_diff_patch("a\n", "A\n", str(f1))
    diff2 = generate_diff_patch("x\n", "X\n", str(f2))
    multi = f"--- a/{f1}\n+++ b/{f1}\n" + "\n".join(diff1.splitlines()[2:]) + "\n" + \
            f"--- a/{f2}\n+++ b/{f2}\n" + "\n".join(diff2.splitlines()[2:])

    res = apply_diff_to_file(str(f1), multi, backup=True)
    return assert_true("Multi-file patches are not supported" in res, "multi-file patch rejected")


def test_apply_unified_patch_multiple_files(tmp: Path) -> bool:
    f1 = tmp / "one.txt"
    f2 = tmp / "two.txt"
    f1.write_text("a\n", encoding="utf-8")
    f2.write_text("x\n", encoding="utf-8")

    d1 = generate_diff_patch("a\n", "A\n", str(f1))
    d2 = generate_diff_patch("x\n", "X\nY\n", str(f2))
    # Construct a simple multi-file patch with headers
    multi = d1 + d2
    res = apply_unified_patch(multi, workspace_path=str(tmp), backup=True, return_json=True)
    ok = assert_true('"status": "success"' in res, "apply_unified_patch succeeded")
    return ok and assert_true(f1.read_text(encoding="utf-8") == "A\n" and f2.read_text(encoding="utf-8") == "X\nY\n", "both files updated")


def test_semantic_docstring_decorator_changes(tmp: Path) -> bool:
    # Ensure enhanced_diff reports semantic additions/removals with decorators and docstrings
    a = tmp / "sem.py"
    b = tmp / "sem2.py"
    a.write_text(
        '''
def f():
    """say hi"""
    return 1
'''.lstrip(), encoding="utf-8")
    b.write_text(
        '''
@decorator
def g():
    """say hi loudly"""
    return 2
'''.lstrip(), encoding="utf-8")

    out = enhanced_diff(str(a), str(b), semantic=True)
    return (
        assert_true("Semantic changes:" in out, "semantic header present")
        and assert_true("Added functions:" in out or "Removed functions:" in out, "function rename appears as add/remove")
    )


def main() -> int:
    print("\n🧪 Testing diff tools (enhanced_diff, apply_diff_to_file, edit_file_with_pattern)\n")
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tests = [
            (test_enhanced_diff_basic, "enhanced_diff basic"),
            (test_enhanced_diff_semantic, "enhanced_diff semantic for .py"),
            (test_apply_diff_roundtrip, "apply_diff_to_file roundtrip"),
            (test_apply_diff_multihunk_and_context, "apply_diff_to_file multi-hunk"),
            (test_edit_file_with_pattern, "edit_file_with_pattern"),
            (test_enhanced_diff_missing_file, "enhanced_diff missing file"),
            (test_crlf_preservation_and_patch, "CRLF preservation and patch"),
            (test_whitespace_only_diff, "whitespace-only diff"),
            (test_stale_base_context_mismatch_rollback, "stale base context mismatch rollback"),
            (test_idempotent_reapply, "idempotent re-apply"),
            (test_unicode_emoji_and_combining, "unicode and emoji changes"),
            (test_multifile_patch_rejected, "multi-file patch rejected"),
            (test_semantic_docstring_decorator_changes, "semantic docstring/decorator changes"),
            (test_preview_and_structured_result, "preview + structured result"),
            (test_apply_unified_patch_multiple_files, "apply unified multi-file patch"),
        ]

        for fn, name in tests:
            print(f"--- {name} ---")
            ok = fn(tmp)
            if not ok:
                failures += 1
            print()

    if failures == 0:
        print("🎉 All diff tool tests passed!")
        return 0
    else:
        print(f"❌ {failures} test(s) failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


