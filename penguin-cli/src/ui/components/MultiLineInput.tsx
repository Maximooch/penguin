/**
 * Multi-line text input component for Ink
 * Esc to submit (like vim), Enter for new lines
 *
 * Features:
 * - Enter: New line
 * - Esc: Submit (reliable key detection)
 * - Backspace/Delete for editing
 * - Arrow keys for cursor movement
 * - Visual cursor indicator
 *
 * Note: Ctrl+Enter doesn't work reliably in Ink, so we use Esc instead
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';

interface MultiLineInputProps {
  onSubmit: (value: string) => void;
  placeholder?: string;
  isDisabled?: boolean;
}

export function MultiLineInput({ onSubmit, placeholder = 'Type your message...', isDisabled = false }: MultiLineInputProps) {
  const [lines, setLines] = useState<string[]>(['']);
  const [cursorLine, setCursorLine] = useState(0);
  const [cursorCol, setCursorCol] = useState(0);

  useInput((input, key) => {
    if (isDisabled) return;

    // Submit on Escape key (more reliable than Ctrl+Enter)
    if (key.escape) {
      const fullText = lines.join('\n').trim();
      if (fullText) {
        onSubmit(fullText);
        setLines(['']);
        setCursorLine(0);
        setCursorCol(0);
      }
      return;
    }

    // New line on Enter
    if (key.return) {
      setLines(prev => {
        const newLines = [...prev];
        const currentLine = newLines[cursorLine];
        const before = currentLine.substring(0, cursorCol);
        const after = currentLine.substring(cursorCol);

        newLines[cursorLine] = before;
        newLines.splice(cursorLine + 1, 0, after);

        return newLines;
      });
      setCursorLine(prev => prev + 1);
      setCursorCol(0);
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      if (cursorCol === 0 && cursorLine > 0) {
        // Join with previous line
        setLines(prev => {
          const newLines = [...prev];
          const prevLineLength = newLines[cursorLine - 1].length;
          newLines[cursorLine - 1] += newLines[cursorLine];
          newLines.splice(cursorLine, 1);
          return newLines;
        });
        setCursorLine(prev => prev - 1);
        setCursorCol(lines[cursorLine - 1].length);
      } else if (cursorCol > 0) {
        // Delete character
        setLines(prev => {
          const newLines = [...prev];
          newLines[cursorLine] =
            newLines[cursorLine].substring(0, cursorCol - 1) +
            newLines[cursorLine].substring(cursorCol);
          return newLines;
        });
        setCursorCol(prev => prev - 1);
      }
      return;
    }

    // Arrow keys
    if (key.upArrow && cursorLine > 0) {
      setCursorLine(prev => prev - 1);
      setCursorCol(Math.min(cursorCol, lines[cursorLine - 1].length));
      return;
    }

    if (key.downArrow && cursorLine < lines.length - 1) {
      setCursorLine(prev => prev + 1);
      setCursorCol(Math.min(cursorCol, lines[cursorLine + 1].length));
      return;
    }

    if (key.leftArrow && cursorCol > 0) {
      setCursorCol(prev => prev - 1);
      return;
    }

    if (key.rightArrow && cursorCol < lines[cursorLine].length) {
      setCursorCol(prev => prev + 1);
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta) {
      setLines(prev => {
        const newLines = [...prev];
        newLines[cursorLine] =
          newLines[cursorLine].substring(0, cursorCol) +
          input +
          newLines[cursorLine].substring(cursorCol);
        return newLines;
      });
      setCursorCol(prev => prev + input.length);
    }
  });

  const isEmpty = lines.length === 1 && lines[0] === '';

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={isDisabled ? 'gray' : 'cyan'} paddingX={1}>
      {isEmpty && (
        <Text dimColor>{placeholder}</Text>
      )}

      {!isEmpty && lines.map((line, lineIndex) => {
        if (lineIndex === cursorLine) {
          // Show cursor on current line
          const before = line.substring(0, cursorCol);
          const cursor = line[cursorCol] || ' ';
          const after = line.substring(cursorCol + 1);

          return (
            <Box key={lineIndex}>
              <Text>{before}</Text>
              <Text inverse>{cursor}</Text>
              <Text>{after}</Text>
            </Box>
          );
        }

        return <Text key={lineIndex}>{line || ' '}</Text>;
      })}

      <Box marginTop={1}>
        <Text dimColor color="gray">
          Enter: New line • Esc: Send message
        </Text>
      </Box>
    </Box>
  );
}
