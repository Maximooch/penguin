# Penguin CLI - Quick Start Guide

## Phase 1 Proof of Concept

This is the initial TypeScript + Ink implementation of Penguin's terminal interface.

## Prerequisites

1. **Python backend running:**
   ```bash
   # From the main penguin directory
   cd ../penguin
   python -m penguin.api.server
   # or
   uvicorn penguin.api.server:app --reload
   ```

   The backend should be accessible at `http://localhost:8000`

2. **Node.js >= 18**
   ```bash
   node --version  # Should be >= 18
   ```

## Installation

```bash
# Install dependencies (already done if you see node_modules/)
npm install
```

## Running

### Development Mode (with watch/reload)
```bash
npm run dev
```

### Build and Run
```bash
npm run build
npm start
```

### Run directly with tsx
```bash
npx tsx src/index.tsx
```

## Testing the WebSocket Connection

### Step 1: Start Python Backend
```bash
# In terminal 1
cd /Users/maximusputnam/Code/Penguin/penguin
python -m penguin.api.server
```

Expected output:
```
🐧 Penguin AI Server
Visit http://localhost:8000 to start using Penguin!
API documentation: http://localhost:8000/api/docs
```

### Step 2: Start CLI
```bash
# In terminal 2
cd /Users/maximusputnam/Code/Penguin/penguin/penguin-cli
npm run dev
```

You should see:
```
🐧 Penguin AI - TypeScript CLI (Ink)
✓ Connected

> _
```

### Step 3: Send a Test Message
Type: `Hello from the new Ink CLI!`
Press Enter

You should see the assistant's streaming response appear with a typewriter effect.

## Troubleshooting

### "WebSocket connection failed"
- Make sure Python backend is running on port 8000
- Check: `curl http://localhost:8000/` should return JSON

### "Cannot find module 'ws'"
- Run: `npm install`

### TypeScript errors
- Run: `npm run typecheck`
- Fix: `npm run build`

## Features Implemented (Phase 1)

- ✅ WebSocket client with auto-reconnect
- ✅ Token batching (50 tokens or 50ms)
- ✅ Basic chat UI with Ink components
- ✅ Streaming message display with cursor
- ✅ Connection status indicator
- ✅ Keyboard input handling
- ✅ Graceful shutdown (Ctrl+C)

## Next Steps

- [ ] Add syntax highlighting for code blocks
- [ ] Implement tool execution display
- [ ] Add multi-line input support
- [ ] Create diff rendering
- [ ] Tab-based multi-session UI

See `../context/penguin_todo_ink_cli.md` for full roadmap.
