# Run-scoped Link inference

An isolated Penguin runtime can use `LINK_INFERENCE_RUNTIME_TOKEN` for Link inference.
Link issues this credential for one run and enforces its workspace, model, permissions, and lifetime.
Penguin sends it as an `Authorization: Bearer` header.
It does not send service-authentication headers in this mode.

For an isolated runtime:

1. Set `LINK_INFERENCE_BASE_URL` to the trusted Link broker URL.
2. Set `LINK_INFERENCE_RUNTIME_TOKEN` to the run credential from the trusted launcher.
3. Leave `LINK_INFERENCE_SERVICE_TOKEN` and `LINK_INTERNAL_SERVICE_SECRET` unset.
4. Keep provider keys and Link service secrets outside the runtime.
5. Set `LINK_INFERENCE_PROTOCOL=chat_completions` for Link's scoped broker.

Malformed or mixed credentials cause a configuration error.
Penguin does not fall back to broader credentials after an authorization failure.
Request previews and configuration representations exclude both credential types.
The existing service-token configuration remains available for trusted servers.

This change does not provide container isolation or credential renewal.
The Link control plane owns those operations.

## Broker restart recovery

Run-scoped Chat Completions calls regenerate an interrupted model attempt after a
transport failure or an HTTP 429, 502, 503, or 504 response. This does not restart
the task. The replacement uses the same conversation input, including completed
tool results, and a new inference request ID. Link rechecks authority and reserves
credit for that new call. The old uncertain charge is not erased or reused.

Each replacement can incur provider cost and produce different text. This is not
resumption of the original provider generation, and it is not exactly-once model
billing. Set an explicit workspace/provider budget for live testing.

Penguin buffers each model attempt's text and reasoning until the attempt has a
terminal response. Failed partial output and tool calls are discarded. This
trades token-by-token display for an unambiguous transcript; completed tool calls
still run through the normal engine. Already-completed tools are not rerun by the
retry loop.

Connection retries use backoff without a retry-count deadline. There is no default
idle-read timeout. Explicit cancellation interrupts both the request and backoff.
Authorization, budget, validation, and explicit in-band provider errors are not
treated as transport loss. Service-token and Responses calls retain their existing
non-replay behavior.

This recovers a broker connection while Penguin remains alive. It does not recover
a crashed Penguin process, replay an exact lost generation, or reconcile an
uncertain provider charge automatically.
