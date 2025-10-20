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

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { CommandAutocomplete } from './CommandAutocomplete';

interface MultiLineInputProps {
  onSubmit: (value: string) => void;
  placeholder?: string;
  isDisabled?: boolean;
  onTextChange?: (text: string) => void;
  suggestions?: string[];
}

export function MultiLineInput({
  onSubmit,
  placeholder = 'Type your message...',
  isDisabled = false,
  onTextChange,
  suggestions = []
}: MultiLineInputProps) {
  const [lines, setLines] = useState<string[]>(['']);
  const [cursorLine, setCursorLine] = useState(0);
  const [cursorCol, setCursorCol] = useState(0);
  const [selectedSuggestion, setSelectedSuggestion] = useState(0);
  const [showSuggestions, setShowSuggestions] = useState(false);

  // Notify parent of text changes
  useEffect(() => {
    const fullText = lines.join('\n');
    onTextChange?.(fullText);

    // Show autocomplete if text starts with /
    if (fullText.startsWith('/') && suggestions.length > 0) {
      setShowSuggestions(true);
      setSelectedSuggestion(0);
    } else {
      setShowSuggestions(false);
    }
  }, [lines, onTextChange, suggestions.length]);

  useInput((input, key) => {
    if (isDisabled) return;

    // Handle autocomplete navigation
    if (showSuggestions && suggestions.length > 0) {
      // Tab to cycle through suggestions
      if (key.tab) {
        setSelectedSuggestion(prev => (prev + 1) % suggestions.length);
        return;
      }

      // Up/Down arrows to navigate suggestions
      if (key.upArrow) {
        setSelectedSuggestion(prev => (prev - 1 + suggestions.length) % suggestions.length);
        return;
      }

      if (key.downArrow) {
        setSelectedSuggestion(prev => (prev + 1) % suggestions.length);
        return;
      }

      // Enter to accept suggestion
      if (key.return && cursorLine === 0) {
        const selected = suggestions[selectedSuggestion];
        setLines([selected + ' ']);
        setCursorCol(selected.length + 1);
        setShowSuggestions(false);
        return;
      }
    }

    // Submit on Escape key (more reliable than Ctrl+Enter)
    if (key.escape) {
      // Dismiss autocomplete first if showing
      if (showSuggestions) {
        setShowSuggestions(false);
        return;
      }

      const fullText = lines.join('\n').trim();
      if (fullText) {
        onSubmit(fullText);
        setLines(['']);
        setCursorLine(0);
        setCursorCol(0);
      }
      return;
    }

    // New line on Enter (only if not handling autocomplete)
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
    <Box flexDirection="column">
      {/* Autocomplete suggestions */}
      {showSuggestions && suggestions.length > 0 && (
        <CommandAutocomplete suggestions={suggestions} selectedIndex={selectedSuggestion} />
      )}

      {/* Input box */}
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
            {showSuggestions
              ? 'Tab/↑↓: Navigate • Enter: Select • Esc: Dismiss'
              : 'Enter: New line • Esc: Send message'}
          </Text>
        </Box>
      </Box>
    </Box>
  );
}
