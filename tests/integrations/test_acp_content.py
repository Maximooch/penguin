"""Attachment validation and native image input for ACP."""

import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.schema import (
    BlobResourceContents,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    TextResourceContents,
)
from PIL import Image
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.content import prepare_prompt
from penguin.integrations.acp.server import PenguinACPAgent


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_image_becomes_persisted_native_input(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    core.model_config = SimpleNamespace(vision_enabled=True)
    core.process = AsyncMock(return_value={"assistant_response": "red"})
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    try:
        assert (await agent.initialize(1)).agent_capabilities.prompt_capabilities.image
        sid = (await agent.new_session(str(tmp_path))).session_id
        block = ImageContentBlock(
            type="image", mime_type="image/png", data=base64.b64encode(png()).decode()
        )
        await agent.prompt(sid, [block])
        payload = core.process.call_args.args[0]
        from pathlib import Path

        image_path = Path(payload["image_paths"][0])
        assert image_path.read_bytes() == png()
        assert image_path.is_relative_to(core.store.base_path)
        assert (
            agent._registry.history(core.store.load_session(sid))[0].content.type
            == "image"
        )
    finally:
        agent.close()
    assert image_path.exists()  # Later model turns still reference this attachment.


@pytest.mark.parametrize(
    "data,mime",
    [
        ("not base64", "image/png"),
        ("aGVsbG8=", "image/png"),
        ("aGVsbG8=", "image/svg+xml"),
    ],
)
def test_bad_images_rejected(tmp_path, data, mime):
    with pytest.raises(RequestError):
        prepare_prompt(
            [ImageContentBlock(type="image", data=data, mime_type=mime)],
            tmp_path,
            tmp_path / "assets",
            allow_images=True,
        )


def test_embedded_text_is_context_not_remote_fetch(tmp_path):
    block = EmbeddedResourceContentBlock(
        type="resource",
        resource=TextResourceContents(
            uri="https://example.invalid/file", text="content", mime_type="text/plain"
        ),
    )
    result = prepare_prompt([block], tmp_path, tmp_path / "assets", allow_images=False)
    assert "Embedded resource (untrusted context)" in result
    assert "content" in result
    assert not (tmp_path / "assets").exists()


def test_embedded_binary_is_preserved_without_execution(tmp_path):
    block = EmbeddedResourceContentBlock(
        type="resource",
        resource=BlobResourceContents(
            uri="client:///binary",
            blob=base64.b64encode(b"opaque bytes").decode(),
            mime_type="application/octet-stream",
        ),
    )
    result = prepare_prompt([block], tmp_path, tmp_path / "assets", allow_images=False)
    assert "Attached binary resource" in result
    assert next((tmp_path / "assets").glob("*.bin")).read_bytes() == b"opaque bytes"


def test_attachment_size_checked_before_decode(tmp_path):
    block = ImageContentBlock(
        type="image", mime_type="image/png", data="a" * 14_000_000
    )
    with pytest.raises(RequestError):
        prepare_prompt([block], tmp_path, tmp_path / "assets", allow_images=True)
    assert not (tmp_path / "assets").exists()
