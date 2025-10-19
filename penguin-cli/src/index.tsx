#!/usr/bin/env node

/**
 * Penguin CLI - Entry Point
 * TypeScript + Ink terminal interface
 */

import React from 'react';
import { render } from 'ink';
import { App } from './components/App';

// Parse command line arguments
const args = process.argv.slice(2);
const conversationId = args.find(arg => arg.startsWith('--conversation='))?.split('=')[1];
const agentId = args.find(arg => arg.startsWith('--agent='))?.split('=')[1];

// Render the app with proper exit handling
const { waitUntilExit } = render(
  <App conversationId={conversationId} agentId={agentId} />
);

// Wait for app to exit naturally (Ink handles Ctrl+C internally)
waitUntilExit().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
