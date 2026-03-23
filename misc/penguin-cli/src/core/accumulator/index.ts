/**
 * Accumulator Module - Stream-based transcript management
 *
 * Re-exports all public APIs for clean imports:
 * import { createBuffers, onChunk, toLines } from '../core/accumulator';
 */

// Types
export type {
  Line,
  WelcomeLine,
  UserLine,
  AssistantLine,
  ReasoningLine,
  ToolCallLine,
  ErrorLine,
  StatusLine,
  SeparatorLine,
  ToolPhase,
  ContentPhase,
  Buffers,
  UsageStats,
  PenguinStreamEvent,
  PenguinStreamEventType,
  DrainResult,
  StaticItem,
} from './types.js';

// Type guards
export {
  isUserLine,
  isAssistantLine,
  isToolCallLine,
  isReasoningLine,
  isFinished,
} from './types.js';

// Accumulator functions
export {
  createBuffers,
  resetBuffers,
  onChunk,
  toLines,
  getFinishedLines,
  getInProgressLines,
  addUserMessage,
  addError,
  addStatus,
  addWelcome,
  markToolRunning,
  markIncompleteToolsAsCancelled,
  hasInProgressTools,
} from './accumulator.js';

// Stream functions
export {
  drainStream,
  createThrottledRefresh,
  parseWebSocketMessage,
  createWebSocketStream,
} from './stream.js';
