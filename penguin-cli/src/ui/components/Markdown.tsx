/**
 * Markdown renderer for Ink
 * Renders markdown content with syntax highlighting in terminal
 */

import React from 'react';
import { Text } from 'ink';
// import InkMarkdown from 'ink-markdown';

interface MarkdownProps {
  content: string;
}

export function Markdown({ content }: MarkdownProps) {
  if (!content || content.trim() === '') {
    return null;
  }

  // Temporarily disabled due to ink-markdown ESM issues
  // TODO: Re-enable when ink-markdown fixes ESM compatibility
  return <Text>{content}</Text>;
  // return <InkMarkdown>{content}</InkMarkdown>;
}
