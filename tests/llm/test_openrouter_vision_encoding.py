from __future__ import annotations

import base64

import pytest
from PIL import Image

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


@pytest.mark.asyncio
async def test_openrouter_vision_encoding_labels_transcoded_png_as_jpeg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fixture")
    image_path = tmp_path / "browser-screenshot.png"
    Image.new("RGB", (8, 6), color=(0, 0, 255)).save(image_path)
    gateway = OpenRouterGateway(
        ModelConfig(
            model="openai/gpt-5",
            provider="openrouter",
            client_preference="openrouter",
            api_key="sk-or-v1-fixture",
        )
    )

    processed = await gateway._process_messages_for_vision(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect screenshot"},
                    {"type": "image_url", "image_path": str(image_path)},
                ],
            }
        ]
    )

    image_url = processed[0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1])[:3] == b"\xff\xd8\xff"


@pytest.mark.asyncio
async def test_openrouter_vision_replaces_missing_image_with_text_part(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A deleted image file must not leak a raw image_path part to the provider.

    Regression: agents delete temporary screenshots after viewing them. The
    persisted ``{"type": "image_url", "image_path": ...}`` part was sent as-is
    on every later request, and OpenRouter rejected it with 400 "image_url
    content parts must carry an object image_url with a string url".
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fixture")
    missing = tmp_path / "deleted-review.png"
    gateway = OpenRouterGateway(
        ModelConfig(
            model="deepseek/deepseek-v4.1-flash-1017",
            provider="openrouter",
            client_preference="openrouter",
            api_key="sk-or-v1-fixture",
        )
    )

    processed = await gateway._process_messages_for_vision(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image artifact"},
                    {"type": "image_url", "image_path": str(missing)},
                ],
            }
        ]
    )

    parts = processed[0]["content"]
    for part in parts:
        if part.get("type") == "image_url":
            assert isinstance(part.get("image_url"), dict)
            assert isinstance(part["image_url"].get("url"), str)
        assert "image_path" not in part
    assert any(
        part.get("type") == "text" and str(missing) in part.get("text", "")
        for part in parts
    )


@pytest.mark.asyncio
async def test_openai_vision_replaces_missing_image_with_text_part(tmp_path) -> None:
    from penguin.llm.adapters.openai import OpenAIAdapter

    missing = tmp_path / "deleted-review.png"
    adapter = OpenAIAdapter.__new__(OpenAIAdapter)

    processed = await adapter._process_messages_for_vision(
        [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_path": str(missing)}],
            }
        ]
    )

    parts = processed[0]["content"]
    assert all("image_path" not in part for part in parts)
    assert all(
        isinstance(part.get("image_url"), dict)
        for part in parts
        if part.get("type") == "image_url"
    )
    assert any(str(missing) in part.get("text", "") for part in parts)
