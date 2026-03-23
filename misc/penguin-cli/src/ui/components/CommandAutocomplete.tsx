/**
 * Command Autocomplete Component
 *
 * Shows command suggestions when user types slash commands.
 */

import React from 'react';
import { Box, Text } from 'ink';

interface CommandAutocompleteProps {
  suggestions: string[];
  selectedIndex: number;
}

export function CommandAutocomplete({ suggestions, selectedIndex }: CommandAutocompleteProps) {
  if (suggestions.length === 0) return null;

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="yellow" paddingX={1} marginBottom={1}>
      <Box>
        <Text bold color="yellow">
          💡 Command Suggestions
        </Text>
      </Box>

      {suggestions.map((suggestion, index) => {
        const isSelected = index === selectedIndex;
        return (
          <Box key={suggestion}>
            <Text color={isSelected ? 'cyan' : 'white'} bold={isSelected}>
              {isSelected ? '→ ' : '  '}
              {suggestion}
            </Text>
          </Box>
        );
      })}

      <Box marginTop={1}>
        <Text dimColor color="gray">
          Tab: Select • Enter: Accept • Esc: Dismiss
        </Text>
      </Box>
    </Box>
  );
}
