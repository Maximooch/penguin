# Remark/Unified Migration Plan for Penguin CLI

## Why Remark?

You're absolutely right - remark/unified is the best long-term choice because:

1. **AST-first design** = perfect for custom terminal rendering
2. **Extensible plugin ecosystem** (200+ plugins)
3. **Mermaid, Math, Emoji** all supported via plugins
4. **Type-safe** with full TypeScript support
5. **Composable** - chain transforms like Babel
6. **Future-proof** - can add any syntax we want

## Current vs. Future

### Current (Custom Parser)
```typescript
<Markdown content={text} />
// ✅ Works: Headers, bold, code, lists, tables
// ❌ Missing: Math, emoji, advanced formatting
// ❌ Limited: Hard to extend
```

### Future (Remark)
```typescript
<RemarkMarkdown content={text} />
// ✅ Everything custom parser has
// ✅ Math/LaTeX rendering
// ✅ Emoji shortcodes
// ✅ Mermaid diagrams
// ✅ Footnotes, definition lists
// ✅ Custom directives (:::warning, etc.)
// ✅ Easy to extend with plugins
```

---

## Phase 1: Setup & Basic Migration (2-3 hours)

### 1.1 Install Dependencies

```bash
npm install unified remark-parse remark-gfm unist-util-visit
npm install --save-dev @types/unist
```

**Packages:**
- `unified`: Core processing engine
- `remark-parse`: Markdown → AST parser
- `remark-gfm`: GitHub Flavored Markdown (tables, strikethrough, task lists)
- `unist-util-visit`: AST traversal utility
- `@types/unist`: TypeScript types

### 1.2 Create Remark Renderer

**File:** `src/ui/components/RemarkMarkdown.tsx`

```typescript
import React from 'react';
import { Box, Text } from 'ink';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';
import type { Root, Heading, Paragraph, Code, Table, List } from 'mdast';

interface RemarkMarkdownProps {
  content: string;
}

export function RemarkMarkdown({ content }: RemarkMarkdownProps) {
  if (!content || content.trim() === '') {
    return null;
  }

  // Parse markdown to AST
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm); // Add GFM support

  const ast = processor.parse(content);

  // Convert AST to Ink components
  const components = astToInkComponents(ast);

  return <Box flexDirection="column">{components}</Box>;
}

function astToInkComponents(ast: Root): React.ReactNode[] {
  const components: React.ReactNode[] = [];
  let key = 0;

  visit(ast, (node) => {
    switch (node.type) {
      case 'heading':
        const heading = node as Heading;
        const headingColor = heading.depth === 1 ? 'cyan' : heading.depth === 2 ? 'blue' : 'white';
        components.push(
          <Box key={key++} marginY={heading.depth <= 2 ? 1 : 0}>
            <Text bold color={headingColor}>
              {extractText(heading)}
            </Text>
          </Box>
        );
        break;

      case 'paragraph':
        const para = node as Paragraph;
        components.push(
          <Box key={key++}>
            <Text>{formatInline(para)}</Text>
          </Box>
        );
        break;

      case 'code':
        const code = node as Code;
        components.push(
          <Box key={key++} marginY={1} paddingX={2} borderStyle="round" borderColor="gray">
            <Text color="green">{code.value}</Text>
          </Box>
        );
        break;

      case 'table':
        const table = node as Table;
        components.push(
          <TableComponent key={key++} node={table} />
        );
        break;

      case 'list':
        const list = node as List;
        components.push(
          <ListComponent key={key++} node={list} />
        );
        break;
    }
  });

  return components;
}

// Helper: Extract text from node
function extractText(node: any): string {
  if (node.type === 'text') return node.value;
  if (node.children) {
    return node.children.map(extractText).join('');
  }
  return '';
}

// Helper: Format inline elements (bold, code, etc.)
function formatInline(node: any): React.ReactNode[] {
  if (node.type === 'text') {
    return [node.value];
  }

  if (node.type === 'strong') {
    return [<Text key={Math.random()} bold>{extractText(node)}</Text>];
  }

  if (node.type === 'inlineCode') {
    return [
      <Text key={Math.random()} backgroundColor="gray" color="green">
        {' '}{node.value}{' '}
      </Text>
    ];
  }

  if (node.children) {
    return node.children.flatMap(formatInline);
  }

  return [];
}
```

