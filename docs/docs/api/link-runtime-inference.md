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

Malformed or mixed credentials cause a configuration error.
Penguin does not fall back to broader credentials after an authorization failure.
Request previews and configuration representations exclude both credential types.
The existing service-token configuration remains available for trusted servers.

This change does not provide container isolation or credential renewal.
The Link control plane owns those operations.
