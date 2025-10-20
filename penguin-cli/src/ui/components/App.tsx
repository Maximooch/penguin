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
  const { activeTab, tabs, activeTabId } = useTab();

  // Get workspace from current directory
  const workspace = process.cwd().split('/').pop() || process.cwd();

  // Render all tabs but only show the active one
  // This preserves state when switching tabs
  const renderAllTabs = () => {
    return (
      <>
        {tabs.map((tab) => {
          const isActive = tab.id === activeTabId;

          return (
            <Box key={tab.id} display={isActive ? 'flex' : 'none'} flexDirection="column">
              {tab.type === 'chat' && (
                <ChatSession conversationId={tab.conversationId} isActive={isActive} />
              )}
              {tab.type === 'dashboard' && <SessionsTab />}
              {tab.type === 'tasks' && (
                <Box padding={2}>📋 Tasks tab - Coming soon!</Box>
              )}
              {tab.type === 'agents' && (
                <Box padding={2}>🤖 Agents tab - Coming soon!</Box>
              )}
            </Box>
          );
        })}
      </>
    );
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

      {/* All tabs (only active one visible) */}
      <Box marginTop={1}>
        {renderAllTabs()}
      </Box>
    </Box>
  );
}
