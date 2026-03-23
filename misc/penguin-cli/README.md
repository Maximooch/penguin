# Penguin CLI (TypeScript + Ink)

> React-based terminal interface for Penguin AI Assistant

## Overview

This is the next-generation CLI for Penguin, built with:
- **Ink** - React for terminal UIs
- **TypeScript** - Type-safe development
- **WebSocket** - Real-time streaming from FastAPI backend

## Architecture

```
┌─────────────────────┐
│  penguin-cli (Ink)  │  ← This package
│  TypeScript/React   │
└──────────┬──────────┘
           │ WebSocket
┌──────────▼──────────┐
│  penguin (Python)   │  ← Existing backend
│  FastAPI + Core     │
└─────────────────────┘
```

## Development

```bash
# Install dependencies
npm install

# Run in development mode (with watch)
npm run dev

# Build for production
npm run build

# Run built version
npm start
```

## Requirements

- Node.js >= 18.0.0
- Python backend running on `http://localhost:8000` (see `../penguin/`)

## Project Structure

```
penguin-cli/
├── src/
│   ├── index.tsx           # Entry point
│   ├── components/         # Ink React components
│   │   ├── App.tsx         # Main app component
│   │   ├── ChatSession.tsx # Chat interface
│   │   └── ...
│   ├── hooks/              # Custom React hooks
│   │   ├── useChat.ts      # WebSocket chat hook
│   │   └── ...
│   ├── api/                # Backend API client
│   │   └── client.ts       # WebSocket/REST client
│   └── utils/              # Utilities
│       └── ...
├── package.json
├── tsconfig.json
└── README.md
```

## Status

**Phase 1: Proof of Concept** (Current)
- [x] Project scaffolding
- [ ] Basic WebSocket client
- [ ] Hello-world Ink component
- [ ] Streaming message display
- [ ] Compare with Python CLI

See `../context/penguin_todo_ink_cli.md` for full migration plan.
