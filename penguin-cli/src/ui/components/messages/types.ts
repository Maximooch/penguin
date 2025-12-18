/**
 * Shared types for message components
 */

import type {
  UserLine,
  AssistantLine,
  ReasoningLine,
  ToolCallLine,
  ErrorLine,
  StatusLine,
  SeparatorLine,
  ToolPhase,
} from '../../../core/accumulator/types.js';

// Re-export line types for convenience
export type {
  UserLine,
  AssistantLine,
  ReasoningLine,
  ToolCallLine,
  ErrorLine,
  StatusLine,
  SeparatorLine,
  ToolPhase,
};

/**
 * Layout constant for content width calculation
 * Used by ChatMessageArea to compute available width
 */
export const GUTTER_WIDTH = 2;