### 1.3 Test Side-by-Side

Update `prototype-mock.tsx` to compare:

```typescript
import { Markdown } from './ui/components/Markdown.js';       // Old
import { RemarkMarkdown } from './ui/components/RemarkMarkdown.js'; // New

// Demo 10: Compare old vs new
const compareRenderers = () => {
  const content = `## Renderer Comparison

### Old (Custom Parser)
| Feature | Status |
|---------|--------|
| Tables | ✅ |
| Code | ✅ |

### New (Remark)
| Feature | Status |
|---------|--------|
| Tables | ✅ |
| Math | 🔜 |
| Emoji | 🔜 |`;

  addMessage(content, 'assistant');
};
```

---

## Phase 2: Advanced Features (3-4 hours)

### 2.1 Add Math Support

```bash
npm install remark-math rehype-katex
```

**Usage:**
```typescript
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath)        // Parse math ($...$, $$...$$)
  .use(rehypeKatex);      // Render math

// In AST handler:
case 'inlineMath':
  return <Text color="magenta">{renderMathASCII(node.value)}</Text>;

case 'math':
  return <Box borderStyle="round" borderColor="magenta">
    <Text>{renderMathASCII(node.value)}</Text>
  </Box>;
```

**Math rendering options:**
- **ASCII art**: Use `ascii-math` package
- **Unicode**: Convert to Unicode math symbols
- **Browser**: Link to rendered version

### 2.2 Add Emoji Support

```bash
npm install remark-emoji
```

**Usage:**
```typescript
import remarkEmoji from 'remark-emoji';

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkEmoji);  // :smile: → 😄

// No extra handling needed! Emoji are converted in AST
```

### 2.3 Add Mermaid Support

```bash
npm install remark-mermaidjs
```

**Usage:**
```typescript
import remarkMermaid from 'remark-mermaidjs';

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMermaid, {
    // Custom renderer for terminal
    renderMermaid: async (code) => {
      // Option A: ASCII art
      return convertMermaidToASCII(code);

      // Option B: Simple text + browser link
      return `[Mermaid Diagram]\n${simplifyMermaid(code)}\n\nView in browser: file:///tmp/diagram.html`;
    }
  });
```

**Mermaid handler:**
```typescript
case 'mermaid':
  const mermaidCode = node.value;
  const ascii = simplifyMermaidToText(mermaidCode);
  return (
    <Box key={key++} flexDirection="column" marginY={1} borderStyle="round" borderColor="blue">
      <Text color="blue">📊 Mermaid Diagram</Text>
      <Text>{ascii}</Text>
      <Text dimColor>
        View full: <Text color="cyan">file:///tmp/penguin-{hash(mermaidCode)}.html</Text>
      </Text>
    </Box>
  );
```

### 2.4 Add Syntax Highlighting

```bash
npm install lowlight  # Highlight.js wrapper for AST
```

**Usage:**
```typescript
import { lowlight } from 'lowlight';
import python from 'highlight.js/lib/languages/python';
import typescript from 'highlight.js/lib/languages/typescript';

// Register languages
lowlight.register('python', python);
lowlight.register('typescript', typescript);

// In code block handler:
case 'code':
  const highlighted = lowlight.highlight(node.lang || 'text', node.value);
  return (
    <Box key={key++} marginY={1} borderStyle="round" borderColor="gray">
      <SyntaxHighlightedCode ast={highlighted} />
    </Box>
  );
