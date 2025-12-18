/**
 * Accumulator Types for Stream Processing
 *
 * Pattern adapted from letta-code: dual-structure (order[] + Map<id, Line>)
 * for efficient transcript management with streaming updates.
 */

/**
 * Tool call lifecycle phases
 * - streaming: Tool call definition still arriving (args incomplete)
 * - ready: Tool call complete, awaiting approval (if approval required)
 * - running: Tool call approved and executing
 * - finished: Tool call completed (success or error)
 */
export type ToolPhase = 'streaming' | 'ready' | 'running' | 'finished';

/**
 * Message streaming phase
 * - streaming: Content still arriving
 * - finished: Content complete
 */
export type ContentPhase = 'streaming' | 'finished';

/**
 * Line types for transcript display
 * Each line represents a distinct UI element in the conversation
 */
export type Line =
  | WelcomeLine
  | UserLine
  | AssistantLine
  | ReasoningLine
  | ToolCallLine
  | ErrorLine
  | StatusLine
  | SeparatorLine;

/**
 * Welcome/banner line - shown once at session start
 */
export interface WelcomeLine {
  kind: 'welcome';
  id: string;
  version: string;
  workspace?: string;
}

export interface UserLine {
  kind: 'user';
  id: string;
  text: string;
}

export interface AssistantLine {
  kind: 'assistant';
  id: string;
  text: string;
  phase: ContentPhase;
}

export interface ReasoningLine {
  kind: 'reasoning';
  id: string;
  text: string;
  phase: ContentPhase;
}

export interface ToolCallLine {
  kind: 'tool_call';
  id: string;
  toolCallId?: string;
  name?: string;
  argsText?: string;
  resultText?: string;
  resultOk?: boolean;
  phase: ToolPhase;
}

export interface ErrorLine {
  kind: 'error';
  id: string;
  text: string;
}

export interface StatusLine {
  kind: 'status';
  id: string;
  lines: string[];
}

export interface SeparatorLine {
  kind: 'separator';
  id: string;
}

/**
 * Token usage tracking
 */
export interface UsageStats {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  reasoningTokens: number;
}

/**
 * Core buffer structure for transcript accumulation
 *
 * Uses dual structure for efficient operations:
 * - order[]: Maintains insertion order for rendering
 * - byId: Map for O(1) lookups and in-place updates
 * - toolCallIdToLineId: Correlates tool returns with tool calls
 */
export interface Buffers {
  /** Approximate token count for display */
  tokenCount: number;

  /** Ordered list of line IDs for rendering */
  order: string[];

  /** Map of line ID to line data */
  byId: Map<string, Line>;

  /** Maps toolCallId to line id for correlating returns */
  toolCallIdToLineId: Map<string, string>;

  /** Last processed message ID for phase transitions */
  lastMessageId: string | null;

  /** Flag to throttle refresh calls */
  pendingRefresh?: boolean;

  /** Token usage statistics */
  usage: UsageStats;
}

/**
 * Penguin stream event types
 * These match the FastAPI backend's streaming response format
 */
export type PenguinStreamEventType =
  | 'start'
  | 'token'
  | 'reasoning'
  | 'tool_call'
  | 'tool_result'
  | 'progress'
  | 'complete'
  | 'error';

export interface PenguinStreamEvent {
  event: PenguinStreamEventType;
  data: {
    /** Message/event ID */
    id?: string;
    /** Token content for streaming */
    content?: string;
    /** Tool call information */
    tool_call_id?: string;
    tool_name?: string;
    tool_args?: string;
    /** Tool result information */
    result?: string;
    status?: 'success' | 'error';
    /** Progress information */
    iteration?: number;
    max_iterations?: number;
    message?: string;
    /** Error information */
    error?: string;
    /** Completion information */
    stop_reason?: string;
    usage?: Partial<UsageStats>;
  };
}

/**
 * Result from draining a stream
 */
export interface DrainResult {
  /** Why the stream ended */
  stopReason: 'complete' | 'error' | 'cancelled' | 'interrupted';
  /** Total API call duration in ms */
  apiDurationMs: number;
  /** Final usage stats */
  usage?: UsageStats;
}

/**
 * Static item types for frozen transcript history
 * These are items that have been committed and will never change
 */
export type StaticItem = Line;

/**
 * Helper type guard functions
 */
export function isUserLine(line: Line): line is UserLine {
  return line.kind === 'user';
}

export function isAssistantLine(line: Line): line is AssistantLine {
  return line.kind === 'assistant';
}

export function isToolCallLine(line: Line): line is ToolCallLine {
  return line.kind === 'tool_call';
}

export function isReasoningLine(line: Line): line is ReasoningLine {
  return line.kind === 'reasoning';
}

export function isFinished(line: Line): boolean {
  if ('phase' in line) {
    return line.phase === 'finished';
  }
  // Lines without phase (user, error, status, separator) are always "finished"
  return true;
}
