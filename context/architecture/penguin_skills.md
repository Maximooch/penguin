# Penguin Agent Skills Implementation Plan

## Overview

Agent Skills provide a composable, scalable way to equip Penguin with domain-specific expertise by packaging procedural knowledge into organized folders of instructions, scripts, and resources. This report outlines how Penguin can implement the Agent Skills standard.

## Core Concepts

### What is a Skill?

A skill is a directory containing:
- **SKILL.md** - Main skill definition with YAML frontmatter
- **Optional resources** - Additional files, scripts, templates
- **Optional code** - Executable scripts for deterministic operations

### Progressive Disclosure Architecture

Skills use a three-level progressive disclosure pattern to manage context efficiently:

1. **Level 1 (Startup)**: YAML metadata (`name`, `description`) loaded into system prompt
2. **Level 2 (Triggered)**: Full SKILL.md loaded when skill is relevant to current task
3. **Level 3+ (On-Demand)**: Additional referenced files loaded as needed

This design allows unbounded skill content without overwhelming the context window.

## Implementation Architecture

### 1. Skill Discovery System

**Location**: `skills/` directory in workspace root

```yaml
skills/
├── pdf/
│   ├── SKILL.md
│   ├── reference.md
│   ├── forms.md
│   └── scripts/
│       └── extract_fields.py
├── git/
│   ├── SKILL.md
│   └── workflows/
│       └── commit_message.md
└── testing/
    ├── SKILL.md
    └── frameworks/
        ├── pytest.md
        └── jest.md
```

**Discovery Logic**:
```python
# Pseudocode for skill discovery
def discover_skills():
    skills_dir = Path("skills")
    skills = []
    
    for skill_path in skills_dir.iterdir():
        if skill_path.is_dir():
            skill_md = skill_path / "SKILL.md"
            if skill_md.exists():
                # Parse YAML frontmatter
                metadata = parse_yaml_frontmatter(skill_md)
                skills.append({
                    "path": skill_path,
                    "name": metadata["name"],
                    "description": metadata["description"],
                    "trigger_count": 0
                })
    
    return skills
```

### 2. Skill Loading Strategy

**At Startup**:
- Scan `skills/` directory
- Extract `name` and `description` from each SKILL.md
- Inject metadata into system prompt as available capabilities

**During Task Execution**:
- Monitor user queries for skill relevance
- When skill is triggered, load full SKILL.md into context
- Dynamically load referenced files based on task needs

**System Prompt Integration**:
```
Available Skills:
- pdf: Manipulate PDF documents, extract form fields, fill forms
- git: Advanced Git operations, commit message generation, branch management
- testing: Test framework expertise, test generation, debugging strategies

When a task requires specialized knowledge, consult the relevant skill by reading its SKILL.md file.
```

### 3. Skill Triggering Mechanism

**Heuristic-Based Triggering**:
```python
def should_trigger_skill(user_message, skill_metadata):
    """
    Determine if a skill should be triggered based on:
    1. Keyword matching in skill description
    2. Semantic similarity to skill name
    3. Task type detection
    """
    skill_keywords = extract_keywords(skill_metadata["description"])
    message_keywords = extract_keywords(user_message)
    
    # Simple keyword overlap
    overlap = len(set(skill_keywords) & set(message_keywords))
    
    # Could be enhanced with semantic similarity
    return overlap >= 2 or skill_metadata["name"].lower() in user_message.lower()
```

**Alternative: Let Penguin Decide**
- Include skill metadata in system prompt
- Trust Penguin to decide when to load skills based on task context
- More flexible, leverages model's reasoning

### 4. Progressive Disclosure Implementation

**SKILL.md Structure**:
```markdown
---
name: pdf
description: Manipulate PDF documents, extract form fields, fill forms programmatically
---

# PDF Manipulation Skill

## Core Capabilities

This skill enables Penguin to work with PDF documents beyond simple reading.

## When to Use

Use this skill when:
- User mentions PDF manipulation
- Need to extract form fields
- Need to fill out forms programmatically
- Need to merge or split PDFs

## Reference Material

For detailed PDF operations, see: [reference.md](reference.md)

## Form Filling

For form-specific workflows, see: [forms.md](forms.md)
```

**Dynamic File Loading**:
```python
def load_skill_file(skill_path, filename):
    """Load a referenced file from a skill"""
    file_path = skill_path / filename
    if file_path.exists():
        return file_path.read_text()
    return None
```

### 5. Code Execution Integration

Penguin already has code execution via `<execute>` blocks. Skills can include:

**Executable Scripts**:
```python
# skills/pdf/scripts/extract_fields.py
import PyPDF2

def extract_form_fields(pdf_path):
    """Extract all form fields from a PDF"""
    reader = PyPDF2.PdfReader(pdf_path)
    fields = reader.get_fields()
    return fields

if __name__ == "__main__":
    import sys
    result = extract_form_fields(sys.argv[1])
    print(result)
```

**Usage in SKILL.md**:
```markdown
## Form Field Extraction

To extract form fields from a PDF, use the provided script:

```bash
python skills/pdf/scripts/extract_fields.py path/to/document.pdf
```

This is more efficient and reliable than token-based extraction.
```

## Penguin-Specific Implementation

### Current State Analysis

Penguin already has:
- ✅ Filesystem access (via `<execute>`)
- ✅ Code execution (via `<execute>` with Python)
- ✅ Context management (via `context/` directory)
- ✅ Memory system (via `<add_*_note>` tools)
- ✅ Tool ecosystem (enhanced tools, search, etc.)

