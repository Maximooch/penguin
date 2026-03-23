#!/usr/bin/env node
/**
 * Standalone setup wizard for Penguin CLI
 * Run with: npm run setup
 */

import { runSetupWizard } from './config/wizard.js';

async function main() {
  try {
    await runSetupWizard();
    process.exit(0);
  } catch (error) {
    if (error instanceof Error && error.message === 'User force closed the prompt') {
      console.log('\nSetup cancelled.');
      process.exit(0);
    }
    console.error('\nSetup failed:', error);
    process.exit(1);
  }
}

main();
