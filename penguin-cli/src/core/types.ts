/**
 * Shared types for Penguin CLI
 * Used across core services and UI components
 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  toolCalls?: ToolCall[];
  reasoning?: string; // Internal reasoning from the model (if available)
}

export interface ToolCall {
  id: string;
  action: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  result?: string;
  error?: string;
  startTime?: number;
  endTime?: number;
}

export interface StreamEvent {
  event: 'start' | 'token' | 'reasoning' | 'progress' | 'complete' | 'error';
  data: any;
}

export interface ActionResult {
  action: string;
  result: string;
  status: 'completed' | 'error' | 'interrupted';
  timestamp?: number;
}

// Normalized tool events for UI timeline and state machines
export type ToolEventPhase = 'start' | 'update' | 'end';

export interface ToolEventNormalized {
  id: string; // stable id for a tool invocation
  phase: ToolEventPhase;
  action: string;
  ts: number;
  status?: 'running' | 'completed' | 'error';
  result?: string; // final result or error text
}

// Event timeline types
export type TimelineEventKind = 'message' | 'stream' | 'tool' | 'progress' | 'system';

export interface BaseEvent {
  id: string;
  kind: TimelineEventKind;
  ts: number;
}

export interface MessageEvent extends BaseEvent {
  kind: 'message';
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoning?: string;
}

export interface StreamEventEntry extends BaseEvent {
  kind: 'stream';
  role: 'assistant';
  text: string;
}

export interface ProgressEventEntry extends BaseEvent {
  kind: 'progress';
  iteration: number;
  max: number;
  message?: string;
}

export interface ToolEventEntry extends BaseEvent, ToolEventNormalized {
  kind: 'tool';
}

export type TimelineEvent =
  | MessageEvent
  | StreamEventEntry
  | ToolEventEntry
  | ProgressEventEntry;

export interface Session {
  id: string;
  conversationId?: string;
  agentId?: string;
  createdAt: number;
  updatedAt: number;
  title?: string;
  message_count?: number;
  last_active?: string;
}

export interface ChatConfig {
  apiUrl: string;
  conversationId?: string;
  agentId?: string;
}

export interface StreamConfig {
  batchSize: number;      // Number of tokens to batch (default: 50)
  batchDelay: number;     // Delay in ms before flushing (default: 50)
}

export interface ConnectionState {
  isConnected: boolean;
  isConnecting: boolean;
  error: Error | null;
  reconnectAttempts: number;
}
