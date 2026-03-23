/**
 * Dashboard Component
 *
 * General purpose dashboard for:
 * - Project management
 * - Session overview
 * - Settings
 * - Statistics
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useTab } from '../contexts/TabContext.js';

type DashboardView = 'overview' | 'projects' | 'settings' | 'stats';

export function Dashboard() {
  const [selectedView, setSelectedView] = useState<DashboardView>('overview');
  const { switchToChat, tabs, activeTabId, switchTab } = useTab();

  useInput((input, key) => {
    // Esc to return to chat
    if (key.escape) {
      switchToChat();
    }
    // Ctrl+P to cycle through tabs
    else if (key.ctrl && input === 'p') {
      const currentIndex = tabs.findIndex(t => t.id === activeTabId);
      const nextIndex = (currentIndex + 1) % tabs.length;
      switchTab(tabs[nextIndex].id);
    }
    // Number keys to switch views
    else if (input === '1') setSelectedView('overview');
    else if (input === '2') setSelectedView('projects');
    else if (input === '3') setSelectedView('settings');
    else if (input === '4') setSelectedView('stats');
  });

  const renderNavigation = () => (
    <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1} marginBottom={1}>
      <Box flexDirection="column">
        <Text bold color="cyan">🏠 Dashboard</Text>
        <Box marginTop={1}>
          <Text dimColor>
            [1] Overview  [2] Projects  [3] Settings  [4] Stats  [Esc] Back to Chat
          </Text>
        </Box>
      </Box>
    </Box>
  );

  const renderOverview = () => (
    <Box flexDirection="column" paddingX={2}>
      <Box marginBottom={1}>
        <Text bold color="green">📊 Overview</Text>
      </Box>

      <Box flexDirection="column" gap={1}>
        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>🚀 Quick Actions</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Type a message to start chatting</Text>
              <Text dimColor>• Use /help to see available commands</Text>
              <Text dimColor>• Ctrl+O for quick session picker</Text>
              <Text dimColor>• Ctrl+P to toggle Dashboard</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>💡 Tip of the Day</Text>
            <Box marginTop={1}>
              <Text>Use workflow commands like /init, /review, and /plan for structured project assistance!</Text>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );

  const renderProjects = () => (
    <Box flexDirection="column" paddingX={2}>
      <Box marginBottom={1}>
        <Text bold color="blue">📂 Project Management</Text>
      </Box>

      <Box flexDirection="column" gap={1}>
        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>Current Workspace</Text>
            <Box marginTop={1}>
              <Text color="cyan">{process.cwd()}</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>🔧 Project Commands</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• /init - Initialize project with AI assistance</Text>
              <Text dimColor>• /review - Get AI code review</Text>
              <Text dimColor>• /plan &lt;feature&gt; - Create implementation plan</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>📋 Coming Soon</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Project templates and scaffolding</Text>
              <Text dimColor>• Task tracking and TODO management</Text>
              <Text dimColor>• Git integration and branch management</Text>
              <Text dimColor>• Custom workflow automation</Text>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );

  const renderSettings = () => (
    <Box flexDirection="column" paddingX={2}>
      <Box marginBottom={1}>
        <Text bold color="yellow">⚙️ Settings</Text>
      </Box>

      <Box flexDirection="column" gap={1}>
        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>🌐 Connection</Text>
            <Box marginTop={1} flexDirection="column">
              <Text>Server: <Text color="green">ws://localhost:8000</Text></Text>
              <Text dimColor>Status: Connected</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>🎨 Preferences</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Theme: Dark (default)</Text>
              <Text dimColor>• Show banner: Yes</Text>
              <Text dimColor>• Show reasoning: Yes</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>⌨️ Keyboard Shortcuts</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Ctrl+C/D - Exit application</Text>
              <Text dimColor>• Ctrl+P - Toggle Dashboard</Text>
              <Text dimColor>• Ctrl+O - Quick session picker</Text>
              <Text dimColor>• Enter - Send message / New line</Text>
              <Text dimColor>• Esc - Send message (from input)</Text>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );

  const renderStats = () => (
    <Box flexDirection="column" paddingX={2}>
      <Box marginBottom={1}>
        <Text bold color="magenta">📈 Statistics</Text>
      </Box>

      <Box flexDirection="column" gap={1}>
        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>💬 Session Stats</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Total conversations: Coming soon</Text>
              <Text dimColor>• Total messages: Coming soon</Text>
              <Text dimColor>• Average session length: Coming soon</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>🔧 Tool Usage</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Most used tools: Coming soon</Text>
              <Text dimColor>• Tool execution success rate: Coming soon</Text>
            </Box>
          </Box>
        </Box>

        <Box borderStyle="round" borderColor="gray" padding={1}>
          <Box flexDirection="column">
            <Text bold>⏱️ Performance</Text>
            <Box marginTop={1} flexDirection="column">
              <Text dimColor>• Average response time: Coming soon</Text>
              <Text dimColor>• Tokens used: Coming soon</Text>
              <Text dimColor>• Uptime: Coming soon</Text>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );

  const renderContent = () => {
    switch (selectedView) {
      case 'overview':
        return renderOverview();
      case 'projects':
        return renderProjects();
      case 'settings':
        return renderSettings();
      case 'stats':
        return renderStats();
      default:
        return renderOverview();
    }
  };

  return (
    <Box flexDirection="column" padding={1}>
      {renderNavigation()}
      {renderContent()}
    </Box>
  );
}
