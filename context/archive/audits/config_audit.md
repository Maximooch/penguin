# Penguin Config System Audit

## Executive Summary
The config system has **circular dependencies** and **multiple loading paths** that cause the first-run model selection bug. The root cause is that `Config.load_config()` returns a `Config` object, but `_initialize_core_components_globally` expects a dict, causing it to fall back to module-level `DEFAULT_MODEL` which was set at import time before the user config existed.

---

## 1. Config Loading Architecture

### 1.1 Module-Level Config Loading (config.py)

**Line 690**: `config = load_config()`
- Called at module import time
- Returns a dict (not Config object)
- Used for `WORKSPACE_PATH` and other module-level constants

**Lines 756-757**: 
```python
_MODEL = config.get('model', {}) if isinstance(config.get('model'), dict) else {}
_API = config.get('api', {}) if isinstance(config.get('api'), dict) else {}
```

**Lines 862-863**: `DEFAULT_MODEL` and `DEFAULT_PROVIDER` computed from `_MODEL`
```python
DEFAULT_MODEL = os.getenv("PENGUIN_DEFAULT_MODEL", _MODEL.get("default")) or "openai/gpt-5"
DEFAULT_PROVIDER = os.getenv("PENGUIN_DEFAULT_PROVIDER", _MODEL.get("provider", "openai"))
```

### 1.2 Config Class Loading (Config.load_config())

**Line 1381**: `def load_config(cls, config_path: Optional[Path] = None) -> "Config":`
- Class method that returns a `Config` dataclass instance
- Calls module-level `load_config()` to get dict data
- Converts dict to `Config` object with nested dataclasses

**Line 1395**: `config_data = load_config()` - calls module-level function

### 1.3 CLI Loading (cli/cli.py)

**Line 437**: `_loaded_config = Config.load_config()`
- Returns `Config` object (not dict)
- Stored in global variable

**Lines 472-501**: Attempts to extract model_dict from various config types
- Handles callable model(), property model, and dict
- **Missing**: Handling for `Config` dataclass with `model_config` attribute

---

## 2. The Bug: First-Run Model Selection

### Scenario Flow

1. **First import** (line 690): `config = load_config()` returns `{}` (no user config yet)
2. **Line 862**: `DEFAULT_MODEL = "openai/gpt-5"` (fallback because _MODEL is empty)
3. **Setup wizard runs**: Creates `~/.config/penguin/config.yml` with `model: default: moonshotai/kimi-k2.5`
4. **After setup**: Code tries to reload config
5. **Line 437**: `_loaded_config = Config.load_config()` returns `Config` object with `model_config.model = "moonshotai/kimi-k2.5"`
6. **Lines 472-501**: Checks for `model` attribute on Config object
   - `hasattr(_loaded_config, "model")` returns `True` (it's a property)
   - But `callable(getattr(_loaded_config, "model", None))` behavior depends on implementation
   - **Issue**: The code expects `_loaded_config.model` to return a dict, but Config.model property may behave differently
7. **If extraction fails**: Falls back to `_pc.DEFAULT_MODEL` which is still `"openai/gpt-5"`

### Root Cause Analysis

The fundamental issue is **timing and type mismatch**:

1. **Module-level constants** (`DEFAULT_MODEL`) are set at import time based on empty config
2. **Config object** has a different structure than expected:
   - `Config.model_config` is a `ModelConfig` object
   - `Config.model` is a property that returns a dict
   - But the extraction logic in cli.py may not handle this correctly
3. **Reload strategy** is flawed:
   - Module reload doesn't work because `config` variable shadows the module
   - Direct attribute updates to globals don't affect already-created objects

---

## 3. Problems Identified

### Problem 1: Type Confusion
- `load_config()` (module-level) returns `dict`
- `Config.load_config()` returns `Config` dataclass
- Code in cli.py tries to handle both but the logic is fragile

### Problem 2: Module-Level Side Effects
- Lines 690, 756-757, 862-863 execute at import time
- Cannot be reloaded cleanly because they depend on module-level execution

### Problem 3: Circular Dependencies
- `Config.load_config()` imports `ModelConfig` inside the method to avoid circular imports
- This suggests architectural coupling issues

### Problem 4: Multiple Config Representations
Same config data exists in multiple formats:
- Raw dict from YAML
- `Config` dataclass
- Module-level constants (`DEFAULT_MODEL`, `WORKSPACE_PATH`)
- Individual variables (`_MODEL`, `_API`)

### Problem 5: No Config Invalidation
- Once `_loaded_config` is set in cli.py, there's no clean way to refresh it
- The global state pattern makes it hard to propagate changes

---

## 4. Recommended Solutions

### Option A: Fix Current Approach (Minimal Change)

In `cli/cli.py`, ensure proper extraction from `Config` objects:

```python
# After setup completes, explicitly re-read config
from penguin.config import Config
fresh_config = Config.load_config()
globals()['_loaded_config'] = fresh_config

# In _initialize_core_components_globally, add explicit Config handling:
if hasattr(_loaded_config, 'model_config'):
    # It's a Config dataclass
    _model_cfg = _loaded_config.model_config
    model_dict = {
        'default': _model_cfg.model if _model_cfg else None,
        'provider': _model_cfg.provider if _model_cfg else None,
        # ... other fields
    }
```

### Option B: Config Manager Pattern (Better)

Create a proper config manager that supports hot-reloading:

```python
# penguin/config_manager.py
class ConfigManager:
    _instance = None
    _config = None

    @classmethod
    def get(cls):
        if cls._config is None:
            cls.reload()
        return cls._config

    @classmethod
    def reload(cls):
        from penguin.config import Config
        cls._config = Config.load_config()
        return cls._config

    @classmethod
    def get_model(cls):
        cfg = cls.get()
        if cfg and cfg.model_config:
            return cfg.model_config.model
        return os.getenv("PENGUIN_DEFAULT_MODEL", "openai/gpt-5")
```

### Option C: Dependency Injection (Best Long-term)

Stop using global config state. Pass config explicitly:

```python
# Instead of global _loaded_config
def _initialize_core_components_globally(config: Config = None):
    if config is None:
        from penguin.config import Config
        config = Config.load_config()
    # Use config directly, not globals
```

---

## 5. Immediate Fix Recommendation

**Combine Options A and B**:

1. **Fix extraction logic** in `_initialize_core_components_globally` to handle `Config` objects properly
2. **Add ConfigManager** for clean reloading after setup
3. **Remove module-level DEFAULT_MODEL dependency** from cli initialization

The key insight: **Don't rely on module-level constants that were set at import time**. Always read from the Config object directly.

---

## 6. Testing Strategy

1. **Unit test**: Verify Config.load_config() returns correct model after file is created
2. **Integration test**: Simulate first-run scenario (no config → setup → verify model)
3. **Regression test**: Ensure existing config files still work

---

## 7. Files Requiring Changes

1. `penguin/cli/cli.py` - Fix extraction logic, add proper reload
2. `penguin/config.py` - Consider adding ConfigManager or fixing reload behavior
3. Potentially: Create `penguin/config_manager.py` for clean abstraction

---

## Conclusion

The config system works correctly for reading files, but the **integration between config loading and CLI initialization** is broken. The CLI assumes config is loaded once at startup, but the setup wizard creates a config file after that initial load.

The fix requires either:
1. Re-loading config explicitly after setup (current attempt, needs refinement)
2. Restructuring to avoid global state (better long-term)
3. Using a config manager pattern (best balance)

The surgical fixes keep failing because they're patching symptoms rather than addressing the architectural issue: **global mutable state set at import time**.
