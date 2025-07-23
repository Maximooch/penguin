# Suggested Minor Improvements

Below is a categorized list of small, non-breaking tasks for the Penguin project. The project is now published as the `penguin-ai` package on PyPI.

## Documentation
1. Fix typos in README introduction.
2. Add missing docstring to `penguin.__init__`.
3. Document environment variables in `docs/README.md`.
4. Add short usage section to `docs/docs/intro.md`.
5. Add comment headers describing classes in `penguin/core.py`.
6. Provide example API requests in `docs/docs/api_reference`.
7. Document memory providers optional dependencies in README.
8. Move large markdown images to `docs/static`.
9. Document `TASK_COMPLETION_PHRASE` in configuration docs.
10. Add `pytest` section on running selected tests.
11. Document how to disable telemetry/events in config.
12. Update minimal Python version to 3.8 in docs.
13. Document `local_task` module in docs/usage section.
14. Provide a short architecture diagram in README.
15. Add example custom tool definition in `docs/docs/advanced/custom_tools.md`.
16. Document expected JSON format for tool results.
17. Create `docs/docs/system/events.md` describing event bus.
18. Add note about running `uvicorn` with `--reload` during development.
19. Document manual token counting in `docs/usage`.
20. Provide example YAML config for local runs.
21. Clarify license section in README about AGPL requirements.
22. Add docstring examples for `Engine.run_task` parameters.
23. Update configuration docs with new `vision_enabled` field.
24. Clarify difference between `PenguinCore.create` and `PenguinCore()`.
25. Document `--help` output for CLI entry points.
26. Add short mention of Textual interface in README features.
27. Document how to run docs site with Docker in docs/README.
28. Clarify comment around `ResourceSnapshot` fields.
29. Provide link to example workflows in docs.
30. Document how to swap LLM providers using config.
31. Add link to official FastAPI docs in API README.
32. Update `CHANGELOG` with latest patch information.
33. Expand README table of contents with new sections.
34. Clarify docstring of ``PenguinCore.process`` return value.
35. Document memory usage expectations in advanced docs.
36. Fix typos in `docs/docs/advanced/roadmap.md`.
37. Document how to contribute translations for docs.
38. Clarify difference between `penguin` and `penguin-web` packages.
39. Document `ToolManager` config options in docs.
40. Add table summarizing CLI commands in docs.
41. Add docstring for `PenguinCore.start_run_mode` parameters.
42. Document environment variables required by `PenguinCore.create`.
43. Add example usage of `PenguinCore.get_token_usage` in docs.
44. Document `EngineSettings.wall_clock_stop_seconds` in README.
45. Document `TokenBudgetStop` behavior in advanced docs.
46. Document lazy-loading design in `tool_manager.py`.
47. Document how to add custom tools in `tools/README.md`.
48. Document parser-supported action tags in docs.
49. Add example for custom action in docs.
50. Document conversation checkpoint flow in `system` docs.
51. Document session rollover logic in `session_manager.py`.
52. Document advanced CLI flags in `chat/cli.py`.
53. Document `model_selector.py` usage in README.
54. Document environment variables used by chat UI.
55. Provide example asynchronous chat script in examples folder.
56. Add system prompt version history file.
57. Document `checkpoint_manager` persistence design.
58. Document default file locations in `file_session.py`.
59. Provide example plugin for additional stop conditions.
60. Document `workspace` module subfolders in README.
61. Document how to customize logging format.
62. Add missing `__init__.py` docstrings in `chat` package.
63. Document expected folder layout under `workspace/`.
64. Document memory providers in `docs/system/memory.md`.
65. Document release process in `CONTRIBUTING.md`.
66. Add coverage badge to README.
67. Provide example structured tool response in docs.
68. Document local debugging steps in `docs/usage/debug.md`.
69. Provide reference output of example tasks.
70. Document how to run integration tests.
71. Document style guides in `docs/contributing/style.md`.
72. Clarify role of `workspace.py` module in README.
73. Add cross-links between docs sections.
74. Document environment variable for debug mode.
75. Provide style example for docstrings.
76. Add quick start video link.
77. Document custom session types.
78. Add screenshot of web UI to README.
79. Document `PenguinCore.save` method.
80. Mention support channels in README.
81. Document `get_memory_usage` helper.
82. Clarify difference between synchronous and asynchronous tool use.
83. Provide glossary of terms in docs.
84. Add docstring example for configuration dataclass.
85. Add table summarizing memory providers.
86. Document metrics endpoint usage.
87. Document `run_server.py` CLI flags.
88. Document how to contribute bug reports.
89. Document manual installation from GitHub.
90. Document keyboard shortcuts in CLI.
91. Provide table describing event types.
92. Add reference to community-contributed tools.

