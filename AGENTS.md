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

Style and Conventions
- Follow .cursorrules at repo root. Key points: PEP 8, explicit > implicit, single responsibility, comprehensive type annotations, Google-style docstrings, robust exception handling, logging.
- Imports: ruff/isort with profile=black; order stdlib, third-party, first-party (penguin). Combine "as" imports; known-first-party = ["penguin"].
- Formatting: Black 88 col; Ruff line-length 88; quotes = double (ruff fmt). Target Python 3.9+ (ruff target 3.8, black target py39).
- Types: annotate all public functions and dataclasses; prefer precise types (dict[str, Any] over Dict). Use Pydantic models where appropriate.
- Naming Penguin: Just call it "Penguin", not "Penguin AI", or "Penguin AI Assistant". In some cases "Penguin Agent" are reasonable though.
- Naming: snake_case for functions/vars; PascalCase for classes; UPPER_SNAKE for constants; clear, descriptive names.
- Errors: raise specific exceptions, no bare except; add context; never swallow; log via logging with appropriate level.
- Logging: use logging.getLogger(__name__); avoid printing in library code.
- Tests: pytest, aim for high coverage; add async tests with pytest-asyncio where needed; keep unit tests deterministic.
- Files to avoid committing: see .gitignore; add .crush/ local artifacts.
- Docs: keep README and docs/ in sync when changing public API.

Notes
- Cursor rules: this repo has .cursorrules at root; agents should adhere to it.
- Copilot rules: none found under .github/copilot-instructions.md.
- Entry points: penguin (CLI), penguin-web (API/web), see pyproject [project.scripts].
