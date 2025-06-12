# Suggested Minor Improvements

Below is a list of 100 small and non-breaking improvements that could be addressed across the project.

1. Fix typos in README introduction.
2. Add missing docstring to `penguin.__init__`.
3. Remove unused imports in `penguin/agent/base.py`.
4. Add type hints for parameters in `penguin.api.server.init_core`.
5. Document environment variables in `docs/README.md`.
6. Normalize logging format strings across modules.
7. Add example `.env.example` file.
8. Replace `print` statements in `penguin/api/server.py` with logging.
9. Use `pathlib.Path` consistently in test helpers.
10. Update `pyproject.toml` with project homepage link.
11. Split long functions in `penguin/local_task/manager.py` for clarity.
12. Ensure `ToolManager` errors go through `log_error` consistently.
13. Add short usage section to `docs/docs/intro.md`.
14. Add default log level setting in config.
15. Add `__all__` declarations to modules under `penguin/chat`.
16. Replace bare `except` blocks with `Exception` handling.
17. Update `.gitignore` with common editor temp files.
18. Optimize `ConversationManager.save` to avoid extra file writes.
19. Add comment headers describing classes in `penguin/core.py`.
20. Provide example API requests in `docs/docs/api_reference`.
21. Add simple unit test for `EngineSettings` defaults.
22. Inline small helper `Engine._check_stop` into main loop for speed.
23. Document memory providers optional dependencies in README.
24. Add code sample for using `penguin-web` CLI entry point.
25. Create `scripts/bootstrap.sh` for common setup steps.
26. Move large markdown images to `docs/static`.
27. Ensure all async functions are awaited in tests.
28. Add missing `return` type hints in `penguin/local_task/manager.py`.
29. Refactor repeated path joins using `Path` operations.
30. Document `TASK_COMPLETION_PHRASE` in configuration docs.
31. Add `ruff` pre-commit hook example in README.
32. Remove commented-out code from `penguin/core.py`.
33. Use `Iterable` instead of `list` where appropriate in interfaces.
34. Update `requirements.txt` comment about optional packages.
35. Add `pytest` section on running selected tests.
36. Document how to disable telemetry/events in config.
37. Simplify boolean checks in `engine.py`.
38. Replace `logger.warn` with `logger.warning` calls.
39. Add missing license headers to new source files.
40. Use `tempfile` in tests instead of hardcoded paths.
41. Include `make lint` command in contributing guide.
42. Update minimal Python version to 3.8 in docs.
43. Document `local_task` module in docs/usage section.
44. Provide a short architecture diagram in README.
45. Add example custom tool definition in `docs/docs/advanced/custom_tools.md`.
46. Document expected JSON format for tool results.
47. Remove stray debugging prints in `tests/debug_imports.py`.
48. Add `__repr__` method to `Task` dataclass for readability.
49. Update tests to use f-strings for clarity.
50. Create `docs/docs/system/events.md` describing event bus.
51. Adjust default `max_iterations` to 3 for faster examples.
52. Improve variable naming in `penguin/api/routes.py`.
53. Add note about running `uvicorn` with `--reload` during development.
54. Document manual token counting in `docs/usage`.
55. Provide example YAML config for local runs.
56. Replace repeated `datetime.now()` calls with variable.
57. Add stub for `EventBus` in tests to reduce duplication.
58. Set default logging level to INFO when running `run_server.py`.
59. Clarify license section in README about AGPL requirements.
60. Add docstring examples for `Engine.run_task` parameters.
61. Replace `print` statements in `local_task/manager.py` with logger.
62. Update configuration docs with new `vision_enabled` field.
63. Clarify difference between `PenguinCore.create` and `PenguinCore()`.
64. Reword comments for `StopCondition` subclasses.
65. Fix inconsistent newline at end of `penguin/config.yml`.
66. Document `--help` output for CLI entry points.
67. Add short mention of Textual interface in README features.
68. Remove unused `IMG.jpg` from package data.
69. Use `AsyncExitStack` in tests to clean up resources.
70. Document how to run docs site with Docker in docs/README.
71. Parameterize API base URL in `api_client` tests.
72. Add default `workspace` directory creation to setup script.
73. Clarify comment around `ResourceSnapshot` fields.
74. Provide link to example workflows in docs.
75. Add small test for `parse_action` error handling.
76. Replace string concatenation with f-strings in server startup message.
77. Document how to swap LLM providers using config.
78. Add link to official FastAPI docs in API README.
79. Update `CHANGELOG` with latest patch information.
80. Expand README table of contents with new sections.
81. Add ``format`` command to ``scripts`` for consistent styling.
82. Clarify docstring of ``PenguinCore.process`` return value.
83. Use `pydantic.Field` for default values with descriptions.
84. Document memory usage expectations in advanced docs.
85. Add simple benchmark script for `Engine` loop.
86. Replace deprecated `pytest.mark.asyncio` usage in tests.
87. Add `pre-commit` config file example to repo.
88. Improve error message for missing API key on startup.
89. Fix typos in `docs/docs/advanced/roadmap.md`.
90. Document how to contribute translations for docs.
91. Remove duplicate `requirements-setup.txt` lines.
92. Clarify difference between `penguin` and `penguin-web` packages.
93. Use more descriptive variable names in engine streaming helper.
94. Expand unit tests for `LocalTaskManager` state transitions.
95. Provide sample `.tool-versions` for pyenv users.
96. Add missing newline at end of `run_server.py`.
97. Document `ToolManager` config options in docs.
98. Add quickstart section for running tests in CI.
99. Replace numeric status codes with enums in APIs.
100. Add table summarizing CLI commands in docs.