## Setup & Packaging
1. Add example `.env.example` file.
2. Update `pyproject.toml` with project homepage link.
3. Add default log level setting in config.
4. Update `.gitignore` with common editor temp files.
5. Create `scripts/bootstrap.sh` for common setup steps.
6. Add `ruff` pre-commit hook example in README.
7. Update `requirements.txt` comment about optional packages.
8. Add missing license headers to new source files.
9. Include `make lint` command in contributing guide.
10. Set default logging level to INFO when running `run_server.py`.
11. Fix inconsistent newline at end of `penguin/config.yml`.
12. Remove unused `IMG.jpg` from package data.
13. Add default `workspace` directory creation to setup script.
14. Add ``format`` command to ``scripts`` for consistent styling.
15. Add `pre-commit` config file example to repo.
16. Remove duplicate `requirements-setup.txt` lines.
17. Provide sample `.tool-versions` for pyenv users.
18. Split tool definitions into separate YAML file for clarity.
19. Add sample docker compose file for running with server.
20. Add check for Python version at startup.
21. Add poetry lock file to `.gitignore`.
22. Document `make release` script usage.
23. Provide local dev configuration example for VSCode.
24. Add instructions for building docs with `make docs`.
25. Add sample `.dockerignore` file.
26. Include package classifiers for supported Python versions.
27. Add pre-commit check for `mypy`.
28. Add example `.flake8` config.
29. Provide requirements for optional GPU features.
30. Document how to publish package to internal PyPI.

