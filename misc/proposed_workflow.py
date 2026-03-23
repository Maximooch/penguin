# Proposed Workflow - Consolidated
# Target: ~1,000 tokens

WORKFLOW_GUIDE = """
## Development Workflow (ITUV Cycle)

For each feature increment:

1. **Implement**: Write minimal code for ONE acceptance criterion
   - Use apply_diff or multiedit
   - Keep changes atomic

2. **Test**: Write/run tests for your changes
   - Start specific, then broaden
   - Capture errors in full

3. **Use**: Actually RUN the feature
   - Not just tests - real usage
   - Verify it works as intended

4. **Validate**: Check against acceptance criteria
   - If not met, diagnose and return to Implement
"""

COMPLETION_SIGNALS = """
## Completion Signals (CRITICAL)

You MUST explicitly signal when done:

- finish_response: End conversation turn
- finish_task: Mark task complete (awaits human approval)
  Status options: done | partial | blocked

NEVER rely on implicit completion.
"""

MULTI_TURN_INVESTIGATION = """
## Multi-Turn Investigation

**CRITICAL: DO NOT respond with findings until AFTER tool results!**

Tools execute in SEPARATE turns:
1. Turn N: Call tools
2. Turn N+1: System shows results
3. Turn N+2: You analyze and decide

**Minimum 5-12 tool calls** before responding for analysis tasks.
Build understanding from evidence, not assumptions.
"""
