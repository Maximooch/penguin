# Markdown Library Detailed Comparison

## 1. marked

**GitHub:** https://github.com/markedjs/marked
**Stars:** ~32k | **Bundle Size:** ~50KB minified
**License:** MIT

### Features

#### ✅ Core Features
- Full CommonMark spec compliance
- GitHub Flavored Markdown (GFM) support
- Tables, strikethrough, task lists
- Autolinks, URL autolinking
- Custom renderers (perfect for Ink!)
- Async rendering support
- Pedantic mode for strict parsing

#### ✅ Extensions & Customization
```javascript
// Custom renderer example
const renderer = {
  heading(text, level) {
    // Return custom Ink components
    return `<InkHeader level={${level}}>${text}</InkHeader>`;
  },
  table(header, body) {
    // Custom table rendering for terminal
    return renderInkTable(header, body);
  },
  code(code, language) {
    // Syntax highlighting
    return highlightCode(code, language);
  }
};

marked.use({ renderer });
```

#### ✅ What It Supports
- **Tables**: Full GFM table syntax with alignment
- **Code blocks**: Language hints, fenced/indented
- **Lists**: Nested, ordered, unordered, task lists
- **Links**: Inline, reference, automatic
- **Images**: Standard markdown syntax
- **Emphasis**: Bold, italic, strikethrough
- **Blockquotes**: Nested support
- **HTML**: Raw HTML passthrough (can disable)
- **Line breaks**: Hard breaks with `\n` or `  \n`

#### ❌ What It Doesn't Support (by default)
- Mermaid diagrams
- Math/LaTeX (needs extension)
- Footnotes (needs extension)
- Definition lists
- Emoji shortcodes (needs extension)
- Front matter (YAML/TOML)

#### 🔧 Extensibility
```javascript
// Adding custom extensions
marked.use({
  extensions: [{
    name: 'mermaid',
    level: 'block',
    start(src) { return src.match(/^```mermaid/)?.index; },
    tokenizer(src) {
      const match = src.match(/^```mermaid\n([\s\S]*?)\n```/);
      if (match) {
        return {
          type: 'mermaid',
          raw: match[0],
          text: match[1]
        };
      }
    },
    renderer(token) {
      return renderMermaidToASCII(token.text);
    }
  }]
});
```

### Pros for Penguin CLI
✅ Lightweight and fast
✅ Proven stability (used by GitHub, npm docs)
✅ Custom renderer = full control over Ink output
✅ GFM support = tables, task lists work out of box
✅ Simple API: `marked.parse(markdown)`
✅ Streaming support for large documents
✅ Active maintenance (last update: recent)

### Cons
⚠️ Designed for HTML output (need custom renderer)
⚠️ No built-in syntax highlighting
⚠️ Extension API can be verbose
⚠️ No AST manipulation (parse-only)

### Integration Example
```typescript
import { marked } from 'marked';
import { Box, Text } from 'ink';

// Custom renderer for Ink
const inkRenderer = {
  heading(text: string, level: number) {
    const colors = ['cyan', 'blue', 'white'];
    return {
      type: 'heading',
      level,
      text,
      color: colors[Math.min(level - 1, 2)]
    };
  },

  table(header: string, body: string) {
    return {
      type: 'table',
      header: parseTableRow(header),
      body: parseTableRows(body)
    };
  },

  code(code: string, language: string | undefined) {
    return {
      type: 'code',
      code,
      language
    };
  }
};

marked.use({ renderer: inkRenderer });

// Parse markdown
const tokens = marked.parse(markdown);

// Render as Ink components
function renderToken(token: any) {
  switch (token.type) {
    case 'heading':
      return <Text bold color={token.color}>{token.text}</Text>;
    case 'table':
      return <TableComponent data={token} />;
    case 'code':
      return <CodeBlock code={token.code} language={token.language} />;
  }
}
```

---

## 2. markdown-it

**GitHub:** https://github.com/markdown-it/markdown-it
**Stars:** ~18k | **Bundle Size:** ~95KB minified
**License:** MIT

### Features

#### ✅ Core Features
- 100% CommonMark compliance
- Extensible plugin architecture
- Safe by default (sanitizes HTML)
- Syntax extensions support
- Typographer (smart quotes, dashes, ellipses)
- Link validation
- Multiple preset configs (commonmark, default, zero)

#### ✅ Plugin Ecosystem (100+ plugins)
```javascript
const md = require('markdown-it')();

