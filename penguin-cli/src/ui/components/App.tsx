/**
 * Main Penguin CLI App Component
 * Phase 2: Tab-based interface with multiple views
 *
 * REFACTORED: Now uses TabContext for managing different views
 */

import React, { useState, useMemo } from 'react';
import { Box } from 'ink';
import { useTab } from '../contexts/TabContext.js';
import { ChatSession } from './ChatSession.js';
import { Dashboard } from './Dashboard.js';
import { MultiAgentLayout } from './MultiAgentLayout.js';
import { TabBar } from './TabBar.js';
import { BannerRenderer } from './BannerRenderer.js';

// Memoized banner - won't re-render unless props change
const MemoizedBanner = React.memo(BannerRenderer);

export function App() {
  const [showBanner] = useState(true);
  const { activeTab, currentConversationId } = useTab();

  // Get workspace from current directory - memoized to prevent re-renders
  const workspace = useMemo(() => process.cwd().split('/').pop() || process.cwd(), []);

  // Render active tab content
  const renderTabContent = () => {
    if (!activeTab) return null;

    switch (activeTab.type) {
      case 'chat':
        return <ChatSession conversationId={currentConversationId} />;
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
      {/* Banner - only shown on chat tab */}
      {showBanner && activeTab?.type === 'chat' && (
        <MemoizedBanner
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
