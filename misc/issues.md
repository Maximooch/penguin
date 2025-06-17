# Penguin – Runtime Issues (latest test run)

Below are the noteworthy warnings and issues that appeared when running `python -m penguin.misc.test1` on 2025-06-17.

## 1. Lance provider – Unknown index type `ivf_pq`

* **Logs**: repeated lines like:
  ```
  WARNING:penguin.memory.providers.lance_provider:Failed to create index: Unknown index type ivf_pq
  ```
* **Impact**: Vector-memory indexing probably falls back to a slower path or is disabled, reducing search/recall performance.
* **Likely cause**: Local `lance` or `pyarrow` package is older than the version that introduced the `ivf_pq` index type.
* **Next steps**:
  1. Pin/upgrade `lance` to ≥ 0.8.0 (or the version that supports IVF-PQ).
  2. Verify by running the same command and ensuring the warning disappears.

## 2. Browser support warning

* **Log**:
  ```
  WARNING:root:browser-use temporarily disabled for Python 3.8-3.10 compatibility. Use PyDoll instead.
  ```
* **Impact**: The `browser` tool is disabled, so agents cannot render or scrape web pages in real browsers; they must rely on the `pydoll` headless fallback.
* **Next steps**:
  1. Decide if true browser support is needed for current tasks.
  2. If yes, bring the codebase up to Python 3.11+ compatibility or adjust the browser module to support 3.8-3.10.

## 3. Minor: noisy debug output

* **Observation**: Core/ToolManager initialization prints a progress bar and multiple DEBUG messages.
* **Impact**: No functional issue, but it clutters stdout and interferes with clean stream output.
* **Next steps**: Gate progress bar & debug logs behind a `verbose` flag or use the logging module with configurable levels.

## 4. Config → Memory section not passed through to ToolManager

* **Symptoms**: Despite `config.yml` specifying `memory: provider: faiss`, runtime still initializes the **LanceDB** provider (see repeated `Failed to create index: Unknown index type ivf_pq` warnings).
* **Root cause hypothesis**: `PenguinCore` converts the loaded `Config` dataclass to `config.__dict__` before handing it to `ToolManager`.  The dataclass currently does **not** include a `memory` attribute, so that subsection of the YAML never reaches `ToolManager`, which then receives an empty dict and falls back to provider-auto-detection (preferring LanceDB).
* **Impact**: Incorrect provider selected, extra dependency requirements, noisy warnings, and potentially slower memory operations.
* **Next steps**:
  1. Add a `memory: dict = field(default_factory=dict)` attribute to the `Config` dataclass and populate it in `load_config`.
  2. Alternatively (or additionally) make `PenguinCore` pass the *raw YAML dict* to `ToolManager` instead of `config.__dict__`.
  3. Verify that after the change the startup logs indicate `Creating faiss memory provider` and the LanceDB warnings disappear.

---

_Keep this file updated as new issues are discovered._ 