// Available plugins
md.use(require('markdown-it-footnote'))
  .use(require('markdown-it-sub'))        // H~2~O
  .use(require('markdown-it-sup'))        // 29^th^
  .use(require('markdown-it-abbr'))       // Abbreviations
  .use(require('markdown-it-deflist'))    // Definition lists
  .use(require('markdown-it-emoji'))      // :smile:
  .use(require('markdown-it-container'))  // Custom blocks
  .use(require('markdown-it-ins'))        // ++inserted++
  .use(require('markdown-it-mark'))       // ==marked==
  .use(require('markdown-it-anchor'))     // Header anchors
  .use(require('markdown-it-toc'));       // Table of contents
```

#### ✅ What It Supports
- **Tables**: Full support with alignment
- **Code blocks**: Fenced, indented, language hints
- **Lists**: Nested, ordered, unordered
- **Links**: All types + validation
- **Images**: Standard syntax
- **Emphasis**: Bold, italic, strikethrough
- **Blockquotes**: Nested
- **HTML**: Configurable (safe/unsafe mode)
- **Subscript/Superscript**: With plugins
- **Footnotes**: With plugin
- **Definition lists**: With plugin
- **Emoji**: With plugin (:smile: → 😄)
- **Math**: With plugin (KaTeX, MathJax)
- **Container blocks**: Custom blocks (warning, info, etc.)

#### ❌ What It Doesn't Support (by default)
- Mermaid (needs plugin)
- Front matter (needs plugin)
- Custom directives (needs plugin)

#### 🔧 Extensibility
```javascript
// Three ways to extend:

// 1. Simple rule modification
md.renderer.rules.strong_open = () => '<b>';
md.renderer.rules.strong_close = () => '</b>';

// 2. Custom renderer
md.renderer.render = function(tokens, options, env) {
  // Full control over rendering
};

// 3. Plugin system
function myPlugin(md, options) {
  md.core.ruler.push('my_rule', state => {
    // Modify token stream
  });

  md.renderer.rules.my_token = (tokens, idx) => {
    return '<custom>' + tokens[idx].content + '</custom>';
  };
}

md.use(myPlugin, { /* options */ });
```

### Pros for Penguin CLI
✅ Most powerful plugin ecosystem
✅ Highly extensible (3 extension points)
✅ Token stream manipulation (AST-like)
✅ Safe by default (good for user content)
✅ Preset configs (can tune performance)
✅ Typographer features (smart quotes)
✅ Link validation built-in

### Cons
⚠️ Larger bundle size (~2x marked)
⚠️ More complex API (steeper learning curve)
⚠️ HTML-focused (like marked, needs custom renderer)
⚠️ Plugin dependencies (external packages)
⚠️ May be overkill for CLI needs

### Integration Example
```typescript
import MarkdownIt from 'markdown-it';
import { Box, Text } from 'ink';

const md = new MarkdownIt({
  html: false,        // Disable HTML tags
  linkify: true,      // Autoconvert URLs
  typographer: true,  // Smart quotes
  breaks: true        // Convert \n to <br>
});

// Add plugins
md.use(require('markdown-it-emoji'));

// Custom renderer
md.renderer.rules.heading_open = (tokens, idx) => {
  const level = tokens[idx].tag.slice(1); // h1 -> 1
  return `<InkHeading level={${level}}>`;
};

md.renderer.rules.heading_close = () => {
  return '</InkHeading>';
};

// Parse and render
const tokens = md.parse(markdown, {});
const html = md.renderer.render(tokens, md.options, {});

// Convert to Ink components
const inkComponents = htmlToInk(html);
```

---

## 3. remark (unified ecosystem)

**GitHub:** https://github.com/remarkjs/remark
**Stars:** ~7k (unified: 4k) | **Bundle Size:** ~50KB core
**License:** MIT

### Features

#### ✅ Core Philosophy: AST-First
```javascript
// Unified pipeline
unified()
  .use(remarkParse)        // markdown → mdast
  .use(remarkGfm)          // Add GFM support
  .use(remarkToc)          // Generate TOC
  .use(remarkRehype)       // mdast → hast
  .use(rehypeHighlight)    // Syntax highlighting
  .use(rehypeStringify)    // hast → html
  .process(markdown);
