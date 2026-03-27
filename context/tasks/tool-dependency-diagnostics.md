# Tool Dependency Diagnostics TODO

## Objective

- Replace failure-masking lazy import patterns with explicit, actionable diagnostics.
- Keep optional dependencies lazy, but stop turning real import/config problems into late confusing runtime surprises.
- Make tool availability and failure reasons visible to developers and users.

## Why This Exists

- `ToolManager` currently uses broad exception swallowing around optional imports.
- That is convenient for startup, but it can hide missing packages, broken environments, bad transitive imports, and partial initialization failures.
- Delayed failures are harder to debug than immediate, specific failures.

## Audit Evidence

- `penguin/tools/tool_manager.py:47-90`
- `penguin/tools/tool_manager.py:95-113`
- `penguin/tools/tool_manager.py:126-159`

## Progress Snapshot

- [ ] Inventory all lazy import guards in the tool stack
- [ ] Separate optional-missing dependency cases from real import/runtime errors
- [ ] Standardize install-hint and diagnostics messaging
- [ ] Surface disabled-tool reasons in a machine-readable way
- [ ] Add regression coverage for missing optional dependencies
- [ ] Verify startup remains fast after tighter error handling

## Checklist

### Phase 1 - Audit
- [ ] Enumerate every broad `except Exception` lazy import path in `penguin/tools`
- [ ] Classify each as optional dependency, environment/config issue, or actual bug masking
- [ ] Document expected failure mode for each optional tool family

### Phase 2 - Contract
- [ ] Define a standard disabled-tool result shape
- [ ] Include cause category, install hint, and original exception type/message where safe
- [ ] Ensure logs preserve traceback for real bugs

### Phase 3 - Implementation
- [ ] Replace broad exception swallowing with narrower handling where possible
- [ ] Keep optional dependency behavior lazy
- [ ] Expose a simple introspection path for tool availability

## Verification Targets

- missing-optional-dependency smoke tests
- browser/PyDoll disabled-path tests
- repository-tool disabled-path tests
- permission-system import failure tests

## Notes

- The target is not “more crashes.”
- The target is “fewer mysterious crashes later.”
