# Visual Mockups: Banner Styles

## Option 1: Terminal-Image (iTerm2/Kitty Only)

**Full pixel art with true colors:**

```
╔════════════════════════════════════════════════════════════════════════╗
║                                                                        ║
║                     [ACTUAL PIXEL ART RENDERED]                        ║
║                                                                        ║
║              Vaporwave penguin with cyan/pink/purple                   ║
║              gradients, full color depth, smooth rendering             ║
║                                                                        ║
║              40 chars wide × 20 lines tall                             ║
║                                                                        ║
╚════════════════════════════════════════════════════════════════════════╝

v0.1.0 • AI-Powered Development Assistant
📁 Workspace: penguin-cli
Type /help for commands • /init to get started
```

**Pros:**
- ✅ Shows actual image with full colors
- ✅ Preserves vaporwave gradient aesthetic
- ✅ Looks **stunning** in modern terminals
- ✅ Can scale image to fit terminal width

**Cons:**
- ❌ Only works in iTerm2, Kitty, WezTerm
- ❌ Terminal capabilities detection needed
- ❌ Image file must be accessible
- ❌ ~100-200ms render time

---

## Option 2: Colored ASCII Conversion (Universal)

**ASCII blocks with 256-color palette:**

```
                    ████████████████████
                ████▓▓▓▓▓▓▓▓▓▓██████████
              ██░░░░▒▒▒▒▓▓▓▓████████████
            ██░░░░░░▒▒▒▒▓▓▓▓██████▓▓▓▓██
            ██░░░░░░░░▒▒▒▒▓▓▓▓████▓▓▓▓██
            ██░░░░░░░░░░▒▒▒▒▓▓████▓▓▓▓██
              ██░░░░░░░░▒▒▓▓▓▓████▓▓▓▓██
              ████░░░░░░▒▒▓▓████████▓▓██
                ████░░░░▒▒▓▓████████████
                  ████░░▒▒████████████
                  ██████▒▒████████▓▓
                    ██████████████▓▓
                    ████████████▓▓
                    ██████████▓▓
                    ████████▓▓
                    ██████▓▓
                    ████▓▓
                    ████
                  ██████
                ████████
              ██████████
            ████████████
          ████  ████  ████
        ████      ████    ████
      ████          ████      ████
    ████              ████████████

v0.1.0 • AI-Powered Development Assistant
📁 Workspace: penguin-cli
Type /help for commands • /init to get started
```

**Pros:**
- ✅ Works in **any terminal** (bash, zsh, cmd, PowerShell)
- ✅ Uses 256-color ANSI codes (cyan→blue→pink gradient)
- ✅ Instant rendering (<10ms)
- ✅ No external dependencies after generation

