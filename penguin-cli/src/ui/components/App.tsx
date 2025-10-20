/**
 * Main Penguin CLI App Component
 * Phase 1: Basic chat interface with streaming support
 *
 * REFACTORED: No longer passes props - uses contexts instead
 * Now uses adaptive banner with pixel art penguin!
 */

import React, { useState } from 'react';
import { Box } from 'ink';
import { ChatSession } from './ChatSession';
import { BannerRenderer } from './BannerRenderer';

export function App() {
  const [showBanner] = useState(true);

  // Get workspace from current directory
  const workspace = process.cwd().split('/').pop() || process.cwd();

  return (
    <Box flexDirection="column" padding={1}>
      {showBanner && (
        <BannerRenderer
          version="0.1.0"
          workspace={workspace}
        />
      )}

      <ChatSession />
    </Box>
  );
}
