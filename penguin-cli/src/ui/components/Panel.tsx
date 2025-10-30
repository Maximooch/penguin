import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../theme/ThemeContext.js';

interface PanelProps {
  title?: string;
  children: React.ReactNode;
  borderColor?: string;
  paddingY?: number;
  paddingX?: number;
}

export function Panel({ title, children, borderColor, paddingY = 0, paddingX = 1 }: PanelProps) {
  const { theme: tokens } = useTheme();
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={borderColor || tokens.border.default} paddingY={paddingY} paddingX={paddingX}>
      {title && (
        <Box marginBottom={tokens.spacing.sm}>
          <Text color={tokens.brand.accent} bold>
            {title}
          </Text>
        </Box>
      )}
      {children}
    </Box>
  );
}
