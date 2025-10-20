/**
 * TabBar Component
 *
 * Compact top bar showing all tabs with active tab highlighted
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTab } from '../contexts/TabContext.js';

const TAB_ICONS: Record<string, string> = {
  chat: '💬',
  sessions: '📂',
  tasks: '📋',
  agents: '🤖',
};

export function TabBar() {
  const { tabs, activeTabId } = useTab();

  return (
    <Box borderStyle="round" borderColor="gray" paddingX={1}>
      {tabs.map((tab, index) => {
        const isActive = tab.id === activeTabId;
        const icon = TAB_ICONS[tab.type] || '📄';
        const tabNumber = index + 1;

        return (
          <Box key={tab.id} marginRight={1}>
            <Text
              color={isActive ? 'cyan' : 'gray'}
              bold={isActive}
              inverse={isActive}
            >
              {' '}
              {tabNumber}:{icon} {tab.title}
              {isActive ? '*' : ''}{' '}
            </Text>
            {index < tabs.length - 1 && (
              <Text dimColor> │ </Text>
            )}
          </Box>
        );
      })}
      <Box flexGrow={1} justifyContent="flex-end">
        <Text dimColor> Ctrl+P: Switch</Text>
      </Box>
    </Box>
  );
}