## Code Quality
1. Remove unused imports in `penguin/agent/base.py`.
2. Add type hints for parameters in `penguin.api.server.init_core`.
3. Normalize logging format strings across modules.
4. Replace `print` statements in `penguin/api/server.py` with logging.
5. Split long functions in `penguin/local_task/manager.py` for clarity.
6. Add `__all__` declarations to modules under `penguin/chat`.
7. Replace bare `except` blocks with `Exception` handling.
8. Add missing `return` type hints in `penguin/local_task/manager.py`.
9. Refactor repeated path joins using `Path` operations.
10. Remove commented-out code from `penguin/core.py`.
11. Use `Iterable` instead of `list` where appropriate in interfaces.
12. Simplify boolean checks in `engine.py`.
13. Replace `logger.warn` with `logger.warning` calls.
14. Remove stray debugging prints in `tests/debug_imports.py`.
15. Add `__repr__` method to `Task` dataclass for readability.
16. Improve variable naming in `penguin/api/routes.py`.
17. Replace repeated `datetime.now()` calls with variable.
18. Replace `print` statements in `local_task/manager.py` with logger.
19. Reword comments for `StopCondition` subclasses.
20. Replace string concatenation with f-strings in server startup message.
21. Use `pydantic.Field` for default values with descriptions.
22. Improve error message for missing API key on startup.
23. Use more descriptive variable names in engine streaming helper.
24. Add missing newline at end of `run_server.py`.
25. Replace numeric status codes with enums in APIs.
26. Remove duplicate `asyncio` import from `core.py`.
27. Replace string formatting with f-strings in `core.py` warnings.
28. Add type hints for `PenguinCore.register_progress_callback`.
29. Extract repeated path checks in `core.py` to helper method.
30. Ensure `PenguinCore.reset_state` closes open tasks gracefully.
31. Add property method for `Engine.current_iteration`.
32. Normalize logger names in `engine.py`.
33. Split long `run_task` function into smaller private methods.
34. Use `dataclass` for `StopCondition` implementations.
35. Add missing `__all__` in `engine.py` for public classes.
36. Use `functools.partial` for repeated callback patterns.
37. Mark internal attributes of `ToolManager` with leading underscore.
38. Add check for nonexistent workspace path in `ToolManager`.
39. Use `Path` operations in `ToolManager.execute_command`.
40. Replace `print` debug lines with logging in `ToolManager`.
41. Validate tool parameters with pydantic in `ToolManager`.
42. Extract regex patterns in `parser.py` to constants.
43. Add more granular error messages for parse failures.
44. Ensure `ActionExecutor` methods return detailed status.
45. Use `Enum.auto()` for `ActionType` values.
46. Refactor `parse_action` to handle nested tags robustly.
47. Add `__repr__` to `Conversation` classes for debugging.
48. Use `Path` in `file_manager.py` instead of `os.path`.
49. Replace manual JSON dumps with `json.dumps` indenting.
50. Add type annotations in `logging.py` for log functions.
51. Use `datetime.fromisoformat` in `state.parse_iso_datetime`.
52. Extract UI constants from `chat/interface.py`.
53. Replace `exit()` calls with `sys.exit` for clarity.
54. Validate YAML before loading in `context_loader.py`.
55. Use `typing.Final` for constants in `system/state.py`.
56. Add error codes enum for parser exceptions.
57. Remove unused function `workspace_search` placeholder.
58. Use dataclass for `Message` in conversation model.
59. Use `pydantic.BaseModel` for config structures.
60. Convert `parser.py` prints to logger calls.
61. Provide typed callback protocol classes.
62. Add check in `Engine.run_task` for empty prompts.
63. Clean up stray TODO comments in `engine.py`.
64. Use `anyio.sleep` for compatibility in async code.
65. Refactor repeated path constants into settings module.
66. Replace mutable default arguments with `None` and set inside functions.
67. Consolidate repeated try/except logic into helper function.
68. Add typed `NamedTuple` for message pairs.
69. Extract CLI argument parsing into separate module.
70. Use `pathlib.Path` across entire codebase instead of `os.path`.
71. Remove redundant return statements.
72. Enforce consistent quoting style with `black`.
73. Use `contextlib.suppress` for expected exceptions.
74. Replace manual string indexing with slicing.
75. Add generics to container classes.
76. Convert simple classes to dataclasses.
77. Replace default `dict` initializations with `collections.defaultdict`.
78. Refactor configuration loading to use dataclasses.
79. Enforce explicit relative imports within packages.
80. Add check for `None` values before logging.
81. Remove trailing whitespace in source files.
82. Consolidate repeated time calculations into helper function.
83. Add module-level docstrings describing package purpose.
84. Factor out repetitive path constants in tests.
85. Add type checking to CI workflow.

