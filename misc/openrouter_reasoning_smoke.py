"""
Standalone reasoning payload smoke test for OpenRouter via Penguin's APIClient.

Focus: text-only messages (no vision). Captures streamed reasoning (if provided)
and final assistant content to help isolate gateway issues around reasoning flags
and message formatting.

Example:
  OPENROUTER_API_KEY=... \
  python -m penguin.misc.openrouter_reasoning_smoke \
      --prompt "Explain the Turing Test in one paragraph." \
      --model openai/gpt-4o-mini \
      --stream true

Notes:
  - This uses Penguin's APIClient and the OpenRouter gateway.
  - If the selected model supports reasoning tokens and the gateway/model config
    enables them, streamed chunks with message_type == "reasoning" will appear.
  - No images are involved; content is text-only to isolate reasoning behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import List, Dict, Any

from penguin.llm.model_config import ModelConfig
from penguin.llm.api_client import APIClient


def build_model_config(model: str | None, temperature: float, max_tokens: int) -> ModelConfig:
    model_id = model or os.environ.get("PENGUIN_MODEL", "openai/gpt-4o-mini")
    # Enable streaming off by default here (overridden by --stream flag)
    # Vision disabled to ensure we test text-only reasoning path.
    return ModelConfig(
        model=model_id,
        provider="openrouter",
        client_preference="openrouter",
        streaming_enabled=False,
        vision_enabled=False,
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def run_once(prompt: str, model: str | None, stream: bool, temperature: float, max_tokens: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("openrouter_reasoning_smoke")

    mc = build_model_config(model, temperature, max_tokens)
    client = APIClient(mc)

    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
            ],
        }
    ]

    reasoning_buf: list[str] = []
    content_buf: list[str] = []

    async def cb(chunk: str, message_type: str = "assistant") -> None:
        # Collect both reasoning and content segments to inspect ordering/phase changes
        if message_type == "reasoning":
            reasoning_buf.append(chunk)
        else:
            content_buf.append(chunk)

    logger.info(f"Sending request (model={mc.model}, stream={stream})")
    result = await client.get_response(messages, stream=stream, stream_callback=cb)

    # Print streamed buffers and final result (for non-streaming path)
    if reasoning_buf:
        print("\n--- Streamed Reasoning ---\n" + "".join(reasoning_buf))
    else:
        print("\n--- Streamed Reasoning ---\n<none>")

    if content_buf:
        print("\n--- Streamed Content ---\n" + "".join(content_buf))
    else:
        print("\n--- Streamed Content ---\n<none>")

    # result will hold the final content text from the gateway
    print("\n--- Final Content (return value) ---\n" + (result or "<empty>"))


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenRouter reasoning smoke test (text-only)")
    # Prompt can be provided via -p/--prompt or as positional words; falls back to stdin if piped
    parser.add_argument("prompt", nargs="*", help="User prompt (positional)")
    parser.add_argument("-p", "--prompt", dest="prompt_opt", help="User prompt (flag)")
    parser.add_argument("-m", "--model", default=None, help="Model id (default from env or fallback)")
    # Stream toggles
    parser.add_argument("--stream", dest="stream", action="store_true", help="Enable streaming (default)")
    parser.add_argument("--no-stream", dest="stream", action="store_false", help="Disable streaming")
    parser.set_defaults(stream=True)
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=1024, help="Max tokens for completion")

    args = parser.parse_args()
    # Resolve prompt from flags, positional, or stdin
    prompt_text = args.prompt_opt or (" ".join(args.prompt).strip() if args.prompt else None)
    if not prompt_text:
        try:
            import sys
            if not sys.stdin.isatty():
                prompt_text = sys.stdin.read().strip()
        except Exception:
            prompt_text = None

    if not prompt_text:
        print("[ERROR] Missing prompt. Provide with -p/--prompt, positional text, or pipe via stdin.")
        raise SystemExit(2)

    if "OPENROUTER_API_KEY" not in os.environ:
        print("[ERROR] OPENROUTER_API_KEY is not set in the environment.")
        raise SystemExit(1)

    asyncio.run(run_once(prompt_text, args.model, args.stream, args.temperature, args.max_tokens))


if __name__ == "__main__":
    main()


