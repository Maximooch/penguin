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
import { CommandProvider } from './ui/contexts/CommandContext';

// Clear the terminal on startup
console.clear();

// Parse command line arguments
const args = process.argv.slice(2);
const providedConversationId = args.find(arg => arg.startsWith('--conversation='))?.split('=')[1];
const agentId = args.find(arg => arg.startsWith('--agent='))?.split('=')[1];
const url = args.find(arg => arg.startsWith('--url='))?.split('=')[1] || 'ws://localhost:8000/api/v1/chat/stream';

// Generate a new conversation ID if not provided
// Format: session_YYYYMMDD_HHMMSS_random (matches backend format)
const generateConversationId = (): string => {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  const random = Math.random().toString(36).substring(2, 10);

  return `session_${year}${month}${day}_${hours}${minutes}${seconds}_${random}`;
};

const conversationId = providedConversationId || generateConversationId();

// Render the app with context providers
const { waitUntilExit } = render(
  <CommandProvider>
    <ConnectionProvider url={url} conversationId={conversationId} agentId={agentId}>
      <SessionProvider initialSession={{ conversationId, agentId }}>
        <App />
      </SessionProvider>
    </ConnectionProvider>
  </CommandProvider>
);

// Wait for app to exit naturally (Ink handles Ctrl+C internally)
waitUntilExit().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