```

---

## Phase 3: Penguin-Specific Features (2-3 hours)

### 3.1 Custom Directives

**Use case:** Special blocks for Penguin features

```markdown
:::warning
This will delete all files!
:::

:::task[high]
Implement user authentication
:::

:::code-execution
\`\`\`python
print("Hello")
\`\`\`
:::
```

**Implementation:**
```bash
npm install remark-directive
```

```typescript
import remarkDirective from 'remark-directive';

const processor = unified()
  .use(remarkParse)
  .use(remarkDirective)
  .use(function penguinDirectives() {
    return (tree) => {
      visit(tree, 'containerDirective', (node) => {
        if (node.name === 'warning') {
          node.data = {
            hName: 'PenguinWarning',
            hProperties: node.attributes
          };
        }
        if (node.name === 'task') {
          node.data = {
            hName: 'PenguinTask',
            hProperties: node.attributes
          };
        }
      });
    };
  });

// In AST handler:
case 'PenguinWarning':
  return (
    <Box borderStyle="bold" borderColor="yellow" paddingX={1}>
      <Text color="yellow">⚠️  Warning</Text>
      <Text>{extractText(node)}</Text>
    </Box>
  );

case 'PenguinTask':
  return (
    <Box borderStyle="single" borderColor="cyan" paddingX={1}>
      <Text color="cyan">📋 Task [{node.properties.priority}]</Text>
      <Text>{extractText(node)}</Text>
    </Box>
  );
```

### 3.2 Tool Result Rendering

**Enhance code blocks with execution results:**

```typescript
// Plugin to detect and enhance execution blocks
function remarkPenguinExecution() {
  return (tree) => {
    visit(tree, 'code', (node, index, parent) => {
      if (node.meta && node.meta.includes('execute')) {
        // Mark for special rendering
        node.data = {
          hName: 'ExecutionBlock',
          hProperties: { language: node.lang }
        };
      }
    });
  };
}

// In renderer:
case 'ExecutionBlock':
  return (
    <ExecutionBlockComponent
      code={node.value}
      language={node.properties.language}
    />
  );
```

### 3.3 Clickable Links

```typescript
// Plugin to make URLs clickable in terminal
function remarkTerminalLinks() {
  return (tree) => {
    visit(tree, 'link', (node) => {
      node.data = {
        hName: 'ClickableLink',
        hProperties: { href: node.url }
      };
    });
  };
}

// In renderer:
case 'ClickableLink':
  return (
    <Text key={key++} color="blue" underline>
      {extractText(node)} ({node.properties.href})
    </Text>
  );
```

---

## Phase 4: Optimization & Polish (1-2 hours)

### 4.1 Caching

```typescript
import { LRUCache } from 'lru-cache';

const astCache = new LRUCache<string, Root>({
  max: 100,
  ttl: 1000 * 60 * 5 // 5 minutes
});

export function RemarkMarkdown({ content }: RemarkMarkdownProps) {
  const cacheKey = hash(content);

  let ast = astCache.get(cacheKey);
  if (!ast) {
    ast = processor.parse(content);
    astCache.set(cacheKey, ast);
  }

  const components = astToInkComponents(ast);
  return <Box flexDirection="column">{components}</Box>;
}
```

### 4.2 Progressive Rendering

For long documents:

```typescript
function astToInkComponents(ast: Root, limit = 100): React.ReactNode[] {
  const components: React.ReactNode[] = [];
  let count = 0;

  visit(ast, (node) => {
    if (count >= limit) return SKIP;

    // Render node...
    count++;
  });

  if (count >= limit) {
    components.push(
      <Text key="more" dimColor>
        ... {ast.children.length - limit} more blocks (scroll to load)
      </Text>
    );
  }

  return components;
}
```

---

## Recommended Remark Plugins for Penguin

