import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional


# ---------- Configuration ----------

# Default widely available model; override with OPENAI_TEST_MODEL if needed
TEST_MODEL_ID = os.getenv("OPENAI_TEST_MODEL", "gpt-5")

# Optional: reasoning-capable model; override with OPENAI_TEST_REASONING_MODEL
REASONING_MODEL_ID = os.getenv("OPENAI_TEST_REASONING_MODEL", "gpt-5")
# Optional: set effort level: low | medium | high
REASONING_EFFORT = os.getenv("OPENAI_TEST_REASONING_EFFORT", "high").lower()

EXPECTED_API_KEY_ENV = "OPENAI_API_KEY"

# Vision image sources (local path preferred, else URL)
TEST_IMAGE_PATH: Optional[str] = str(
    Path(__file__).resolve().parents[2] / "docs" / "static" / "img" / "penguin.png"
)
TEST_IMAGE_URL: Optional[str] = (
    "https://raw.githubusercontent.com/Maximooch/penguin/main/penguin/IMG.jpg"
)


# ---------- Import setup ----------

# Ensure project root is importable when running standalone
project_root = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(project_root))

from penguin.llm.adapters.openai import OpenAIAdapter  # type: ignore  # noqa: E402
from penguin.llm.model_config import ModelConfig  # type: ignore  # noqa: E402


# ---------- Logging ----------

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ---------- Test helpers ----------

def _require_api_key() -> str:
    api_key = os.getenv(EXPECTED_API_KEY_ENV)
    if not api_key:
        logger.error(
            f"Required environment variable '{EXPECTED_API_KEY_ENV}' is not set."
        )
        raise SystemExit(1)
    return api_key


def _build_adapter(model_id: str, *, vision_enabled: Optional[bool] = None) -> OpenAIAdapter:
    api_key = _require_api_key()
    mc = ModelConfig(
        model=model_id,
        provider="openai",
        client_preference="native",
        api_key=api_key,
        max_tokens=400,
        temperature=0.5,
        vision_enabled=vision_enabled,
        streaming_enabled=True,
        reasoning_enabled=True,
        reasoning_effort=(REASONING_EFFORT if REASONING_EFFORT in ["low", "medium", "high"] else None),
    )
    return OpenAIAdapter(mc)


# ---------- Individual tests ----------

async def run_text_completion(adapter: OpenAIAdapter) -> None:
    logger.info("--- Non-Streaming Text Test ---")
    messages = [
        {"role": "user", "content": "Explain async/await in Python in two sentences."}
    ]
    resp = await adapter.get_response(messages, stream=False)
    print(resp)
    print("-" * 30)


async def run_streaming_completion(adapter: OpenAIAdapter) -> None:
    logger.info("--- Streaming Text Test (prints as it streams) ---")
    messages = [
        {"role": "user", "content": "Write a short haiku about a penguin."}
    ]

    def stream_callback(chunk: str, message_type: str = "assistant") -> None:
        # Distinguish reasoning vs content if the model supports reasoning
        if message_type == "reasoning":
            print(f"\n[R] {chunk}", end="", flush=True)
        else:
            print(chunk, end="", flush=True)

    final_text = await adapter.get_response(
        messages, stream=True, stream_callback=stream_callback
    )
    print("\n--- End of Stream ---")
    logger.info("Streaming produced %d characters.", len(final_text))
    print("-" * 30)


async def run_system_message_test(adapter: OpenAIAdapter) -> None:
    logger.info("--- System Message Test ---")
    messages = [
        {"role": "system", "content": "You speak like a pirate."},
        {"role": "user", "content": "Describe vector databases."},
    ]
    resp = await adapter.get_response(messages, stream=False)
    print(resp)
    print("-" * 30)


async def run_vision_completion(adapter: OpenAIAdapter) -> None:
    logger.info("--- Vision Test ---")
    path = Path(TEST_IMAGE_PATH) if TEST_IMAGE_PATH else None

    parts = [{"type": "text", "text": "Describe this image very briefly."}]
    if path and path.is_file():
        # Use local file path; adapter will encode to a data URI
        parts.append({"type": "image_url", "image_path": str(path)})
        logger.info("Using local image: %s", path)
    elif TEST_IMAGE_URL:
        parts.append({"type": "image_url", "image_url": {"url": TEST_IMAGE_URL}})
        logger.info("Using remote image URL: %s", TEST_IMAGE_URL)
    else:
        logger.info("No image provided; skipping vision test.")
        return

    # Ensure the adapter/model supports vision
    if not adapter.supports_vision():
        logger.warning("Vision not enabled for this model; skipping vision test.")
        return

    messages = [{"role": "user", "content": parts}]
    resp = await adapter.get_response(messages, stream=False)
    print(resp)
    print("-" * 30)


# ---------- Main ----------

async def main() -> None:
    print("=========================================")
    print("      OpenAI Adapter Standalone Test")
    print("=========================================")
    print(f"Primary Model: {TEST_MODEL_ID}")
    print(f"Reasoning Model (optional): {REASONING_MODEL_ID}")
    print(f"Ensure '{EXPECTED_API_KEY_ENV}' is set.")
    print("-----------------------------------------")

    # Primary adapter (gpt-4o by default)
    adapter = _build_adapter(TEST_MODEL_ID, vision_enabled=True)
    await run_text_completion(adapter)
    await run_streaming_completion(adapter)
    await run_system_message_test(adapter)
    await run_vision_completion(adapter)

    # Optional reasoning-capable adapter
    try:
        reasoning_adapter = _build_adapter(REASONING_MODEL_ID, vision_enabled=False)
        logger.info("--- Reasoning Model Streaming Test ---")
        await run_streaming_completion(reasoning_adapter)
    except SystemExit:
        raise
    except Exception as e:
        logger.warning("Skipping reasoning model test: %s", e)


if __name__ == "__main__":
    asyncio.run(main())