## Testing
1. Use `pathlib.Path` consistently in test helpers.
2. Add simple unit test for `EngineSettings` defaults.
3. Ensure all async functions are awaited in tests.
4. Use `tempfile` in tests instead of hardcoded paths.
5. Update tests to use f-strings for clarity.
6. Add stub for `EventBus` in tests to reduce duplication.
7. Use `AsyncExitStack` in tests to clean up resources.
8. Parameterize API base URL in `api_client` tests.
9. Add small test for `parse_action` error handling.
10. Replace deprecated `pytest.mark.asyncio` usage in tests.
11. Expand unit tests for `LocalTaskManager` state transitions.
12. Add quickstart section for running tests in CI.
13. Add integration test for `Engine.run_single_turn`.
14. Add unit tests for lazy initialization branches.
15. Add unit tests for `context_loader.load_context`.
16. Add example conversation YAML files for testing.
17. Use `tempfile.NamedTemporaryFile` for file session tests.
18. Add minimal test harness for CLI prompts.
19. Add integration tests for CLI error paths.
20. Mock network calls in API tests to speed up suite.
21. Add fixture for temporary config files.
22. Parameterize tests for multiple Python versions.
23. Add test ensuring `Workspace` directory cleanup.
24. Add snapshot tests for chat UI output.
25. Test `run_server` with multiple workers.
26. Add fuzz tests for parser.
27. Add coverage report step in CI.
28. Add unit test for CPU usage logging.

## Engine & Core
1. Adjust default `max_iterations` to 3 for faster examples.
2. Add property to retrieve active tool names.
3. Expose engine start time via property.
4. Add method to gracefully stop all tasks.
5. Validate configuration on initialization.
6. Add callback for run loop iteration events.
7. Support custom stop conditions via plugin.
8. Add method to export conversation history as JSON.
9. Cache loaded models between runs.
10. Add context manager for running core in a temporary directory.
11. Add optional metrics collection.

## CLI & Interface
1. Add code sample for using `penguin-web` CLI entry point.
2. Add bash completion script for CLI.
3. Add `--log-level` flag.
4. Support reading prompts from stdin.
5. Add `--dry-run` option for previewing tasks.
6. Improve help text formatting.
7. Add interactive config wizard.
8. Add colorized diff display for updates.
9. Provide example theming options.
10. Add support for customizing prompt prefixes.
11. Add CLI subcommand to show config path.

## Tools
1. Ensure `ToolManager` errors go through `log_error` consistently.
2. Add abstract base class for asynchronous tools.
3. Cache tool results on disk.
4. Add health check for external service tools.
5. Support environment-specific tool configuration.
6. Add built-in text translation tool.

## Performance
1. Optimize `ConversationManager.save` to avoid extra file writes.
2. Inline small helper `Engine._check_stop` into main loop for speed.
3. Add simple benchmark script for `Engine` loop.
4. Add caching for loaded configuration files in `core.py`.
5. Use `asyncio.gather` for concurrent tool initialization.
6. Cache snapshots in `snapshot_manager` to reduce disk I/O.
7. Move CLI import timing behind debug flag.
8. Add progress update throttling in `interface.py`.
9. Use lazy imports in `model_selector.py` to speed startup.
10. Add small benchmark for `context_window.trim`.
11. Use `functools.cache` for parser compiled regex.
12. Cache HTTP session objects.
13. Use `orjson` for faster JSON parsing.
14. Avoid expensive deep copies in state snapshotting.
15. Use memory-mapped files for large logs.
16. Buffer file writes in snapshot manager.
17. Profile startup time of CLI.
18. Add lazy property evaluation for config.
19. Use `functools.lru_cache` for context retrieval.
20. Evaluate JIT compilation with `numba`.
21. Add asynchronous file I/O for conversation logs.

## Features
1. Add optional `progress_bar` argument to `Engine.run_task`.
2. Add `async` versions of heavy I/O tool executions.
3. Provide configuration option for checkpoint frequency.
4. Add command alias `penguin chat` for interactive mode.
5. Provide optional colored output toggle in chat UI.
6. Add `--list-models` option to CLI.
7. Add CLI flag to toggle progress bars.
8. Add property `conversation_length` to `ConversationSystem`.
9. Add `--version` option to CLI.
10. Add `ToolManager.list_tools` method for introspection.
11. Add optional CPU usage logging in `Engine`.
12. Add webhook notification support.
13. Provide plugin system for custom memory providers.
14. Allow saving and restoring sessions via CLI.
15. Add interactive tutorial mode.
16. Support running tools within Docker containers.

