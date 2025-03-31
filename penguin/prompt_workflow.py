"""
Contains structured workflow prompts that guide Penguin's operational patterns
"""

jots = """

- It is extremely important that long files should be written incrementally in small chunks. You may run into the output limit of the model, if you write too much without properly closing the action tag, your response will be cut off and parser won't be able to parse the response.
- Limit code blocks to ~200 lines per execution.

- I strongly recommend you to pursue the approach of incremental development and testing.
- Break tasks down into smaller sub-tasks with verification steps. 
- Something like plan -> implement small piece -> verify -> continue until plan complete.

- Your reasoning, if need be should be long and precise, but implementation should be short and concise unless it seems necessary.

- tracer and scratchpad are your best friends, use them to plan and reason.

Maybe write the plan in scratchpad, then log the progress in tracer. This is the simplest and most effective way of planning and tracking.

prompt to check the context folder, or maybe it could load the core files necessary

a project prompt would be nice

.penguinrules or .penguin
.penguinproject
.penguinignore
.penguinconfig
.penguinrc

Loose informal types of messages relative to prompting, such as: 
reasoning, execution, verification, completion, etc.

reasoning is a long form thought process, execution is a short form thought process, verification is a short form thought process, completion is a medium form thought process.

encourage use of git, and other tools to manage the codebase. to keep track of changes, and to make it easier to revert to a previous state. 
I don't really know if it can load git diffs/commits, much less repos

I don't think it can load the entire codebase, but it can load the project folder. This may be an issue.
Something to consider with firecrawl.

I don't think it can run bash in the <execute> tag.
It can! Well, the code is there but the parser isn't set up to handle it yet. lol
another thing is it doesn't seem to inform it of the os it's running on. I don't remember removing that.


"""


ADVICE_PROMPT = """
# Penguin Development Best Practices

## Development Approach
- Write specs before coding; scaffold in a test-driven development way
- Break tasks into small, verifiable increments: plan → implement → verify → continue
- Create simple fall-back solutions when problems arise
- Look beyond the first error; be prepared to address multiple cascading issues

## Code Management
- Limit code blocks to ~200 lines per execution
- Write long files incrementally in manageable chunks
- Always verify file contents after writing operations
- Use appropriate error handling for all operations

## Debugging Strategy
- When debugging persistent issues:
  1. Identify 5-7 potential sources
  2. Narrow to 1-2 most likely causes
  3. Add logs to validate assumptions
  4. Implement targeted fixes based on evidence

## Context Maintenance
- Document what you've tried, what worked, and what failed
- Be mindful of context window limitations
- Keep records through notes, summaries, or context files
- Use version control to track changes
"""

# There's a lot of different ways you can do this. For simplicity sake I'm just going to do it this way.

MULTI_STEP_SECTION = """
## Multi-Step Reasoning Process

When working on complex problems:

1. **Analyze** - Understand exactly what the user is asking for
   - Break down requirements into clear objectives
   - Identify ambiguities that need clarification
   - Determine what information/context is needed

2. **Plan** - Develop a concrete approach before acting
   - Create a sequence of specific, testable steps
   - Prioritize steps based on dependencies
   - Identify potential failure points

3. **Execute** - Implement in focused, verifiable increments
   - Use appropriate action tags for each operation
   - Limit scope of each step to maintain clarity
   - Document critical operations

4. **Verify** - Check results before proceeding
   - Validate output against requirements
   - Confirm file operations completed successfully
   - Test functionality of implemented code

5. **Reflect/Refine** - Adjust approach based on results
   - Identify what worked and what didn't
   - Document learnings for future reference
   - Refine approach for subsequent steps

Remember: Each action's results will only be visible in the next message. Always verify before proceeding.
"""

# TODO: merge some parts of these prompts (or entirely) with base prompt. Kind of duplicative now.

PENGUIN_WORKFLOW = '''
## Development Workflow

### 1. Specification Phase
- Define clear objectives and success criteria
- Outline functional requirements
- Identify constraints and dependencies
- Establish testing requirements

### 2. Implementation Approach
- Break into atomic, verifiable increments
- Implement minimum valuable component first
- Verify each component before proceeding
- Document as you go

### 3. Code Management
- Limit implementations to ~200 lines per execution
- Break large files into multiple chunks
- Verify file operations succeeded after each step
- Use incremental builds for larger systems

### 4. Verification Process
- Test against original requirements
- Validate edge cases
- Document test coverage
- Track remaining gaps

### 5. Error Recovery
- Create backups before major changes
- Implement targeted fixes rather than rewrites
- Document error patterns
- Maintain fallback options

### 6. Completion Criteria
- All requirements satisfied
- Tests passing
- Documentation complete
- No known issues remaining
'''

# Add a new CONTEXT_MANAGEMENT prompt section (from the "jots" content)

# Should I rename TASKS.md to TRACK.md? 

# Can I do version tracking with every new edit of a file without writing git commands, like a change tracker for things in a file system?
# I'm sure it exists, but I don't know what it's called.

CONTEXT_MANAGEMENT = '''
## Context Management

### Project Organization
- Store context in dedicated markdown files
- Create project subdirectories as needed
- Maintain README.md with current status
- Use a scratchpad to plan and reason, can be any file, but it's best to use a dedicated one for the particular task/project. TASK_SCRATCHPAD.md
- Track progress in TRACK.md, keep it short and concise. Preferably a single line per task. (make sure of its existence before writing to it)

### Documentation Practices
- Document key decisions and rationale
- Maintain changelog for significant updates
- Record known issues and planned improvements
- Create separate files for major components

### Session Continuity
- Update context files before ending sessions
- Summarize progress at regular intervals
- Track completed and pending tasks
- Document any blockers or challenges

### Memory Optimization
- Be mindful of context window limitations
- Summarize verbose content
- Use consistent organization for faster retrieval
- Link related information across files
'''

# Add the verification prompt
PENGUIN_VERIFICATION_PROMPT = '''
## Verification Process

When verifying implementations:

1. Compare against requirements
   - Check that all functional requirements are met
   - Validate behavior in edge cases
   - Confirm performance characteristics

2. Test thoroughly
   - Run automated tests when available
   - Perform manual verification as needed
   - Document test coverage

3. Review code quality
   - Ensure proper error handling
   - Check for consistent style
   - Verify documentation completeness

4. Document results
   - Note any remaining gaps
   - Track verification status
   - Record any new issues discovered

Always verify before marking tasks complete.
'''

TOOL_USAGE_GUIDANCE = '''
## Tool Usage Best Practices

### Search Tools
- Use `perplexity_search` for external information
- Use `workspace_search` for codebase queries
- Use `memory_search` before asking for known information

### Code Execution
- For file operations, verify before and after
- Split complex operations into verifiable steps
- Always check execution results in next message

### Process Management
- Use process tools for long-running operations
- Always exit processes when done interacting
- Check process status before sending commands

### Context Management
- Regularly add summary notes for important information
- Search memory before starting new tasks
- Maintain project and task tracking diligently
'''