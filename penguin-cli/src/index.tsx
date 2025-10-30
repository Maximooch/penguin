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
import { TabProvider } from './ui/contexts/TabContext';
import { ThemeProvider } from './ui/theme/ThemeContext.js';
import { isSetupComplete } from './config/loader.js';
import chalk from 'chalk';

// Clear the terminal on startup
console.clear();

// Check if setup is complete before starting
async function checkSetup() {
  const setupComplete = await isSetupComplete();

  if (!setupComplete) {
    console.log(chalk.yellow.bold('\n⚠️  Penguin Setup Required\n'));
    console.log('It looks like this is your first time running Penguin, or your configuration is incomplete.\n');
    console.log('Please run the setup wizard to configure your environment:\n');
    console.log(chalk.cyan('  npm run setup\n'));
    console.log('Or configure manually by editing:');
    console.log(chalk.dim('  ~/.config/penguin/config.yml\n'));
    console.log('Then set your API key:');
    console.log(chalk.dim('  export OPENROUTER_API_KEY="your-key-here"\n'));

    const readline = require('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });

    rl.question(chalk.bold('Press Enter to exit and run setup, or type "skip" to continue anyway: '), (answer: string) => {
      rl.close();
      if (answer.toLowerCase() !== 'skip') {
        console.log(chalk.yellow('\nExiting... Please run: npm run setup\n'));
        process.exit(0);
      } else {
        console.log(chalk.yellow('\n⚠️  Continuing without complete setup. Some features may not work.\n'));
        startApp();
      }
    });
  } else {
    startApp();
  }
}

function startApp() {
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
    <ThemeProvider>
      <CommandProvider>
        <TabProvider initialConversationId={conversationId}>
          <ConnectionProvider url={url} conversationId={conversationId} agentId={agentId}>
            <SessionProvider initialSession={{ conversationId, agentId }}>
              <App />
            </SessionProvider>
          </ConnectionProvider>
        </TabProvider>
      </CommandProvider>
    </ThemeProvider>
  );

  // Wait for app to exit naturally (Ink handles Ctrl+C internally)
  waitUntilExit().catch((error) => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}

// Run setup check before starting
checkSetup();
