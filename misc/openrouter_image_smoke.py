"""
Quick, standalone smoke test for OpenRouter vision via Penguin's APIClient.

Usage examples:
  python -m penguin.misc.openrouter_image_smoke \
      --url https://i.imgur.com/tn8MIFb.jpg \
      --model openai/gpt-4o-mini \
      --stream false

  # Test local-path encode path as well (downloads to a temp file)
  python -m penguin.misc.openrouter_image_smoke \
      --url https://i.imgur.com/tn8MIFb.jpg \
      --local true

Requires:
  - Environment: OPENROUTER_API_KEY=<key>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import tempfile
from pathlib import Path

import httpx  # type: ignore

from penguin.llm.model_config import ModelConfig
from penguin.llm.api_client import APIClient


def build_model_config(model: str | None) -> ModelConfig:
    """Create a ModelConfig suitable for OpenRouter with vision enabled."""
    model_id = model or os.environ.get("PENGUIN_MODEL", "openai/gpt-4o-mini")
    return ModelConfig(
        model=model_id,
        provider="openrouter",
        client_preference="openrouter",
        streaming_enabled=False,
        vision_enabled=True,
        max_tokens=1024,
        temperature=0.1,
    )


async def download_to_temp(url: str) -> Path:
    """Download URL to a temporary file and return its path."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        suffix = Path(url).suffix or ".jpg"
        fd, tmp_path = tempfile.mkstemp(prefix="penguin_img_", suffix=suffix)
        os.close(fd)
        Path(tmp_path).write_bytes(resp.content)
        return Path(tmp_path)


async def run_test(url: str, model: str | None, stream: bool, use_local: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("openrouter_image_smoke")

    mc = build_model_config(model)
    client = APIClient(mc)

    if use_local:
        local_path = await download_to_temp(url)
        logger.info(f"Downloaded test image to: {local_path}")
        # Use gateway's local encode path
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in one short sentence."},
                    {"type": "image_url", "image_path": str(local_path)},
                ],
            }
        ]
    else:
        # Pass-through URL variant
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in one short sentence."},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]

    logger.info(f"Requesting with model={mc.model}, stream={stream}, local={use_local}")
    out = await client.get_response(messages, stream=stream)
    print("\n=== Response ===\n" + (out or "<empty>"))


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRouter vision smoke test via Penguin")
    parser.add_argument("--url", required=True, help="Image URL to test")
    parser.add_argument("--model", default=None, help="Model id (default from env or fallback)")
    parser.add_argument("--stream", default="false", choices=["true", "false"], help="Enable streaming")
    parser.add_argument("--local", default="false", choices=["true", "false"], help="Download and send as local file")

    args = parser.parse_args()
    stream = args.stream.lower() == "true"
    use_local = args.local.lower() == "true"

    if "OPENROUTER_API_KEY" not in os.environ:
        print("[ERROR] OPENROUTER_API_KEY is not set in the environment.")
        raise SystemExit(1)

    asyncio.run(run_test(args.url, args.model, stream, use_local))


if __name__ == "__main__":
    main()


