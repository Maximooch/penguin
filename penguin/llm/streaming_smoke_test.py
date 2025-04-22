import asyncio
import os
import sys
import logging
from pathlib import Path
from typing import Optional

# ---- Configurable parameters ----
MODEL_ID = os.getenv("STREAM_TEST_MODEL", "openrouter/quasar-alpha")
PROVIDER = "openrouter"  # fixed for now
API_ENV = "OPENROUTER_API_KEY"

# Vision test image
TEST_IMAGE_PATH: Optional[str] = os.getenv("STREAM_TEST_IMAGE_PATH")  # local path if any
TEST_IMAGE_URL: Optional[str] = os.getenv("STREAM_TEST_IMAGE_URL", "https://raw.githubusercontent.com/Maximooch/penguin/main/penguin/IMG.jpg")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Ensure project root on path
root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root))

from penguin.llm.openrouter_gateway import OpenRouterGateway  # type: ignore
from penguin.llm.model_config import ModelConfig  # type: ignore


async def stream_text(gateway: OpenRouterGateway):
    logger.info("--- Streaming text completion ---")
    messages = [{"role": "user", "content": "Write a short limerick about Penguins."}]
    collected = []

    def cb(chunk: str):
        print(chunk, end="", flush=True)
        collected.append(chunk)

    final = await gateway.get_response(messages, stream=True, stream_callback=cb)
    print("\n\n[stream finished]\n")
    logger.info("Chunks collected: %d chars vs final %d chars", len("".join(collected)), len(final))


async def stream_vision(gateway: OpenRouterGateway):
    if not gateway.model_config.vision_enabled:
        logger.warning("Vision not enabled, skipping vision streaming test.")
        return

    content_parts = [{"type": "text", "text": "Describe this image in one sentence."}]

    img_source = None
    if TEST_IMAGE_PATH and Path(TEST_IMAGE_PATH).is_file():
        img_source = TEST_IMAGE_PATH
        # encode as base64 similar to openrouter test script
        import base64, io
        from PIL import Image  # type: ignore

        img = Image.open(img_source)
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG")
        encoded = base64.b64encode(buf.getvalue()).decode()
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        })
        logger.info("Using local image %s", img_source)
    else:
        img_source = TEST_IMAGE_URL
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": img_source},
        })
        logger.info("Using image URL %s", img_source)

    messages = [{"role": "user", "content": content_parts}]
    collected = []

    def cb(chunk: str):
        print(chunk, end="", flush=True)
        collected.append(chunk)

    final = await gateway.get_response(messages, stream=True, stream_callback=cb)
    print("\n\n[vision stream finished]\n")
    logger.info("Vision stream collected %d chars", len("".join(collected)))


async def main():
    api_key = os.getenv(API_ENV)
    if not api_key:
        logger.error("Environment variable %s not set", API_ENV)
        sys.exit(1)

    config = ModelConfig(
        model=MODEL_ID,
        provider=PROVIDER,
        client_preference="openrouter",
        api_key=api_key,
        streaming_enabled=True,
        vision_enabled=True,
    )

    gateway = OpenRouterGateway(config, site_url="https://linkai.chat", site_title="Penguin")

    print("=== Streaming Smoke Test ===")
    print(f"Model : {MODEL_ID}")
    print("---------------------------\n")

    await stream_text(gateway)
    await stream_vision(gateway)
    print("All streaming tests complete.")


if __name__ == "__main__":
    asyncio.run(main()) 