```

#### ✅ What It Supports (via plugins)
- **Tables**: `remark-gfm`
- **Code blocks**: `remark-code-titles`, `remark-prism`
- **Math**: `remark-math` + `rehype-katex`
- **Mermaid**: `remark-mermaid` (AST transform!)
- **Emoji**: `remark-emoji`
- **TOC**: `remark-toc` (auto-generated)
- **Front matter**: `remark-frontmatter`
- **Directives**: `remark-directive` (::note{}, :::warning)
- **Custom syntax**: Easy to add via plugins
- **MDX**: Full React component support (`remark-mdx`)

#### ✅ Plugin Ecosystem (200+ packages)
```javascript
// Common remark plugins
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';           // Tables, strikethrough
import remarkMath from 'remark-math';         // LaTeX math
import remarkEmoji from 'remark-emoji';       // :smile: -> 😄
import remarkToc from 'remark-toc';           // Auto TOC
import remarkFrontmatter from 'remark-frontmatter';
import remarkMermaid from 'remark-mermaidjs'; // Mermaid!

// Rehype plugins (HTML AST)
import rehypeHighlight from 'rehype-highlight';   // Syntax highlighting
import rehypeSlug from 'rehype-slug';             // Header IDs
import rehypeAutolinkHeadings from 'rehype-autolink-headings';

// Custom transformers
function myRemarkPlugin() {
  return (tree) => {
    // Traverse and modify AST
    visit(tree, 'code', (node) => {
      if (node.lang === 'mermaid') {
        // Transform mermaid to ASCII
        node.value = renderMermaidASCII(node.value);
      }
    });
  };
}
```

#### ✅ AST Structure (mdast)
```javascript
{
  type: 'root',
  children: [
    {
      type: 'heading',
      depth: 1,
      children: [{ type: 'text', value: 'Title' }]
    },
    {
      type: 'paragraph',
      children: [
        { type: 'text', value: 'This is ' },
        { type: 'strong', children: [{ type: 'text', value: 'bold' }] }
      ]
    },
    {
      type: 'code',
      lang: 'python',
      value: 'print("Hello")'
    },
    {
      type: 'table',
      align: ['left', 'center', 'right'],
      children: [
        {
          type: 'tableRow',
          children: [
            { type: 'tableCell', children: [{ type: 'text', value: 'Name' }] },
            { type: 'tableCell', children: [{ type: 'text', value: 'Age' }] }
          ]
        }
      ]
    }
  ]
}
```

#### ✅ What Makes It Special
- **AST manipulation**: Transform markdown before rendering
- **Unified ecosystem**: Works with HTML (rehype), plain text (retext)
- **Type-safe**: Full TypeScript support with typed ASTs
- **Composition**: Chain transforms like Babel for markdown
- **Mermaid support**: Can transform at AST level!

#### ❌ What It Doesn't Support
- Nothing! Everything is a plugin away
- But: More setup required

#### 🔧 Extensibility (Most Powerful)
```typescript
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';
import type { Root, Code } from 'mdast';

// Custom plugin to render for Ink
function remarkInk() {
  return (tree: Root) => {
    const inkComponents: any[] = [];

    visit(tree, (node) => {
      switch (node.type) {
        case 'heading':
          inkComponents.push({
            type: 'InkHeader',
            level: node.depth,
            children: extractText(node)
          });
          break;

        case 'code':
          if (node.lang === 'mermaid') {
            // Transform mermaid to ASCII or browser link
            inkComponents.push({
              type: 'MermaidBlock',
              code: node.value,
              renderMode: 'ascii' // or 'browser-link'
            });
          } else {
            inkComponents.push({
              type: 'CodeBlock',
              code: node.value,
              language: node.lang
            });
          }
          break;

        case 'table':
          inkComponents.push({
            type: 'InkTable',
            headers: extractHeaders(node),
            rows: extractRows(node),
            align: node.align
          });
          break;
      }
    });

    return inkComponents;
  };
}