### Essential (Phase 2)
1. **remark-gfm** ✅ Tables, strikethrough, task lists
2. **remark-emoji** 😄 Emoji shortcodes
3. **remark-math** + **rehype-katex** ∫ Math/LaTeX
4. **remark-mermaidjs** 📊 Diagrams

### Nice-to-Have (Phase 3)
5. **remark-directive** :::blocks Custom containers
6. **remark-frontmatter** 📄 YAML metadata
7. **remark-footnotes** [^1] Footnotes
8. **remark-definition-list** <dl> Definition lists
9. **remark-toc** 📑 Auto table of contents
10. **remark-slug** 🔗 Header IDs

### Advanced (Phase 4)
11. **remark-lint** ✓ Markdown linting
12. **remark-validate-links** 🔗 Check broken links
13. **remark-code-titles** ```js:file.js Code file names
14. **remark-github** #123 GitHub issue links
15. **remark-breaks** Soft line breaks
16. **remark-abbr** *[HTML]: Abbreviations
17. **remark-custom-blocks** Custom block syntax

### Penguin-Specific (Future)
18. **Custom plugin**: Tool execution blocks
19. **Custom plugin**: File path links
20. **Custom plugin**: Conversation references
21. **Custom plugin**: Diff rendering
22. **Custom plugin**: Interactive prompts

---

## Migration Checklist

### Phase 1: Basic Setup
- [ ] Install unified, remark-parse, remark-gfm
- [ ] Create RemarkMarkdown.tsx
- [ ] Implement basic AST handlers (heading, paragraph, code)
- [ ] Add table support
- [ ] Add list support
- [ ] Test in prototype mock
- [ ] Compare with current Markdown component

### Phase 2: Feature Parity
- [ ] Inline code formatting
- [ ] Bold/italic support
- [ ] Link rendering
- [ ] Code block with language detection
- [ ] Table alignment
- [ ] Nested lists

### Phase 3: New Features
- [ ] Add remark-emoji
- [ ] Add remark-math
- [ ] Add remark-mermaidjs
- [ ] Add syntax highlighting (lowlight)
- [ ] Test all features in mock

### Phase 4: Integration
- [ ] Replace Markdown with RemarkMarkdown in ChatSession
- [ ] Update MessageList
- [ ] Test with real backend
- [ ] Performance testing
- [ ] Update documentation

### Phase 5: Advanced Features
- [ ] Custom directives (warning, task, etc.)
- [ ] Tool execution rendering
- [ ] Clickable terminal links
- [ ] Caching implementation
- [ ] Progressive rendering for long docs

---

## Benefits Summary

**What Penguin Gains:**

1. **Rich Content**
   - Math equations: `$E = mc^2$`
   - Emoji: `:rocket:` → 🚀
   - Mermaid diagrams
   - Syntax highlighting

2. **Extensibility**
   - Add new syntax with plugins
   - Custom directives for Penguin features
   - Transform markdown at AST level

3. **Type Safety**
   - Full TypeScript support
   - Typed AST nodes
   - Compile-time checking

4. **Standards Compliance**
   - CommonMark + GFM spec
   - Compatible with GitHub, GitLab, etc.
   - Future-proof

5. **Community**
   - 200+ plugins available
   - Active maintenance
   - Well-documented

---

## Timeline

| Phase | Duration | Features |
|-------|----------|----------|
| Phase 1 | 2-3 hours | Basic remark setup, feature parity |
| Phase 2 | 3-4 hours | Emoji, math, mermaid, highlighting |
| Phase 3 | 2-3 hours | Custom directives, tool rendering |
| Phase 4 | 1-2 hours | Optimization, caching |
| **Total** | **8-12 hours** | Full remark migration |

---

## Next Steps

1. **Now**: Use current custom parser + continue building
2. **Phase 2 Completion**: Migrate to remark during polish phase
3. **Phase 3**: Add advanced features as needed

This gives us a solid foundation while maintaining velocity! 🚀
