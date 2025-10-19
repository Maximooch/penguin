/**
 * Input prompt component
 * Shows current user input with visual feedback
 */

import React from 'react';
import { Box, Text } from 'ink';

export interface InputPromptProps {
  value: string;
  isStreaming: boolean;
  isConnected: boolean;
}

export function InputPrompt({ value, isStreaming, isConnected }: InputPromptProps) {
  const disabled = isStreaming || !isConnected;
  const promptColor = disabled ? 'gray' : 'green';
  const cursorChar = disabled ? '' : '▊';

  return (
    <Box borderStyle="single" borderColor={promptColor} paddingX={1}>
      <Text color={promptColor} bold>
        {'> '}
      </Text>
      <Text dimColor={disabled}>
        {value}
        {!disabled && <Text color={promptColor}>{cursorChar}</Text>}
      </Text>
    </Box>
  );
}
