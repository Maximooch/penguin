# LLM Stack Boundary Cleanup TODO

## Objective

- Clarify responsibilities across the LLM stack so provider-specific logic stops leaking upward into orchestration and routing layers.
- Reduce abstraction overlap between high-level client paths and provider/gateway implementations.
- Make the LLM pipeline easier to trace when requests fail.

## Why This Exists

- The LLM stack is spread across multiple large files with overlapping responsibilities.
- `penguin/llm/openrouter_gateway.py` is large (~92 KB in the repo scan).
- `penguin/web/routes.py` is even larger (~249 KB), which raises the risk that API routing, orchestration, and provider-specific behavior are bleeding together.

## Audit Evidence

- `penguin/llm/api_client.py`
- `penguin/llm/client.py`
- `penguin/llm/provider_adapters.py`
- `penguin/llm/openrouter_gateway.py`
- `penguin/web/routes.py`
- `penguin/web/app.py`
- `penguin/web/services/`

## Progress Snapshot

- [ ] Map exact responsibilities of each LLM-facing module
- [ ] Identify duplicate orchestration paths and normalization layers
- [ ] Pull provider-specific logic down toward adapters/gateways
- [ ] Keep web routing thin where possible
- [ ] Preserve current external API behavior while reducing internal sprawl

## Checklist

### Phase 1 - Map the Current Stack
- [ ] Document who owns:
  - model selection
  - request shaping
  - provider failover
  - retries/timeouts
  - streaming normalization
  - tool-call normalization
  - HTTP/web route concerns
- [ ] Flag duplicate or conflicting ownership

### Phase 2 - Draw Better Boundaries
- [ ] Keep route handlers focused on transport/auth/request validation
- [ ] Keep provider quirks inside provider adapters/gateways
- [ ] Keep shared normalization in one place, not three

### Phase 3 - Reduce Monolith Hotspots
- [ ] Split the highest-churn portions of `openrouter_gateway.py`
- [ ] Split the highest-churn portions of `penguin/web/routes.py`
- [ ] Add internal module docs for the new boundaries

## Verification Targets

- `tests/test_api_client.py`
- web API tests
- streaming tests
- provider-specific integration tests
- manual traceability review for one end-to-end request path

## Notes

- Big files are not automatically bad.
- Big files with mixed responsibilities usually are.
