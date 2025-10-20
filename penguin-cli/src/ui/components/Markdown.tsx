/**
 * Markdown renderer for Ink
 * Renders markdown content with basic formatting in terminal
 *
 * Supports:
 * - Headers (##)
 * - Bold (**text**)
 * - Italic (*text*)
 * - Code blocks (```)
 * - Inline code (`code`)
 * - Lists (- item)
 */

import React from 'react';
import { Box, Text } from 'ink';

interface MarkdownProps {
  content: string;
}

interface MarkdownLine {
  type: 'header' | 'list' | 'code' | 'text' | 'empty' | 'table';
  level?: number;
  content: string;
  raw: string;
  tableData?: {
    headers: string[];
    rows: string[][];
    alignments?: ('left' | 'center' | 'right')[];
  };
}

function parseMarkdown(content: string): MarkdownLine[] {
  const lines = content.split('\n');
  const parsed: MarkdownLine[] = [];
  let inCodeBlock = false;
  let codeBlockContent: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Handle code blocks
    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        parsed.push({
          type: 'code',
          content: codeBlockContent.join('\n'),
          raw: line,
        });
        codeBlockContent = [];
        inCodeBlock = false;
      } else {
        // Start code block (skip the language identifier line like ```python)
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockContent.push(line);
      continue;
    }

    // Empty line
    if (line.trim() === '') {
      parsed.push({ type: 'empty', content: '', raw: line });
      continue;
    }

    // Headers
    const headerMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headerMatch) {
      parsed.push({
        type: 'header',
        level: headerMatch[1].length,
        content: headerMatch[2],
        raw: line,
      });
      continue;
    }

    // Tables (detect by | character)
    if (line.trim().includes('|')) {
      // Check if next line is separator (|---|---|)
      if (i + 1 < lines.length && lines[i + 1].trim().match(/^\|?[\s-:|]+\|/)) {
        const headerLine = line;
        const separatorLine = lines[i + 1];
        const headers = headerLine.split('|').map(h => h.trim()).filter(h => h);

        // Parse alignment from separator
        const alignments = separatorLine.split('|').map(s => s.trim()).filter(s => s).map(s => {
          if (s.startsWith(':') && s.endsWith(':')) return 'center';
          if (s.endsWith(':')) return 'right';
          return 'left';
        });

        // Collect table rows
        const rows: string[][] = [];
        let j = i + 2;
        while (j < lines.length && lines[j].trim().includes('|')) {
          const row = lines[j].split('|').map(c => c.trim()).filter(c => c);
          if (row.length > 0) {
            rows.push(row);
          }
          j++;
        }

        parsed.push({
          type: 'table',
          content: '',
          raw: line,
          tableData: { headers, rows, alignments },
        });

        // Skip processed lines
        i = j - 1;
        continue;
      }
    }

    // List items
    if (line.trim().startsWith('-') || line.trim().startsWith('*')) {
      const content = line.trim().substring(1).trim();
      parsed.push({
        type: 'list',
        content,
        raw: line,
      });
      continue;
    }

    // Regular text
    parsed.push({
      type: 'text',
      content: line,
      raw: line,
    });
  }

  return parsed;
}

function formatInlineMarkdown(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  // Process inline code first (`code`)
  const codeRegex = /`([^`]+)`/g;
  let codeMatch;
  let lastIndex = 0;

  while ((codeMatch = codeRegex.exec(text)) !== null) {
    // Add text before code
    if (codeMatch.index > lastIndex) {
      const beforeText = text.substring(lastIndex, codeMatch.index);
      // Process bold in the text before code
      parts.push(...processBold(beforeText, key));
      key += 100; // Offset for next batch
    }
    // Add inline code
    parts.push(
      <Text key={`code-${key++}`} backgroundColor="gray" color="green">
        {' '}{codeMatch[1]}{' '}
      </Text>
    );
    lastIndex = codeMatch.index + codeMatch[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    const remainingText = text.substring(lastIndex);
    parts.push(...processBold(remainingText, key));
  }

  // If no formatting, return plain text
  if (parts.length === 0) {
    return [text];
  }

  return parts;
}

function processBold(text: string, startKey: number): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const boldRegex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match;
  let key = startKey;

  while ((match = boldRegex.exec(text)) !== null) {
    // Add text before bold
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    // Add bold text
    parts.push(<Text key={`bold-${key++}`} bold>{match[1]}</Text>);
    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  // If no formatting, return plain text
  if (parts.length === 0) {
    return [text];
  }

  return parts;
}

export function Markdown({ content }: MarkdownProps) {
  if (!content || content.trim() === '') {
    return null;
  }

  const lines = parseMarkdown(content);

  return (
    <Box flexDirection="column">
      {lines.map((line, index) => {
        switch (line.type) {
          case 'header':
            return (
              <Box key={index} marginY={line.level === 1 || line.level === 2 ? 1 : 0}>
                <Text bold color={line.level === 1 ? 'cyan' : line.level === 2 ? 'blue' : 'white'}>
                  {formatInlineMarkdown(line.content)}
                </Text>
              </Box>
            );

          case 'list':
            return (
              <Box key={index} marginLeft={2}>
                <Text color="gray">• </Text>
                <Text>{formatInlineMarkdown(line.content)}</Text>
              </Box>
            );

          case 'code':
            return (
              <Box key={index} marginY={1} paddingX={2} borderStyle="round" borderColor="gray">
                <Text color="green">{line.content}</Text>
              </Box>
            );

          case 'table':
            if (!line.tableData) return null;
            const { headers, rows } = line.tableData;
            return (
              <Box key={index} flexDirection="column" marginY={1} borderStyle="single" borderColor="cyan">
                {/* Table headers */}
                <Box borderStyle="single" borderColor="cyan">
                  {headers.map((header, hi) => (
                    <Box key={hi} width={20} paddingX={1}>
                      <Text bold color="cyan">{header}</Text>
                    </Box>
                  ))}
                </Box>
                {/* Table rows */}
                {rows.map((row, ri) => (
                  <Box key={ri}>
                    {row.map((cell, ci) => (
                      <Box key={ci} width={20} paddingX={1}>
                        <Text>{cell}</Text>
                      </Box>
                    ))}
                  </Box>
                ))}
              </Box>
            );

          case 'empty':
            return <Text key={index}>{'\n'}</Text>;

          case 'text':
          default:
            return <Text key={index}>{formatInlineMarkdown(line.content)}</Text>;
        }
      })}
    </Box>
  );
}
