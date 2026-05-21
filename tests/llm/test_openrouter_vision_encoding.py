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
