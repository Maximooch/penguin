#!/usr/bin/env node

/**
 * Penguin CLI - Entry Point
 * TypeScript + Ink terminal interface
 *
 * REFACTORED: Now wraps App with context providers
 */

import React from 'react';
import { render } from 'ink';
import { App } from './ui/components/App';
import { ConnectionProvider } from './ui/contexts/ConnectionContext';
import { SessionProvider } from './ui/contexts/SessionContext';

// Clear the terminal on startup
console.clear();

// Parse command line arguments
const args = process.argv.slice(2);
const conversationId = args.find(arg => arg.startsWith('--conversation='))?.split('=')[1];
const agentId = args.find(arg => arg.startsWith('--agent='))?.split('=')[1];
const url = args.find(arg => arg.startsWith('--url='))?.split('=')[1] || 'ws://localhost:8000/api/v1/chat/stream';

// Render the app with context providers
const { waitUntilExit } = render(
  <ConnectionProvider url={url} conversationId={conversationId} agentId={agentId}>
    <SessionProvider initialSession={{ conversationId, agentId }}>
      <App />
    </SessionProvider>
  </ConnectionProvider>
);

// Wait for app to exit naturally (Ink handles Ctrl+C internally)
waitUntilExit().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
