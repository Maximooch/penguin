"""Safe, payload-free inventory of noisy and rotated server logs."""

from pathlib import Path

from scripts.server_log_inventory import inventory


def test_inventory_ignores_embedded_errors_and_does_not_export_payloads(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-PAYLOAD-DO-NOT-EXPORT"
    lines = [
        "TypeError: quoted program output, not a server diagnostic\n",
        "2026-10-14 02:05:00,001 - root - ERROR - quoted tool error\n",
        "2026-10-14 02:05:00,001 - penguin.core - WARNING - "
        f"stream.finalize.scope_miss session={secret}\n",
        "2026-10-14 02:05:00,002 - penguin.system.session_manager - ERROR - "
        f"Error saving session {secret}: [Errno 28] No space left on device\n",
        "2026-10-14 02:05:00,003 - uvicorn.error - ERROR - request failed\n",
    ]
    (tmp_path / "penguin-web-test.txt").write_text("".join(lines))
    (tmp_path / "unrelated.txt").write_text("".join(lines))
    result = inventory(tmp_path)
    assert result["files"] == 1
    assert result["diagnostic_records"] == 3
    assert result["ignored_lines"] == 2
    assert result["categories"] == {
        "other": 1,
        "storage_full": 1,
        "stream_scope_miss": 1,
    }
    assert secret not in repr(result)
    assert result["scanned_bytes"] == len("".join(lines).encode())


def test_inventory_rotations_invalid_utf8_and_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "penguin-web-test.txt.1"
    source.write_bytes(
        b"2026-10-14 02:05:00,001 - penguin.tools.process_runtime - ERROR - "
        b"Process capture failed: \xff\n"
    )
    (tmp_path / "penguin-web-link.txt").symlink_to(source)
    result = inventory(tmp_path)
    assert result["files"] == 1
    assert result["categories"] == {"process_capture_failure": 1}


def test_empty_inventory(tmp_path: Path) -> None:
    assert inventory(tmp_path)["diagnostic_records"] == 0
