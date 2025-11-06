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
import { Dashboard } from './Dashboard.js';
import { MultiAgentLayout } from './MultiAgentLayout.js';
import { TabBar } from './TabBar.js';
import { BannerRenderer } from './BannerRenderer.js';

export function App() {
  const [showBanner] = useState(true);
  const [bannerRendered] = useState(true); // Only render banner once
  const { activeTab, currentConversationId } = useTab();

  // Get workspace from current directory
  const workspace = process.cwd().split('/').pop() || process.cwd();

  // Render banner (only for chat tab, passed to ChatSession)
  const banner = showBanner && activeTab?.type === 'chat' ? (
    <BannerRenderer
      version="0.1.0"
      workspace={workspace}
    />
  ) : undefined;

  // Render active tab content
  const renderTabContent = () => {
    if (!activeTab) return null;

    switch (activeTab.type) {
      case 'chat':
        return <ChatSession conversationId={currentConversationId} header={banner} />;
      case 'dashboard':
        return <Dashboard />;
      case 'agents':
        return <MultiAgentLayout />;
      default:
        return null;
    }
  };

  return (
    <Box flexDirection="column" padding={1}>
      {/* Tab bar */}
      <TabBar />

      {/* Active tab content */}
      <Box marginTop={1}>
        {renderTabContent()}
      </Box>
    </Box>
  );
}
