# Penguin Ink CLI - Rendering Capabilities

## Current Status

### ✅ Implemented Features

1. **Basic Markdown**
   - Headers (H1-H6) with color coding
   - Bold text (`**bold**`)
   - Inline code (`` `code` ``) with background
   - Lists (unordered with `•`)
   - Code blocks with borders
   - **Tables** (just added!)

2. **Tool Results**
   - Tool execution display with status (pending/running/completed/error)
   - Expandable results
   - Duration tracking

3. **Progress Indicators**
   - Multi-step progress bars
   - Percentage display
   - Step counter

4. **Reasoning Display**
   - Bordered box with `🧠` icon
   - Dimmed/gray text for reasoning
   - Separate from main content

---

## Questions & Answers

### 1. Tables ✅ DONE

**Status:** Just implemented!

Tables are now rendered with:
- Bordered layout
- Header row (bold, cyan)
- Fixed-width columns (20 chars)
- Support for alignment markers (`:---`, `:---:`, `---:`)

**Example:**
```markdown
| Feature | Status | Priority |
|---------|--------|----------|
| Tables  | Done   | High     |
| Mermaid | TBD    | Medium   |
```

---

### 2. Mermaid Graphs 🤔 COMPLEX

**Answer:** Technically possible but very challenging.

**Options:**

#### A. ASCII Art Conversion (Realistic)
Convert mermaid to ASCII using libraries:
- `mermaid-cli` → PNG → ASCII art converter
- Pros: Works in terminal
- Cons: Loss of detail, requires external dependencies

```typescript
// Pseudocode
import { execSync } from 'child_process';

function renderMermaid(code: string): string {
  // 1. Save mermaid code to temp file
  // 2. Run: mmdc -i temp.mmd -o temp.png
  // 3. Convert PNG to ASCII: img2txt temp.png
  // 4. Return ASCII art
}
```

**Libraries to consider:**
- `@mermaid-js/mermaid-cli` (mmdc)
- `image-to-ascii` or `asciify-image`

#### B. Simplified Graph Rendering (Alternative)
For simple flowcharts/diagrams, render as structured text:

```
┌─────────────┐
│   Start     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Process    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    End      │
└─────────────┘
```

#### C. Browser Preview (Practical)
- Detect mermaid blocks
- Show message: "Mermaid diagram detected. View in browser? [Y/n]"
- Generate HTML + mermaid.js
- Open in default browser

**Recommendation:** Start with option C (browser preview) - it's the most practical and maintains full mermaid features.

---

### 3. Alternative Markdown Libraries

**Research findings:**

#### Currently Using: Custom Parser
- **Pros:**
  - No dependencies
  - Full control
  - No ESM issues
  - Lightweight
- **Cons:**
  - Limited features
  - Manual maintenance

#### Option A: `marked` + Custom Renderer ⭐ RECOMMENDED
```bash
npm install marked
```

**Pros:**
- Industry standard (GitHub uses it)
- Extensible renderer
- ESM compatible
- Full markdown spec support
- Active maintenance

**Implementation:**
```typescript
import { marked } from 'marked';
import { Box, Text } from 'ink';

const renderer = {
  heading(text: string, level: number) {
    return `<InkHeader level={${level}}>${text}</InkHeader>`;
  },
  // ... custom renderers for each element
};

marked.setOptions({ renderer });
```

#### Option B: `markdown-it` ⚠️ HEAVY
```bash
npm install markdown-it
```

**Pros:**
- Extremely powerful
- Plugin ecosystem
- Syntax extensions (tables, footnotes, etc.)

**Cons:**
- Larger bundle size
- More complex setup
- Designed for HTML output (needs adaptation)

#### Option C: `remark` + `unified` 🎯 BEST FOR COMPLEX
```bash
npm install remark remark-parse unified
```

**Pros:**
- AST-based (like Babel for markdown)
- Incredible plugin ecosystem
- Transform pipelines
- Perfect for custom rendering

**Cons:**
- Learning curve
- More setup required
- Might be overkill for CLI

**Example:**
```typescript
import { unified } from 'unified';
import remarkParse from 'remark-parse';

const processor = unified()
  .use(remarkParse)
  .use(myInkRenderer);

const ast = processor.parse(markdown);
// Walk AST and render Ink components
```

#### Option D: Keep Custom + `cli-table3` for Tables
```bash
npm install cli-table3
```

**Pros:**
- Add just table support
- Lightweight
- Terminal-optimized tables

**Implementation:**
```typescript
import Table from 'cli-table3';

const table = new Table({
  head: ['Name', 'Status', 'Priority'],
  style: { head: ['cyan'] }
});

table.push(
  ['Tables', 'Done', 'High'],
  ['Mermaid', 'TBD', 'Medium']
);

console.log(table.toString());
```

### **Recommendation:**

