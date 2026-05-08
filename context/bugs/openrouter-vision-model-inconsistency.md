# OpenRouter Vision Model Inconsistency

## Status

Open / provider-specific.

## Observed On

2026-05-06 during browser-harness screenshot visibility testing.

## Summary

Penguin's multimodal `image_path` plumbing works with modern OpenAI vision-capable models, but OpenRouter model behavior is inconsistent across advertised or candidate models.

## Evidence

- `gpt-5.5` via OpenAI/Codex path successfully read a real browser-harness screenshot and extracted the expected text: `browser-harness smoke`.
- `openai/gpt-5.5` via OpenRouter successfully read the same real browser-harness screenshot and extracted the expected text: `browser-harness smoke`.
- `moonshotai/kimi-k2.6` via OpenRouter successfully handled a synthetic image smoke test, but one real browser-harness screenshot request returned empty assistant content.
- `z-ai/glm-5.1` via OpenRouter returned a provider/model capability error indicating no usable image-input endpoint for that model path.

## Impact

This is not evidence that Penguin cannot see screenshots. It is evidence that OpenRouter vision-capability metadata and provider routing cannot be trusted uniformly. Tests that prove image visibility should use known vision-capable model IDs and should treat OpenRouter failures as model/provider compatibility failures unless the same image fails on OpenAI direct.

## Recommendation

- Keep a small provider/model vision smoke matrix in docs or tests.
- Prefer `gpt-5.5` direct or `openai/gpt-5.5` via OpenRouter for deterministic screenshot-read validation.
- Do not assume every OpenRouter model listed as current/general-purpose accepts image input.
- If native artifact-to-message bridging is added, test it against at least one direct provider and one OpenRouter provider model.
