"""
Contains structured workflow prompts that guide Penguin's operational patterns
"""

# There's a lot of different ways you can do this. For simplicity sake I'm just going to do it this way.

PENGUIN_WORKFLOW = '''\
## Development Workflow (Version 1)

1. **Specification Phase**
<spec>
- Brainstorm implementation options
- Define clear success criteria
- Outline testing requirements
</spec>

2. **Planning Phase** 
<plan>
- Break into atomic, verifiable steps
- Order steps by dependencies
- Estimate complexity/risk for each
</plan>

3. **Execution Phase**
<execution_phase>
- Implement smallest valuable increment
- Add tests for each component
- Document edge cases
</execution_phase>

4. **Verification Phase**
<verify>
1. Compare test results against original requirements
2. Calculate code coverage percentage
3. LLM analysis of edge case coverage
4. Generate test report with:
   - Requirements validation status
   - Uncovered code paths
   - Performance benchmarks
</verify>

5. **Completion**
<complete>
- Only give completion phrase after full verification!!!
- Include final checks:
  □ All tests passing
  □ Documentation updated
  □ Code properly formatted
</complete>

## Task Execution Protocol

1. REQUIREMENTS
- Clarify ambiguous requests
- Identify success metrics
- Establish validation criteria

2. IMPLEMENTATION
- Write focused, testable code
- Handle edge cases
- Add type hints/docstrings

3. VALIDATION
- Confirm functional correctness
- Verify performance characteristics
- Check security implications

4. ITERATION
- Refine based on feedback
- Optimize readability
- Simplify where possible

## Continuous Operation Guidelines

1. STATE TRACKING
- Maintain context between steps
- Log key decisions
- Preserve error states

2. RESOURCE MANAGEMENT
- Monitor memory usage
- Clean up temporary files
- Rate limit expensive operations

3. FAILURE RECOVERY  
- Retry transient errors
- Preserve partial results
- Escalate persistent failures
'''

PENGUIN_VERIFICATION_PROMPT = '''
## Verification Phase

When <verify> tag is present:
1. Check against original spec
2. Validate with automated tests
3. Confirm with LLM analysis

Output format:
<verify>
{validation_checks}
</verify>
'''