### Integration Points

1. **Skill Discovery**: Add to initialization phase
2. **Skill Loading**: Integrate with existing context loading
3. **Skill Execution**: Leverage existing `<execute>` tool
4. **Skill Caching**: Use existing memory system

### Implementation Priority

**Phase 1: Core Infrastructure**
1. Create `skills/` directory structure
2. Implement skill discovery at startup
3. Add skill metadata to system prompt
4. Create first example skill (e.g., `git` or `testing`)

**Phase 2: Dynamic Loading**
1. Implement skill triggering logic
2. Add progressive disclosure (load referenced files)
3. Integrate with existing context window management

**Phase 3: Advanced Features**
1. Skill versioning and updates
2. Skill sharing/import mechanism
3. Skill evaluation and testing
4. Skill creation assistance (Penguin helps build skills)

## Example Skills for Penguin

### 1. Git Operations Skill

**skills/git/SKILL.md**:
```markdown
---
name: git
description: Advanced Git operations, commit message generation, branch management, conflict resolution
---

# Git Operations Skill

## Core Capabilities

Advanced Git workflows beyond basic add/commit/push.

## Commit Message Generation

Follow conventional commits format:
```
type(scope): description

[optional body]

[optional footer]
```

Types: feat, fix, docs, style, refactor, test, chore

## Branch Management

See: [workflows/branching.md](workflows/branching.md)

## Conflict Resolution

See: [workflows/conflicts.md](workflows/conflicts.md)
```

### 2. Testing Skill

**skills/testing/SKILL.md**:
```markdown
---
name: testing
description: Test framework expertise, test generation strategies, debugging techniques, coverage analysis
---

# Testing Skill

## Framework-Specific Guidance

- Python: See [frameworks/pytest.md](frameworks/pytest.md)
- JavaScript: See [frameworks/jest.md](frameworks/jest.md)
- Rust: See [frameworks/cargo_test.md](frameworks/cargo_test.md)

## Test Generation Strategy

1. Start with happy path
2. Add edge cases
3. Test error conditions
4. Verify integration points

## Debugging Failed Tests

See: [debugging.md](debugging.md)
```

### 3. Documentation Skill

**skills/documentation/SKILL.md**:
```markdown
---
name: documentation
description: Technical writing, API documentation, README generation, docstring standards
---

# Documentation Skill

## Writing Principles

- Be concise but complete
- Include examples
- Use consistent terminology
- Keep docs in sync with code

## Docstring Standards

- Python: Follow Google style or NumPy style
- JavaScript: JSDoc format
- See: [standards.md](standards.md)

## README Structure

See: [templates/readme.md](templates/readme.md)
```

## Security Considerations

### Skill Validation

Before loading a skill, Penguin should:

1. **Parse YAML Frontmatter**: Verify required fields (`name`, `description`)
2. **Check File Structure**: Ensure SKILL.md exists and is valid
3. **Scan for Dangerous Code**: Look for:
   - Network requests to untrusted sources
   - File system operations outside workspace
   - Executable code in unexpected locations
   - Data exfiltration patterns

### Sandboxing

- Skills should only access files within their directory
- Code execution should respect existing permission boundaries
- No direct system command execution from skill code

### Auditing

- Log skill usage (which skills triggered, how often)
- Track skill loading performance
- Monitor for skill conflicts or unexpected behavior

## Evaluation and Iteration

### Skill Effectiveness Metrics

1. **Trigger Accuracy**: How often is the skill triggered correctly?
2. **Task Success Rate**: Does using the skill improve outcomes?
3. **Context Efficiency**: How many tokens does the skill consume?
4. **User Satisfaction**: Do users find the skill helpful?

### Iterative Improvement

1. **Start with Evaluation**: Identify capability gaps
2. **Build Incrementally**: Add skills to address specific gaps
3. **Monitor Usage**: Track how Penguin uses skills in practice
4. **Refine Based on Observation**: Adjust SKILL.md based on actual usage patterns
5. **Self-Reflection**: Ask Penguin to reflect on skill effectiveness

### Skill Creation Workflow

When Penguin successfully solves a novel problem:

1. **Capture the Approach**: Document the successful strategy
2. **Identify Patterns**: Extract reusable procedures
3. **Create Skill File**: Package into SKILL.md
4. **Test Skill**: Verify skill improves performance on similar tasks
5. **Iterate**: Refine based on real-world usage

## Future Enhancements

### Skill Sharing

- Export skills as portable directories
- Import skills from trusted sources
- Skill marketplace (internal or public)

### Skill Composition

- Skills that depend on other skills
- Skill inheritance and extension
- Skill templates for quick creation

### MCP Integration

- Skills that teach MCP server workflows
- Skills that wrap MCP tools
- Hybrid skill + MCP architectures

### Self-Improving Skills

- Penguin creates and edits its own skills
- Automatic skill generation from successful patterns
- Skill optimization based on usage data

## Conclusion

Agent Skills provide a powerful framework for extending Penguin's capabilities in a composable, scalable way. By implementing progressive disclosure and leveraging Penguin's existing tools, we can create a rich ecosystem of domain-specific expertise that grows organically with usage.

The key to success is:
1. Start simple with core infrastructure
2. Build skills based on actual capability gaps
3. Iterate based on real-world usage
4. Maintain security through careful validation

This approach transforms Penguin from a general-purpose agent into a continuously improving specialist that can adapt to any domain through composable skills.