# LLM Runtime Package Hygiene TODO

## Objective

- Clean runtime package directories so backups, ad hoc test files, and stale artifacts do not live beside production code.
- Make packaging boundaries clearer for contributors and tooling.
- Reduce confusion about what is canonical runtime code versus scratch/test material.

## Why This Exists

- `penguin/llm/` currently includes `.bak` files and ad hoc `test_*.py` files inside the runtime package.
- Similar hygiene issues exist elsewhere in runtime directories.
- This does not necessarily break execution, but it muddies ownership and increases maintenance noise.

## Audit Evidence

- `penguin/llm/client.py.bak`
- `penguin/llm/openrouter_gateway.py.bak`
- `penguin/llm/test_link_integration.py.bak`
- `penguin/llm/test1.py`
- `penguin/llm/test_openai_adapter.py`
- `penguin/llm/test_openrouter_gateway.py`
- `penguin/llm/test_litellm_gateway.py`

## Progress Snapshot

- [ ] Inventory non-runtime artifacts inside package directories
- [ ] Decide whether each should move to `tests/`, `context/archive/`, or deletion
- [ ] Keep any intentional runtime self-tests clearly named and justified
- [ ] Tighten packaging exclusions if needed

## Checklist

### Phase 1 - Inventory
- [ ] List `.bak`, backup, scratch, and test-like files inside runtime packages
- [ ] Determine whether each file is authoritative, duplicated, or dead

### Phase 2 - Cleanup
- [ ] Move real tests into `tests/`
- [ ] Move historical artifacts into `context/archive/` if worth keeping
- [ ] Delete dead files that exist only as fossilized confusion

### Phase 3 - Prevention
- [ ] Add ignore/tooling guidance so backup files do not accumulate in runtime packages
- [ ] Consider packaging/test guards that fail on stray backup artifacts

## Verification Targets

- package import smoke tests
- targeted test suite after file moves
- packaging/build checks if applicable

## Notes

- Git is already the backup system.
- Runtime directories do not need cosplay backups.