// Usage
const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkInk);

const inkComponents = processor.processSync(markdown);
```

### Pros for Penguin CLI
✅ **Best for custom rendering** (AST-first design)
✅ Mermaid support via AST transform
✅ Most extensible (200+ plugins)
✅ Type-safe AST manipulation
✅ Can transform before rendering (powerful!)
✅ Composable pipeline
✅ Math/LaTeX support
✅ MDX support (if we want React in markdown later)

### Cons
⚠️ Steepest learning curve
⚠️ More setup code
⚠️ AST traversal can be verbose
⚠️ Overkill for simple markdown

### Integration Example
```typescript
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';
import { Box, Text } from 'ink';

function InkMarkdown({ content }: { content: string }) {
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(function inkRenderer() {
      return (tree) => {
        const components: JSX.Element[] = [];
        let key = 0;

        visit(tree, (node) => {
          switch (node.type) {
            case 'heading':
              components.push(
                <Text key={key++} bold color="cyan">
                  {extractText(node)}
                </Text>
              );
              break;

            case 'code':
              if (node.lang === 'mermaid') {
                components.push(
                  <MermaidBlock key={key++} code={node.value} />
                );
              } else {
                components.push(
                  <CodeBlock key={key++} code={node.value} lang={node.lang} />
                );
              }
              break;

            case 'table':
              components.push(
                <TableComponent key={key++} node={node} />
              );
              break;
          }
        });

        return components;
      };
    });

  const ast = processor.parse(content);
  const components = processor.runSync(ast);

  return <Box flexDirection="column">{components}</Box>;
}
```

---

## Recommendation Matrix

| Use Case | Recommended Library | Reason |
|----------|---------------------|---------|
| **Simple markdown** | Custom parser | Lightweight, sufficient |
| **Standard markdown + tables** | **marked** ⭐ | Best balance |
| **Need plugins (emoji, math)** | markdown-it | Rich ecosystem |
| **Custom syntax + mermaid** | **remark/unified** ⭐ | AST manipulation |
| **Future-proof + extensible** | **remark/unified** ⭐ | Most flexible |

## Feature Comparison Table

| Feature | marked | markdown-it | remark/unified |
|---------|--------|-------------|----------------|
| **Bundle Size** | 50KB | 95KB | 50KB+ |
| **Learning Curve** | Easy | Medium | Hard |
| **Tables** | ✅ GFM | ✅ Full | ✅ Plugin |
| **Code Highlighting** | ❌ (manual) | ❌ (manual) | ✅ Plugin |
| **Mermaid** | ❌ (manual) | ❌ (manual) | ✅ Plugin |
| **Math/LaTeX** | ❌ | ✅ Plugin | ✅ Plugin |
| **Emoji** | ❌ | ✅ Plugin | ✅ Plugin |
| **Custom Syntax** | ⚠️ Verbose | ✅ Good | ✅ Excellent |
| **AST Manipulation** | ❌ | ⚠️ Limited | ✅ Full |
| **TypeScript** | ✅ | ✅ | ✅ Excellent |
| **Maintenance** | ✅ Active | ✅ Active | ✅ Active |
| **Ink Integration** | ⚠️ Need renderer | ⚠️ Need renderer | ✅ Natural fit |

## Final Recommendation for Penguin

### Phase 2 (Now): Keep Custom + `cli-table3`
- Add `cli-table3` for better table rendering
- Fix current issues
- Keep it simple

### Phase 3 (Next): Migrate to **remark/unified**
**Why?**
1. **Mermaid support** built-in via plugins
2. **AST-first** = perfect for custom Ink rendering
3. **Most extensible** for future needs
4. **Type-safe** with full TypeScript support
5. **Math/LaTeX** if needed later
6. **MDX support** if we want React components in markdown

**Migration would be**:
```typescript
// Before (custom)
<Markdown content={text} />

// After (remark)
<RemarkMarkdown content={text} />
// Same API, more features!
```

This gives us:
- Tables ✅
- Mermaid ✅ (via `remark-mermaidjs`)
- Math ✅ (via `remark-math`)
- Code highlighting ✅ (via `rehype-highlight`)
- Future extensibility ✅