**Cons:**
- ❌ Loses some detail compared to pixel art
- ❌ Gradient may be blocky (8 colors vs thousands)
- ❌ Requires pre-conversion of image to ASCII
- ❌ Fixed size (can't easily scale)

---

## Option 3A: Hybrid - Terminal-Image + Figlet Text

**Best for iTerm2/Kitty users:**

```
ooooooooo.                                    o8o
\`888   \`Y88.                                   \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888
 888         888ooo888  888   888  888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o
                                   d"     YD
                                   "Y88888P'

┌────────────────────────────────────────────────────────────────┐
│                                                                │
│               [PIXEL ART PENGUIN - 30 chars wide]              │
│                                                                │
│         Full vaporwave colors, centered, small scale           │
│                                                                │
└────────────────────────────────────────────────────────────────┘

v0.1.0 • AI-Powered Development Assistant
📁 Workspace: penguin-cli • Type /help for commands
```

**Layout:**
- Figlet text: **10 lines** tall
- Spacer: **1 line**
- Pixel art penguin: **15 lines** tall (small scale)
- Info footer: **3 lines**
- **Total: ~29 lines**

---

## Option 3B: Hybrid - Colored ASCII + Figlet Text

**Universal support:**

```
ooooooooo.                                    o8o
\`888   \`Y88.                                   \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888
 888         888ooo888  888   888  888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o
                                   d"     YD
                                   "Y88888P'

              ████████████
          ████▓▓▓▓▓▓██████
        ██░░▒▒▓▓████████▓▓
        ██░░▒▒▓▓████████▓▓
        ██░░▒▒▓▓██████▓▓
          ████▓▓██████▓▓
          ██████████▓▓
          ██████████
          ████████
          ████████
        ████  ████  ██
      ████    ████    ██
    ████        ████████

v0.1.0 • AI-Powered Development Assistant
📁 Workspace: penguin-cli • Type /help for commands
```

**Layout:**
- Figlet text: **10 lines** tall
- Spacer: **1 line**
- ASCII penguin: **13 lines** tall (compact)
- Info footer: **3 lines**
- **Total: ~27 lines**

---

## Option 3C: Side-by-Side Layout

**Figlet text + Penguin side-by-side (wide terminals):**

```
┌──────────────────────────────────────────┬──────────────────────┐
│ ooooooooo.                        o8o    │    ████████████      │
│ \`888   \`Y88.                       \`"'    │  ████▓▓▓▓██████      │
│  888   .d88'  .ooooo.  ooo. .oo.   ...   │██░░▒▒▓▓████████▓▓    │
│  888ooo88P'  d88' \`88b \`888P"Y88b  ...   │██░░▒▒▓▓████████▓▓    │
│  888         888ooo888  888   888  ...   │██░░▒▒▓▓██████▓▓      │
│  888         888    .o  888   888  ...   │  ████▓▓██████▓▓      │
│ o888o        \`Y8bod8P' o888o o888o ...   │  ██████████▓▓        │
│                            d"     YD     │  ██████████          │
│                            "Y88888P'     │  ████████            │
│                                          │  ████████            │
│  v0.1.0 • AI Assistant                   │████  ████  ██        │
│  📁 penguin-cli                          │      ████    ████    │
└──────────────────────────────────────────┴──────────────────────┘
```

**Pros:**
- Compact vertical space (12-13 lines)
- Both elements visible simultaneously
- Good for wide terminals (120+ columns)

**Cons:**
- Doesn't work well in narrow terminals (<100 cols)
- Harder to implement layout logic

---

## Comparison Table

| Feature                  | Terminal-Image | Colored ASCII | Hybrid (Image) | Hybrid (ASCII) |
|--------------------------|----------------|---------------|----------------|----------------|
| **Visual Quality**       | ⭐⭐⭐⭐⭐        | ⭐⭐⭐          | ⭐⭐⭐⭐⭐        | ⭐⭐⭐⭐          |
| **Universal Support**    | ❌ iTerm2 only | ✅ All terms  | ❌ iTerm2 only | ✅ All terms   |
| **Gradient Colors**      | ✅ Full        | ⚠️ 8-256 col  | ✅ Full        | ⚠️ 8-256 col   |
| **Render Speed**         | ~150ms         | <10ms         | ~180ms         | <15ms          |
| **Height (lines)**       | 20-25          | 25-30         | 29             | 27             |
| **File Dependency**      | image.png      | None          | image.png      | None           |
| **Scalability**          | ✅ Dynamic     | ❌ Fixed      | ✅ Dynamic     | ❌ Fixed       |

---

## Recommendations

### Best for Most Users: **Option 3B (Hybrid ASCII)**
- Universal terminal support
- Classic Penguin text (recognizable brand)
- Compact ASCII penguin art (nice accent)
- ~27 lines total (fits in most terminals)
- Fast rendering

### Best for Power Users: **Option 3A (Hybrid Terminal-Image)**
- Detect terminal capabilities
- Fallback to ASCII if not supported
- Best of both worlds
- Worth the extra complexity

### Simplest: **Option 2 (Colored ASCII)**
- Just the penguin, no figlet text
- Great for small terminals
- Still shows vaporwave aesthetic
- Minimalist approach

---

## Implementation Strategy

1. **Start with Option 2** - Get colored ASCII working universally
2. **Add Option 3B** - Combine with figlet text (default)
3. **Add Option 1/3A** - Terminal-image as enhancement (detect iTerm2/Kitty)
4. **Make configurable** - Let users choose their style

```typescript
export interface BannerConfig {
  style: 'ascii' | 'image' | 'hybrid-ascii' | 'hybrid-image' | 'compact';
  detectTerminal: boolean; // Auto-upgrade to image if supported
  maxHeight: number; // Trim for small terminals
  showWorkspace: boolean;
}
```

---

## Next Steps

1. Convert `context/image.png` to colored ASCII
2. Implement terminal capability detection
3. Create BannerConfig system
4. Add `--banner=<style>` CLI flag
5. Test in different terminals (iTerm2, Terminal.app, VSCode, Kitty)
