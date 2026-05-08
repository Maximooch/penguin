from __future__ import annotations

from pathlib import Path

from penguin.web.routes import _extract_paths_from_parts


def test_extract_paths_accepts_direct_image_url_image_path(tmp_path: Path) -> None:
    image = tmp_path / "Screenshot 2026-05-07 at 4.39.01 PM.png"
    image.write_bytes(b"fake")

    context_files, image_paths = _extract_paths_from_parts(
        [{"type": "image_url", "image_path": str(image)}],
        directory=str(tmp_path),
    )

    assert context_files == []
    assert image_paths == [str(image)]


def test_extract_paths_accepts_nested_image_url_path(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")

    context_files, image_paths = _extract_paths_from_parts(
        [{"type": "image_url", "image_url": {"image_path": str(image)}}],
        directory=str(tmp_path),
    )

    assert context_files == []
    assert image_paths == [str(image)]


def test_extract_paths_keeps_opencode_file_image_shape(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake")

    context_files, image_paths = _extract_paths_from_parts(
        [
            {
                "type": "file",
                "mime": "image/png",
                "source": {"path": str(image)},
            }
        ],
        directory=str(tmp_path),
    )

    assert context_files == []
    assert image_paths == [str(image)]
