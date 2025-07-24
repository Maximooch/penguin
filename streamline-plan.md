# Streamlining Duplicate Core Code

The repository currently ships two versions of `PenguinCore`:

1. `penguin/core.py` – the production implementation.
2. `misc/core_copy.py` – an older snapshot of the same class used for reference.

There is also a shim module at `core.py` that re-exports `penguin.penguin.core`.

This duplication makes the codebase harder to maintain and leads to confusion when importing the correct class.

## Proposed Plan

1. **Remove the unused copy**
   - Delete `misc/core_copy.py` or move relevant comments into documentation.
   - This file is not referenced anywhere and contains outdated logic.

2. **Consolidate import path**
   - Update all imports to use `penguin.core` directly.
   - Once confirmed, remove the shim `core.py` to avoid redundancy.

3. **Centralise event & progress callbacks**
   - Both `PenguinCore` and the CLI manage lists of progress callbacks and UI handlers. Create a small module (e.g. `penguin.events`) that owns this registration logic so all components share a single implementation.
   - The core should publish events via this module, and the CLI or web layers subscribe through it.

4. **Simplify Core initialisation**
   - Break the large `create` factory into smaller helper functions for logging setup, model config creation, and tool manager initialisation. This reduces repeated code across other modules that attempt similar initialisation.

5. **Document the streamlined API**
   - Ensure docs reference only the consolidated module and show the unified event system.

Cleaning up these duplicates will reduce maintenance overhead and make it clearer how to interact with `PenguinCore`.
