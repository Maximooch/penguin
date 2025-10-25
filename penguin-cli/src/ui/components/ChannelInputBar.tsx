import React, { useState, useCallback } from 'react';
import { Box, Text, useInput } from 'ink';
import { AgentProfile } from '../../core/api/AgentAPI.js';

export interface ChannelInputBarProps {
  agents: AgentProfile[];
  currentChannel: string;
  onSendMessage: (content: string) => Promise<void>;
  onCommand?: (command: string, args: string[]) => Promise<void>;
}

export function ChannelInputBar({
  agents,
  currentChannel,
  onSendMessage,
  onCommand,
}: ChannelInputBarProps) {
  const [input, setInput] = useState('');
  const [cursorPosition, setCursorPosition] = useState(0);
  const [showAutocomplete, setShowAutocomplete] = useState(false);
  const [autocompleteOptions, setAutocompleteOptions] = useState<string[]>([]);
  const [autocompleteIndex, setAutocompleteIndex] = useState(0);

  // Parse input for @mentions and slash commands
  const parseInput = useCallback((text: string) => {
    // Check for @mention at cursor position
    const beforeCursor = text.slice(0, cursorPosition);
    const mentionMatch = beforeCursor.match(/@(\w*)$/);

    if (mentionMatch) {
      const partial = mentionMatch[1].toLowerCase();
      const matches = agents
        .filter((agent) => agent.id.toLowerCase().startsWith(partial))
        .map((agent) => agent.id);

      if (matches.length > 0) {
        setAutocompleteOptions(matches);
        setShowAutocomplete(true);
        return;
      }
    }

    setShowAutocomplete(false);
  }, [agents, cursorPosition]);

  // Handle input changes
  const handleInput = useCallback(
    (char: string) => {
      const newInput = input.slice(0, cursorPosition) + char + input.slice(cursorPosition);
      setInput(newInput);
      setCursorPosition(cursorPosition + 1);
      parseInput(newInput);
    },
    [input, cursorPosition, parseInput]
  );

  // Handle backspace
  const handleBackspace = useCallback(() => {
    if (cursorPosition > 0) {
      const newInput = input.slice(0, cursorPosition - 1) + input.slice(cursorPosition);
      setInput(newInput);
      setCursorPosition(cursorPosition - 1);
      parseInput(newInput);
    }
  }, [input, cursorPosition, parseInput]);

  // Handle autocomplete selection
  const handleAutocompleteSelect = useCallback(() => {
    if (showAutocomplete && autocompleteOptions.length > 0) {
      const selected = autocompleteOptions[autocompleteIndex];
      const beforeCursor = input.slice(0, cursorPosition);
      const mentionMatch = beforeCursor.match(/^(.*)@(\w*)$/);

      if (mentionMatch) {
        const prefix = mentionMatch[1];
        const newInput = prefix + '@' + selected + ' ' + input.slice(cursorPosition);
        setInput(newInput);
        setCursorPosition(prefix.length + selected.length + 2);
        setShowAutocomplete(false);
      }
    }
  }, [showAutocomplete, autocompleteOptions, autocompleteIndex, input, cursorPosition]);

  // Handle send
  const handleSend = useCallback(async () => {
    if (input.trim() === '') return;

    // Check for slash command
    if (input.startsWith('/')) {
      const parts = input.slice(1).split(' ');
      const command = parts[0];
      const args = parts.slice(1);

      if (onCommand) {
        await onCommand(command, args);
      }
    } else {
      await onSendMessage(input);
    }

    setInput('');
    setCursorPosition(0);
    setShowAutocomplete(false);
  }, [input, onSendMessage, onCommand]);

  // Keyboard handling
  useInput(
    (inputChar, key) => {
      // Don't capture Ctrl+P (tab switching) or Esc when no autocomplete
      if (key.ctrl && inputChar === 'p') {
        return; // Let parent handle tab switching
      }
      if (key.escape && !showAutocomplete) {
        return; // Let parent handle Esc
      }

      if (key.return) {
        if (key.shift) {
          // Shift+Enter: new line
          handleInput('\n');
        } else if (showAutocomplete) {
          // Enter with autocomplete: select option
          handleAutocompleteSelect();
        } else {
          // Enter: send message
          handleSend();
        }
      } else if (key.backspace || key.delete) {
        handleBackspace();
      } else if (key.leftArrow) {
        setCursorPosition(Math.max(0, cursorPosition - 1));
      } else if (key.rightArrow) {
        setCursorPosition(Math.min(input.length, cursorPosition + 1));
      } else if (key.upArrow && showAutocomplete) {
        setAutocompleteIndex(Math.max(0, autocompleteIndex - 1));
      } else if (key.downArrow && showAutocomplete) {
        setAutocompleteIndex(Math.min(autocompleteOptions.length - 1, autocompleteIndex + 1));
      } else if (key.tab && showAutocomplete) {
        handleAutocompleteSelect();
      } else if (key.escape) {
        // Only handle Esc if autocomplete is showing
        if (showAutocomplete) {
          setShowAutocomplete(false);
        }
      } else if (inputChar) {
        handleInput(inputChar);
      }
    },
    { isActive: true }
  );

  return (
    <Box flexDirection="column">
      {/* Autocomplete Dropdown */}
      {showAutocomplete && autocompleteOptions.length > 0 && (
        <Box
          flexDirection="column"
          borderStyle="single"
          borderColor="cyan"
          paddingX={1}
          marginBottom={1}
        >
          <Text bold dimColor>
            Mention:
          </Text>
          {autocompleteOptions.slice(0, 5).map((option, idx) => (
            <Text key={option} color={idx === autocompleteIndex ? 'cyan' : 'white'}>
              {idx === autocompleteIndex ? '▸ ' : '  '}@{option}
            </Text>
          ))}
          <Text dimColor>↑↓ Navigate • Tab/Enter: Select • Esc: Cancel</Text>
        </Box>
      )}

      {/* Input Box */}
      <Box borderStyle="single" borderColor="cyan" paddingX={1}>
        <Text color="cyan">▸ </Text>
        <Text>
          {input.slice(0, cursorPosition)}
          <Text backgroundColor="cyan" color="black">
            {input[cursorPosition] || ' '}
          </Text>
          {input.slice(cursorPosition + 1)}
        </Text>
      </Box>

      {/* Help Text */}
      <Box paddingX={1}>
        <Text dimColor>
          {currentChannel} | @mention agents | /command | Enter: Send • Shift+Enter: New line
        </Text>
      </Box>
    </Box>
  );
}