101. Add docstring for `PenguinCore.start_run_mode` parameters.
102. Remove duplicate `asyncio` import from `core.py`.
103. Document environment variables required by `PenguinCore.create`.
104. Replace string formatting with f-strings in `core.py` warnings.
105. Add type hints for `PenguinCore.register_progress_callback`.
106. Extract repeated path checks in `core.py` to helper method.
107. Ensure `PenguinCore.reset_state` closes open tasks gracefully.
108. Add caching for loaded configuration files in `core.py`.
109. Use `asyncio.gather` for concurrent tool initialization.
110. Add example usage of `PenguinCore.get_token_usage` in docs.
111. Document `EngineSettings.wall_clock_stop_seconds` in README.
112. Add property method for `Engine.current_iteration`.
113. Normalize logger names in `engine.py`.
114. Split long `run_task` function into smaller private methods.
115. Add optional `progress_bar` argument to `Engine.run_task`.
116. Use `dataclass` for `StopCondition` implementations.
117. Add missing `__all__` in `engine.py` for public classes.
118. Document `TokenBudgetStop` behavior in advanced docs.
119. Use `functools.partial` for repeated callback patterns.
120. Add integration test for `Engine.run_single_turn`.
121. Document lazy-loading design in `tool_manager.py`.
122. Mark internal attributes of `ToolManager` with leading underscore.
123. Add check for nonexistent workspace path in `ToolManager`.
124. Use `Path` operations in `ToolManager.execute_command`.
125. Replace `print` debug lines with logging in `ToolManager`.
126. Add `async` versions of heavy I/O tool executions.
127. Split tool definitions into separate YAML file for clarity.
128. Document how to add custom tools in `tools/README.md`.
129. Validate tool parameters with pydantic in `ToolManager`.
130. Add unit tests for lazy initialization branches.
131. Document parser-supported action tags in docs.
132. Extract regex patterns in `parser.py` to constants.
133. Add more granular error messages for parse failures.
134. Ensure `ActionExecutor` methods return detailed status.
135. Add example for custom action in docs.
136. Use `Enum.auto()` for `ActionType` values.
137. Refactor `parse_action` to handle nested tags robustly.
138. Document conversation checkpoint flow in `system` docs.
139. Add `__repr__` to `Conversation` classes for debugging.
140. Use `Path` in `file_manager.py` instead of `os.path`.
141. Add unit tests for `context_loader.load_context`.
142. Cache snapshots in `snapshot_manager` to reduce disk I/O.
143. Provide configuration option for checkpoint frequency.
144. Replace manual JSON dumps with `json.dumps` indenting.
145. Document session rollover logic in `session_manager.py`.
146. Add type annotations in `logging.py` for log functions.
147. Use `datetime.fromisoformat` in `state.parse_iso_datetime`.
148. Add example conversation YAML files for testing.
149. Document advanced CLI flags in `chat/cli.py`.
150. Move CLI import timing behind debug flag.
151. Add command alias `penguin chat` for interactive mode.
152. Extract UI constants from `chat/interface.py`.
153. Add progress update throttling in `interface.py`.
154. Provide optional colored output toggle in chat UI.
155. Document `model_selector.py` usage in README.
156. Use lazy imports in `model_selector.py` to speed startup.
157. Add `--list-models` option to CLI.
158. Replace `exit()` calls with `sys.exit` for clarity.
159. Document environment variables used by chat UI.
160. Provide example asynchronous chat script in examples folder.
161. Add system prompt version history file.
162. Document `checkpoint_manager` persistence design.
163. Use `tempfile.NamedTemporaryFile` for file session tests.
164. Add small benchmark for `context_window.trim`.
165. Document default file locations in `file_session.py`.
166. Validate YAML before loading in `context_loader.py`.
167. Use `typing.Final` for constants in `system/state.py`.
168. Add error codes enum for parser exceptions.
169. Provide example plugin for additional stop conditions.
170. Remove unused function `workspace_search` placeholder.
171. Document `workspace` module subfolders in README.
172. Add CLI flag to toggle progress bars.
173. Use dataclass for `Message` in conversation model.
174. Add property `conversation_length` to `ConversationSystem`.
175. Document how to customize logging format.
176. Add missing `__init__.py` docstrings in `chat` package.
177. Use `pydantic.BaseModel` for config structures.
178. Add minimal test harness for CLI prompts.
179. Document expected folder layout under `workspace/`.
180. Convert `parser.py` prints to logger calls.
181. Use `functools.cache` for parser compiled regex.
182. Document memory providers in `docs/system/memory.md`.
183. Add sample docker compose file for running with server.
184. Provide typed callback protocol classes.
185. Add check in `Engine.run_task` for empty prompts.
186. Document release process in `CONTRIBUTING.md`.
187. Add coverage badge to README.
188. Clean up stray TODO comments in `engine.py`.
189. Provide example structured tool response in docs.
190. Add `--version` option to CLI.
191. Document local debugging steps in `docs/usage/debug.md`.
192. Use `anyio.sleep` for compatibility in async code.
193. Add `ToolManager.list_tools` method for introspection.
194. Provide reference output of example tasks.
195. Document how to run integration tests.
196. Add check for Python version at startup.
197. Refactor repeated path constants into settings module.
198. Add optional CPU usage logging in `Engine`.
199. Document style guides in `docs/contributing/style.md`.
200. Clarify role of `workspace.py` module in README.
