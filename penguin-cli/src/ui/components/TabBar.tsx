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
  dashboard: '🏠',
  tasks: '📋',
  agents: '🤖',
};

export function TabBar() {
  const { tabs, activeTabId } = useTab();

  return (
    <Box borderStyle="single" borderColor="cyan" borderDimColor paddingX={1}>
      {tabs.map((tab, index) => {
        const isActive = tab.id === activeTabId;
        const icon = TAB_ICONS[tab.type] || '📄';
        const tabNumber = index + 1;

        return (
          <Box key={tab.id} marginRight={1}>
            <Text
              color={isActive ? 'cyan' : undefined}
              bold={isActive}
              dimColor={!isActive}
            >
              {' '}
              {tabNumber}:{icon} {tab.title}
              {isActive ? ' *' : ''}{' '}
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
