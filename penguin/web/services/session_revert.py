"""Session revert helpers for OpenCode-compatible TUI flows."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
import re
import uuid
from typing import Any, Optional

from penguin.tools.core.support import _apply_unified_diff
from penguin.web.services.session_view import (
    REVERT_KEY,
    REVERT_SNAPSHOT_KEY,
    SUMMARY_KEY,
    _build_file_diff,
    _build_session_info,
    _extract_file_from_diff,
    _find_session,
    _line_counts,
    _session_directory,
    get_session_messages,
    list_session_statuses,
)


def _snapshot_id() -> str:
    return f"revert_{uuid.uuid4().hex[:8]}"


def _reverse_unified_diff(diff_text: str) -> str:
    lines = diff_text.splitlines()
    reversed_lines: list[str] = []
    hunk_pattern = re.compile(
        r"@@ -(?P<o_start>\d+)(?:,(?P<o_cnt>\d+))? \+(?P<n_start>\d+)(?:,(?P<n_cnt>\d+))? @@(?P<tail>.*)"
    )

    for line in lines:
        if line.startswith("--- "):
            reversed_lines.append("+++ " + line[4:])
            continue
        if line.startswith("+++ "):
            reversed_lines.append("--- " + line[4:])
            continue
        if line.startswith("@@"):
            match = hunk_pattern.match(line)
            if not match:
                reversed_lines.append(line)
                continue
            reversed_lines.append(
                "@@ -"
                f"{match.group('n_start')}"
                f"{(',' + match.group('n_cnt')) if match.group('n_cnt') else ''}"
                " +"
                f"{match.group('o_start')}"
                f"{(',' + match.group('o_cnt')) if match.group('o_cnt') else ''}"
                f" @@{match.group('tail')}"
            )
            continue
        if line.startswith("+") and not line.startswith("+++"):
            reversed_lines.append("-" + line[1:])
            continue
        if line.startswith("-") and not line.startswith("---"):
            reversed_lines.append("+" + line[1:])
            continue
        reversed_lines.append(line)

    return "\n".join(reversed_lines) + ("\n" if diff_text.endswith("\n") else "")


def _parse_diff_paths(diff_text: str) -> tuple[str, str]:
    from_path = ""
    to_path = ""
    for line in diff_text.splitlines():
        if line.startswith("--- ") and not from_path:
            from_path = line[4:].strip()
            continue
        if line.startswith("+++ ") and not to_path:
            to_path = line[4:].strip()
            break
    return from_path, to_path


def _clean_diff_path(value: str) -> str:
    if value in {"/dev/null", ""}:
        return ""
    return value[2:] if value.startswith(("a/", "b/")) else value


def _collect_revert_diffs(
    rows: list[dict[str, Any]], message_id: str, part_id: str | None
) -> tuple[str, list[str], list[str]]:
    started = False
    diff_texts: list[str] = []
    files: list[str] = []
    hidden_ids: list[str] = []

    for row in rows:
        info = row.get("info") if isinstance(row, dict) else None
        if not isinstance(info, dict):
            continue
        row_id = str(info.get("id") or "")
        if not started and row_id == message_id:
            started = True
        if not started:
            continue
        if row_id:
            hidden_ids.append(row_id)

        parts = row.get("parts")
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            if (
                isinstance(part_id, str)
                and part_id.strip()
                and part.get("id") != part_id
            ):
                continue
            state = part.get("state")
            if not isinstance(state, dict):
                continue
            metadata = state.get("metadata")
            if not isinstance(metadata, dict):
                continue
            diff_text = metadata.get("diff")
            if not isinstance(diff_text, str) or not diff_text.strip():
                continue
            diff_texts.append(diff_text)
            from_path, to_path = _parse_diff_paths(diff_text)
            for raw in (from_path, to_path):
                cleaned = _clean_diff_path(raw)
                if cleaned and cleaned not in files:
                    files.append(cleaned)
        if isinstance(part_id, str) and part_id.strip() and row_id == message_id:
            break

    return "\n".join(diff_texts), files, hidden_ids


def _capture_files(base: Path, files: list[str]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for relative in files:
        full = (base / relative).resolve()
        exists = full.exists()
        if exists and full.is_file():
            snapshot[relative] = {
                "exists": True,
                "content": base64.b64encode(full.read_bytes()).decode("ascii"),
            }
            continue
        snapshot[relative] = {"exists": False, "content": ""}
    return snapshot


def _restore_files(base: Path, snapshot: dict[str, dict[str, Any]]) -> None:
    for relative, entry in snapshot.items():
        full = (base / relative).resolve()
        if entry.get("exists") is True:
            full.parent.mkdir(parents=True, exist_ok=True)
            content = str(entry.get("content") or "")
            full.write_bytes(base64.b64decode(content.encode("ascii")))
            continue
        if full.exists():
            full.unlink()


def _apply_revert(base: Path, diff_text: str) -> None:
    chunks = [chunk for chunk in diff_text.split("\n--- ") if chunk.strip()]
    patches = [
        chunk if chunk.startswith("--- ") else "--- " + chunk for chunk in chunks
    ]
    for patch in reversed(patches):
        from_path, to_path = _parse_diff_paths(patch)
        source_path = _clean_diff_path(from_path)
        target_path = _clean_diff_path(to_path)
        file_path = source_path or target_path
        if not file_path:
            continue

        full = (base / file_path).resolve()
        original = full.read_text(encoding="utf-8") if full.exists() else ""

        if from_path == "/dev/null":
            if full.exists():
                full.unlink()
            continue

        reversed_patch = _reverse_unified_diff(patch)
        restored = _apply_unified_diff(original, reversed_patch)
        if isinstance(restored, dict):
            raise ValueError(
                str(restored.get("error") or "Failed to apply reverse diff")
            )

        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(restored, encoding="utf-8")


def _summary_from_diffs(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "additions": sum(int(item.get("additions", 0) or 0) for item in diffs),
        "deletions": sum(int(item.get("deletions", 0) or 0) for item in diffs),
        "files": len(diffs),
        "diffs": diffs,
    }


def _diff_entries(diff_text: str, files: list[str]) -> list[dict[str, Any]]:
    chunks = [chunk for chunk in diff_text.split("\n--- ") if chunk.strip()]
    patches = [
        chunk if chunk.startswith("--- ") else "--- " + chunk for chunk in chunks
    ]
    fallback = iter(files)
    diffs: list[dict[str, Any]] = []
    for patch in patches:
        additions, deletions = _line_counts(patch)
        file_path = _extract_file_from_diff(patch) or next(fallback, "unknown")
        diffs.append(
            _build_file_diff(
                file_path=file_path,
                before="",
                after=patch,
                additions=additions,
                deletions=deletions,
            )
        )
    return diffs


def revert_session(
    core: Any,
    session_id: str,
    *,
    message_id: str,
    part_id: str | None = None,
) -> Optional[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Mark a session reverted and restore workspace state to before the selected range."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None
    if list_session_statuses(core).get(session_id, {}).get("type") != "idle":
        raise ValueError("Session must be idle before reverting")

    rows = get_session_messages(core, session_id)
    if rows is None:
        return None

    diff_text, files, hidden_ids = _collect_revert_diffs(rows, message_id, part_id)
    base = Path(_session_directory(core, session))
    snapshot_id = _snapshot_id()
    file_snapshot = _capture_files(base, files)
    if diff_text.strip():
        _apply_revert(base, diff_text)

    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    session.metadata = metadata
    metadata[REVERT_KEY] = {
        "messageID": message_id,
        **({"partID": part_id} if isinstance(part_id, str) and part_id.strip() else {}),
        "snapshot": snapshot_id,
        "diff": diff_text,
        "hiddenMessageIDs": hidden_ids,
    }
    metadata[REVERT_SNAPSHOT_KEY] = {
        "id": snapshot_id,
        "files": file_snapshot,
    }
    diffs = _diff_entries(diff_text, files)
    metadata[SUMMARY_KEY] = _summary_from_diffs(diffs)

    manager.mark_session_modified(session.id)
    manager.save_session(session)
    return _build_session_info(core, session, manager), diffs


def unrevert_session(
    core: Any, session_id: str
) -> Optional[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Restore files and clear revert metadata for a session."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None
    if list_session_statuses(core).get(session_id, {}).get("type") != "idle":
        raise ValueError("Session must be idle before restoring reverted changes")

    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    revert_info = metadata.get(REVERT_KEY)
    revert_snapshot = metadata.get(REVERT_SNAPSHOT_KEY)
    if not isinstance(revert_info, dict) or not isinstance(revert_snapshot, dict):
        return _build_session_info(core, session, manager), []

    snapshot_files = revert_snapshot.get("files")
    if isinstance(snapshot_files, dict):
        _restore_files(Path(_session_directory(core, session)), snapshot_files)

    metadata.pop(REVERT_KEY, None)
    metadata.pop(REVERT_SNAPSHOT_KEY, None)
    summary = metadata.pop(SUMMARY_KEY, None)

    manager.mark_session_modified(session.id)
    manager.save_session(session)
    diffs = summary.get("diffs") if isinstance(summary, dict) else []
    return _build_session_info(core, session, manager), diffs if isinstance(
        diffs, list
    ) else []
