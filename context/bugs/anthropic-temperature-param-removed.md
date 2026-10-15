# Native Anthropic requests fail with `temperature` TypeError (September 28, 2026)

Every native Anthropic chat request failed before reaching the provider:

```
engine.llm_attempt.start model=claude-opus-5-5 provider=anthropic streaming=True
engine.llm_attempt.error retryable=False category=ErrorCategory.RUNTIME
error=Error during Anthropic streaming: AsyncMessages.create() got an unexpected keyword argument 'temperature'
```

The TUI surfaced this as `[Streaming Error: AsyncMessages.create() got an unexpected keyword argument 'temperature']`
and the session was auto-titled `Error: LLM request failed. Diagnostic ID: ...`.

## Root cause

The installed SDK is `anthropic 1.4.0`, whose Messages surface no longer declares
any sampling controls: `temperature`, `top_p`, and `top_k` appear nowhere in the
package. `AsyncMessages.create` validates keyword arguments client side, so the
always-present `"temperature"` key in `AnthropicAdapter` request params raised a
`TypeError` on every streaming and non-streaming call, for every Claude model.

Two further defects were found while making Anthropic work again:

1. **Streaming stop reason and usage were never captured.** `message_delta` now
   carries `stop_reason` inside `delta` (`chunk.delta.stop_reason`) and usage on
   the event itself; the adapter required a top-level `chunk.stop_reason`, so the
   branch never matched. The intended fallback, `stream.get_final_message()`,
   does not exist on the raw stream returned by `messages.create(stream=True)`
   (only on the `messages.stream()` manager), so usage stayed `{}` for every
   streaming request and `finish_reason` silently defaulted to `STOP`.
2. **Vision capability was misreported.** `supports_vision()` tested for
   `"claude-3"` in the model id, so current models such as `claude-opus-5-5` and
   `claude-sonnet-4-6` reported no vision support, and the CLI refused image
   attachments for them.

The existing tests did not catch any of this because they stub the SDK client
(`AnthropicMessagesStub`), so request kwargs were never validated against the
real SDK surface.

## Fixes

- `penguin/llm/adapters/anthropic.py` no longer forwards `temperature` (kept in
  the adapter signature for interface compatibility).
- New `_create_messages()` / `_filter_messages_create_params()` route every
  `messages.create` call through an introspection check of the installed SDK
  signature, dropping unsupported keys with a warning instead of failing the
  request. This also protects against future SDK surface changes.
- `message_delta` handling reads a nested `delta.stop_reason`, `message_start`
  and `message_delta` usage payloads are merged, and the absent
  `get_final_message` fallback is skipped instead of logged as a warning.
- `supports_vision()` now treats every Claude 3+ model as vision capable and
  only excludes first/second generation ids.
- `tests/llm/test_anthropic_sdk_param_compat.py` asserts forwarded kwargs are a
  subset of the installed SDK signature, that `temperature` never reaches the
  SDK, and that streaming stop reason/usage are captured from current event
  shapes.

## Verification

- `pytest tests/llm` — 405 passed.
- Against the real SDK client pointed at a dead port, both paths now get past
  client-side validation and fail only with a retryable
  `APIConnectionError`/`ErrorCategory.NETWORK`, instead of a non-retryable
  `TypeError`.

## Open items (not changed)

- `pyproject.toml` pins `anthropic>=0.3.0`, which admits both the old and the
  new SDK surface. The adapter is now tolerant of both, but a deliberate floor
  bump would be the stronger signal; it requires regenerating `uv.lock`, which
  already has unrelated local modifications.
- `penguin/web/services/provider_credentials.py` carries the comment
  `#Need to remove Anthropic from the list given their new TOS`, so Anthropic is
  intentionally being de-emphasized. Nothing in this fix contradicts that
  direction; it only stops the native adapter from failing for users who still
  have a key configured.
