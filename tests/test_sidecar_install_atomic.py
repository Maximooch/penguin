"""An interrupted sidecar copy never leaves a file at the final path (SM-72)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.cli import opencode_launcher

if TYPE_CHECKING:
    from pathlib import Path


def test_interrupted_copy_leaves_no_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "extracted" / "penguin-tui"
    source.parent.mkdir()
    source.write_bytes(b"x" * 1024)
    target = tmp_path / "cache" / "penguin-tui"

    def partial_copy(src, dst, *args, **kwargs):
        with open(dst, "wb") as handle:
            handle.write(b"x" * 10)
        raise OSError("interrupted")

    monkeypatch.setattr(opencode_launcher.shutil, "copy2", partial_copy)

    with pytest.raises(OSError, match="interrupted"):
        opencode_launcher._install_sidecar_binary(source, target)

    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_complete_copy_installs_the_binary(tmp_path: Path) -> None:
    source = tmp_path / "penguin-tui-src"
    source.write_bytes(b"binary")
    target = tmp_path / "cache" / "penguin-tui"

    opencode_launcher._install_sidecar_binary(source, target)

    assert target.read_bytes() == b"binary"
    assert [path.name for path in target.parent.iterdir()] == ["penguin-tui"]
