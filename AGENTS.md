Fast Reference for Agents

Commands
- Install dev deps: pip install -e .[dev] (use uv/pipx if available)
- Lint (Ruff): ruff check . ; ruff format .
- Format (Black + isort profile via Ruff): black . ; ruff check --fix .
- Type hints policy: use typing, no strict mypy configured; prefer Pydantic types where relevant.
- Run all tests: pytest -q
- Run a single test file: pytest -q tests/test_api_client.py
- Run a single test by node id: pytest -q tests/test_api_client.py::test_basic_flow
- Core test suites: pytest tests -q ; pytest misc/tests -q (extra)
- Phase 1 test harness: python tests/run_phase1_tests.py
- Full repo tests (legacy/misc): python run_all_tests.py ; python misc/run_all_memory_tests.py
- Build wheel/sdist: python -m build
- Publish (manual): twine upload dist/*
- Dev web server: PORT=8080 uv run penguin-web
- Dev web server with reload: PORT=8080 DEBUG=true uv run penguin-web
- TUI against dev web server: uv run penguin --url http://127.0.0.1:8080 --no-web-autostart

Style and Conventions
- Follow .cursorrules at repo root. Key points: PEP 8, explicit > implicit, single responsibility, comprehensive type annotations, Google-style docstrings, robust exception handling, logging.
- Imports: ruff/isort with profile=black; order stdlib, third-party, first-party (penguin). Combine "as" imports; known-first-party = ["penguin"].
- Formatting: Black 88 col; Ruff line-length 88; quotes = double (ruff fmt). Target Python 3.9+ (ruff target 3.8, black target py39).
- Types: annotate all public functions and dataclasses; prefer precise types (dict[str, Any] over Dict). Use Pydantic models where appropriate.
- Naming Penguin: Just call it "Penguin", not "Penguin AI", or "Penguin AI Assistant". In some cases "Penguin Agent" are reasonable though.
- Naming: snake_case for functions/vars; PascalCase for classes; UPPER_SNAKE for constants; clear, descriptive names.
- Errors: raise specific exceptions, no bare except; add context; never swallow; log via logging with appropriate level.
- Logging: use logging.getLogger(__name__); avoid printing in library code.
- Tests: pytest, aim for high coverage; add async tests with pytest-asyncio where needed; keep unit tests deterministic. Tests go in tests/, NEVER in penguin/ source dirs.
- Files to avoid committing: see .gitignore; add .crush/ local artifacts.
- Docs: keep README and docs/ in sync when changing public API.

Architecture Boundaries
- PenguinCore (core.py): orchestrator ONLY. Delegates to Engine, ConversationManager, ToolManager, etc. Do NOT add business logic here.
- Engine (engine.py): owns the reasoning loop. Receives pre-constructed managers, no hidden globals.
- Routes (web/routes.py): thin HTTP layer. ALL business logic goes in web/services/*.py. Routes should be ~20 lines max per endpoint.
- Config (config.py): loading and merging only. Dataclass definitions belong in dedicated schema modules.
- Tools (tools/): each tool in its own file. tool_manager.py is a registry, not an implementation dump.
- Parser (utils/parser.py): action parsing only. Keep it focused.
- Public API: define __all__ in every public module. If it's not in __all__, it's internal.

Anti-Patterns (DO NOT do these)
- God files: no file should exceed ~2000 lines. If it does, extract. Current targets for decomposition: routes.py, core.py, tool_manager.py, parser.py.
- .bak files: NEVER commit .bak files. Git is your backup. Delete existing ones.
- old_* files: delete dead code, don't rename it. Git history preserves it.
- # type: ignore on valid imports: remove them. If mypy complains, fix the config, don't suppress.
- Commented-out imports: delete them. Git history has them.
- Bare Exception → return error string: raise PenguinError subclasses instead. See utils/errors.py for the pattern.
- Lazy imports via module-level globals: use a cached function or functools.lru_cache pattern instead.
- Non-Python assets in penguin/: no images, JSON data files, or logs in the package directory.
- Tests in source dirs: tests/ only. No test_*.py files under penguin/.
- sys.path manipulation: never add to sys.path in library code.

Patterns to Emulate
- Pydantic schemas: see agent/schema.py — Field() with descriptions, validators, factory methods, from __future__ import annotations.
- Error hierarchy: see utils/errors.py — PenguinError base with code/recoverable/suggested_action, specific subclasses.
- Security exceptions: see security/path_utils.py — custom hierarchy, full typing, proper docstrings.
- Service extraction: see web/services/conversations.py — thin functions that build response payloads.
- Constants: see constants.py — env vars with defaults, helper functions, no magic numbers in logic.
- State machines: see llm/stream_handler.py — dataclasses + enums, clean state transitions.

Notes
- Cursor rules: this repo has .cursorrules at root; agents should adhere to it.
- Copilot rules: none found under .github/copilot-instructions.md.
- Entry points: penguin (CLI), penguin-web (API/web), see pyproject [project.scripts].
- Verification scripts and local web surface checks should prefer port `9000` by default unless another non-reserved port is explicitly needed.
- Avoid `5***` ports for ad hoc local verification because some are reserved by Apple on macOS.
