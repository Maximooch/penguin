/**
 * Main Penguin CLI App Component
 * Phase 2: Tab-based interface with multiple views
 *
 * REFACTORED: Now uses TabContext for managing different views
 */

import React, { useState } from 'react';
import { Box } from 'ink';
import { useTab } from '../contexts/TabContext.js';
import { ChatSession } from './ChatSession.js';
import { SessionsTab } from './SessionsTab.js';
import { TabBar } from './TabBar.js';
import { BannerRenderer } from './BannerRenderer.js';

export function App() {
  const [showBanner] = useState(true);
  const { activeTab } = useTab();

  // Get workspace from current directory
  const workspace = process.cwd().split('/').pop() || process.cwd();

  // Render the active tab content
  const renderTabContent = () => {
    if (!activeTab) return null;

    switch (activeTab.type) {
      case 'chat':
        return <ChatSession />;
      case 'sessions':
        return <SessionsTab />;
      case 'tasks':
        return (
          <Box padding={2}>
            <Box>📋 Tasks tab - Coming soon!</Box>
          </Box>
        );
      case 'agents':
        return (
          <Box padding={2}>
            <Box>🤖 Agents tab - Coming soon!</Box>
          </Box>
        );
      default:
        return null;
    }
  };

  return (
    <Box flexDirection="column" padding={1}>
      {showBanner && (
        <BannerRenderer
          version="0.1.0"
          workspace={workspace}
        />
      )}

      {/* Tab bar */}
      <TabBar />

      {/* Active tab content */}
      <Box marginTop={1}>
        {renderTabContent()}
      </Box>
    </Box>
  );
}