**Phase 2:** Keep custom parser + add `cli-table3` for better tables
- Quick win
- No major refactor
- Terminal-optimized

**Phase 3:** Migrate to `marked` with custom Ink renderer
- Full markdown spec
- Maintainable
- Industry standard

**Phase 4:** Add mermaid browser preview
- Best UX for complex diagrams
- Minimal CLI complexity

---

### 4. Multi-line Input 🔧 SOLVABLE

**Problem:** Ink's `useInput` doesn't reliably detect keyboard modifiers (Shift, Alt, Option).

**Solutions:**

#### A. Ctrl+Enter to Submit ⭐ RECOMMENDED
```typescript
useInput((input, key) => {
  // Ctrl+Enter = submit
  if (key.return && key.ctrl) {
    handleSubmit(text);
    return;
  }

  // Plain Enter = new line
  if (key.return) {
    addNewLine();
    return;
  }

  // Regular typing...
});
```

**Pros:**
- Reliable (Ink detects Ctrl)
- Common pattern (Slack, Discord)
- Works on all platforms

**Cons:**
- Opposite of standard (Enter usually submits)
- Needs clear UI hints

#### B. Command-Based Toggle
```typescript
// Type "/multi" to enable multi-line mode
if (input === '/multi') {
  setMultiLineMode(true);
  // Now Enter adds lines, use "/send" to submit
}
```

**Pros:**
- Explicit mode switching
- No keyboard modifier issues

**Cons:**
- Extra steps
- Less intuitive

#### C. Textarea-Style with "Done" Button
```typescript
<Box>
  <Text>Press Tab to add line, Enter when done:</Text>
  <MultiLineTextArea />
</Box>
```

**Pros:**
- Clear separation
- No confusion

**Cons:**
- More UI complexity
- Tab might not work either

#### D. External Editor (Advanced)
```typescript
// Press Ctrl+E to open $EDITOR
if (key.ctrl && input === 'e') {
  const tempFile = '/tmp/penguin-input.txt';
  execSync(`${process.env.EDITOR || 'nano'} ${tempFile}`);
  const content = readFileSync(tempFile, 'utf-8');
  handleSubmit(content);
}
```

**Pros:**
- Full editor power (vim, emacs, etc.)
- No keyboard limitations

**Cons:**
- Interrupts flow
- Requires external editor

### **Recommendation for Multi-line:**

**Implement Ctrl+Enter** approach:

```typescript
/**
 * Multi-line Input
 * - Enter: New line
 * - Ctrl+Enter: Submit
 * - Esc: Clear input
 */

const [lines, setLines] = useState(['']);
const [cursorLine, setCursorLine] = useState(0);

useInput((input, key) => {
  // Submit on Ctrl+Enter
  if (key.return && key.ctrl) {
    const text = lines.join('\n');
    onSubmit(text);
    setLines(['']);
    return;
  }

  // New line on plain Enter
  if (key.return) {
    setLines(prev => [...prev, '']);
    setCursorLine(prev => prev + 1);
    return;
  }

  // Regular typing
  // ...
});
```

**UI Hint:**
```
╭────────────────────────────────────╮
│ Type your message                  │
│                                    │
│ Enter: New line                    │
│ Ctrl+Enter: Send                   │
╰────────────────────────────────────╯
```

This is the most reliable approach given Ink's limitations.

---

## Next Steps

### Immediate (Phase 2)
1. ✅ Add table support (DONE)
2. 🔧 Implement Ctrl+Enter multi-line input
3. 📦 Add `cli-table3` for better table rendering
4. 🧪 Test in prototype mock

### Near-term (Phase 3)
1. 🔄 Migrate to `marked` with custom Ink renderer
2. 🎨 Add syntax highlighting for code blocks
3. 🖼️ Add mermaid browser preview
4. 📊 Improve table responsiveness (dynamic widths)

### Long-term (Phase 4)
1. 🎨 Theme support
2. 📱 Responsive layout (adapt to terminal width)
3. 🔍 Search/filter in long conversations
4. 💾 Session management UI

---

## Summary

| Feature | Status | Library | Priority |
|---------|--------|---------|----------|
| Basic Markdown | ✅ Done | Custom | - |
| Tables | ✅ Done | Custom | High |
| Inline code | ✅ Done | Custom | - |
| Multi-line input | 🔧 In Progress | Custom | High |
| Code highlighting | 📋 Planned | highlight.js | Medium |
| Mermaid | 📋 Planned | Browser | Low |
| Advanced MD | 📋 Planned | marked | Medium |

**Recommended library stack:**
- **Current:** Custom parser (lightweight, working)
- **Next:** `marked` + custom renderer (full spec, maintainable)
- **Tables:** `cli-table3` (terminal-optimized)
- **Mermaid:** Browser preview via temp HTML file
