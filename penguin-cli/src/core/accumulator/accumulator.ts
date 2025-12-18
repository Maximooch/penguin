/**
 * Accumulator - Stream-based transcript management
 *
 * Core pattern from letta-code: maintains dual-structure (order[] + Map)
 * for efficient rendering with in-place updates for streaming content.
 */

import type {
  Buffers,
  Line,
  WelcomeLine,
  UserLine,
  AssistantLine,
  ReasoningLine,
  ToolCallLine,
  ErrorLine,
  StatusLine,
  PenguinStreamEvent,
  UsageStats,
} from './types.js';

/**
 * Generate a unique ID for a line
 */
function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Strip action tags from content that should be consumed by backend
 * These are control tags that shouldn't be displayed to users
 */
const ACTION_TAG_PATTERN = /<\/?(?:finish_response|finish_task|emergency_stop)[^>]*>/gi;

function stripActionTags(content: string): string {
  return content.replace(ACTION_TAG_PATTERN, '');
}

/**
 * Create empty buffers for a new transcript
 */
export function createBuffers(): Buffers {
  return {
    tokenCount: 0,
    order: [],
    byId: new Map(),
    toolCallIdToLineId: new Map(),
    lastMessageId: null,
    pendingRefresh: false,
    usage: {
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      reasoningTokens: 0,
    },
  };
}

/**
 * Reset buffers to empty state (preserves object reference)
 */
export function resetBuffers(b: Buffers): void {
  b.tokenCount = 0;
  b.order = [];
  b.byId.clear();
  b.toolCallIdToLineId.clear();
  b.lastMessageId = null;
  b.pendingRefresh = false;
  b.usage = {
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    reasoningTokens: 0,
  };
}

/**
 * Ensure a line exists in buffers, creating if needed
 * Returns the existing or newly created line
 */
function ensure<T extends Line>(b: Buffers, id: string, make: () => T): T {
  const existing = b.byId.get(id) as T | undefined;
  if (existing) return existing;

  const created = make();
  b.byId.set(id, created);
  b.order.push(id);
  return created;
}

/**
 * Update a line immutably
 */
function updateLine<T extends Line>(b: Buffers, id: string, updates: Partial<T>): void {
  const line = b.byId.get(id);
  if (line) {
    b.byId.set(id, { ...line, ...updates } as Line);
  }
}

/**
 * Mark a line as finished (for lines with phase)
 */
function markAsFinished(b: Buffers, id: string): void {
  const line = b.byId.get(id);
  if (line && 'phase' in line && line.phase !== 'finished') {
    updateLine(b, id, { phase: 'finished' });
  }
}

/**
 * Handle transition when a new message ID appears
 * Marks previous streaming content as finished
 */
function handleMessageTransition(b: Buffers, newId: string | undefined): void {
  if (b.lastMessageId && b.lastMessageId !== newId) {
    const prev = b.byId.get(b.lastMessageId);
    if (prev && (prev.kind === 'assistant' || prev.kind === 'reasoning')) {
      markAsFinished(b, b.lastMessageId);
    }
  }
  if (newId) {
    b.lastMessageId = newId;
  }
}

/**
 * Add a user message to the transcript
 */
export function addUserMessage(b: Buffers, text: string): string {
  const id = uid('user');
  const line: UserLine = { kind: 'user', id, text };
  b.byId.set(id, line);
  b.order.push(id);
  return id;
}

/**
 * Add an error to the transcript
 */
export function addError(b: Buffers, text: string): string {
  const id = uid('error');
  const line: ErrorLine = { kind: 'error', id, text };
  b.byId.set(id, line);
  b.order.push(id);
  return id;
}

/**
 * Add a status message to the transcript
 */
export function addStatus(b: Buffers, lines: string[]): string {
  const id = uid('status');
  const line: StatusLine = { kind: 'status', id, lines };
  b.byId.set(id, line);
  b.order.push(id);
  return id;
}

/**
 * Add a welcome message to the transcript (typically first item)
 */
export function addWelcome(b: Buffers, version: string, workspace?: string): string {
  const id = uid('welcome');
  const line: WelcomeLine = { kind: 'welcome', id, version, workspace };
  b.byId.set(id, line);
  b.order.unshift(id); // Add at beginning
  return id;
}

/**
 * Process a stream event and update buffers accordingly
 * This is the main entry point for handling streaming data
 */
export function onChunk(b: Buffers, event: PenguinStreamEvent): void {
  const { event: eventType, data } = event;

  switch (eventType) {
    case 'start': {
      // Stream starting - could reset or just note
      break;
    }

    case 'token': {
      // Assistant message token
      // Generate unique ID for each response stream, not a fixed ID
      // This prevents issues where committed IDs get skipped in dynamic rendering
      let id: string;
      if (data.id) {
        id = data.id;
      } else {
        // If no ID provided, check if we need a new stream
        // Use lastMessageId if it's still streaming, otherwise create new
        const lastLine = b.lastMessageId ? b.byId.get(b.lastMessageId) : null;
        if (b.lastMessageId && lastLine && lastLine.kind === 'assistant' && 'phase' in lastLine && lastLine.phase === 'streaming') {
          id = b.lastMessageId;
        } else {
          // Create a new unique ID for this response
          id = `assistant-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
        }
      }
      handleMessageTransition(b, id);

      const line = ensure<AssistantLine>(b, id, () => ({
        kind: 'assistant',
        id,
        text: '',
        phase: 'streaming',
      }));

      if (data.content) {
        // Accumulate text then strip action tags (handles tags split across chunks)
        const accumulatedText = line.text + data.content;
        const cleanText = stripActionTags(accumulatedText);
        updateLine<AssistantLine>(b, id, { text: cleanText });
        b.tokenCount += data.content.length;
      }
      break;
    }

    case 'reasoning': {
      // Reasoning/thinking content
      // Generate unique ID for each reasoning stream
      let id: string;
      if (data.id) {
        id = data.id;
      } else {
        // Check if we have an active reasoning stream
        const lastLine = b.lastMessageId ? b.byId.get(b.lastMessageId) : null;
        if (b.lastMessageId && lastLine && lastLine.kind === 'reasoning' && 'phase' in lastLine && lastLine.phase === 'streaming') {
          id = b.lastMessageId;
        } else {
          id = `reasoning-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
        }
      }
      handleMessageTransition(b, id);

      const line = ensure<ReasoningLine>(b, id, () => ({
        kind: 'reasoning',
        id,
        text: '',
        phase: 'streaming',
      }));

      if (data.content) {
        const updatedText = line.text + data.content;
        updateLine<ReasoningLine>(b, id, { text: updatedText });
        b.usage.reasoningTokens += data.content.length;
      }
      break;
    }

    case 'tool_call': {
      // Tool call initiated
      const toolCallId = data.tool_call_id;
      let id = toolCallId ? b.toolCallIdToLineId.get(toolCallId) : undefined;

      if (!id) {
        id = uid('tool');
        if (toolCallId) {
          b.toolCallIdToLineId.set(toolCallId, id);
        }
      }

      handleMessageTransition(b, id);

      const line = ensure<ToolCallLine>(b, id, () => ({
        kind: 'tool_call',
        id,
        toolCallId,
        phase: 'ready',
      }));

      // Update tool call info
      const updates: Partial<ToolCallLine> = {};
      if (data.tool_name) updates.name = data.tool_name;
      if (data.tool_args) {
        updates.argsText = (line.argsText || '') + data.tool_args;
      }
      if (Object.keys(updates).length > 0) {
        updateLine<ToolCallLine>(b, id, updates);
      }
      break;
    }

    case 'tool_result': {
      // Tool result returned
      const toolCallId = data.tool_call_id;
      const id = toolCallId ? b.toolCallIdToLineId.get(toolCallId) : undefined;

      if (id) {
        updateLine<ToolCallLine>(b, id, {
          resultText: data.result,
          resultOk: data.status === 'success',
          phase: 'finished',
        });
      }
      break;
    }

    case 'progress': {
      // Progress update - could add as status or handle separately
      if (data.message) {
        addStatus(b, [`Step ${data.iteration}/${data.max_iterations}: ${data.message}`]);
      }
      break;
    }

    case 'complete': {
      // Stream complete - mark everything as finished
      if (b.lastMessageId) {
        markAsFinished(b, b.lastMessageId);
      }

      // Update usage stats if provided
      if (data.usage) {
        Object.assign(b.usage, data.usage);
      }
      break;
    }

    case 'error': {
      // Error occurred
      if (data.error) {
        addError(b, data.error);
      }

      // Mark current line as finished
      if (b.lastMessageId) {
        markAsFinished(b, b.lastMessageId);
      }
      break;
    }
  }
}

/**
 * Convert buffers to ordered array of lines for rendering
 */
export function toLines(b: Buffers): Line[] {
  const out: Line[] = [];
  for (const id of b.order) {
    const line = b.byId.get(id);
    if (line) {
      out.push(line);
    }
  }
  return out;
}

/**
 * Get only finished lines (for static rendering)
 */
export function getFinishedLines(b: Buffers): Line[] {
  const out: Line[] = [];
  for (const id of b.order) {
    const line = b.byId.get(id);
    if (line) {
      const isFinished = !('phase' in line) || line.phase === 'finished';
      if (isFinished) {
        out.push(line);
      }
    }
  }
  return out;
}

/**
 * Get only in-progress lines (for dynamic rendering)
 */
export function getInProgressLines(b: Buffers): Line[] {
  const out: Line[] = [];
  for (const id of b.order) {
    const line = b.byId.get(id);
    if (line && 'phase' in line && line.phase !== 'finished') {
      out.push(line);
    }
  }
  return out;
}

/**
 * Mark a tool call as running (user approved)
 */
export function markToolRunning(b: Buffers, toolCallId: string): void {
  const id = b.toolCallIdToLineId.get(toolCallId);
  if (id) {
    updateLine<ToolCallLine>(b, id, { phase: 'running' });
  }
}

/**
 * Mark incomplete tool calls as cancelled
 */
export function markIncompleteToolsAsCancelled(b: Buffers): void {
  for (const id of b.order) {
    const line = b.byId.get(id);
    if (
      line &&
      line.kind === 'tool_call' &&
      line.phase !== 'finished'
    ) {
      updateLine<ToolCallLine>(b, id, {
        phase: 'finished',
        resultText: 'Cancelled',
        resultOk: false,
      });
    }
  }
}

/**
 * Check if there are any in-progress tool calls
 */
export function hasInProgressTools(b: Buffers): boolean {
  for (const id of b.order) {
    const line = b.byId.get(id);
    if (
      line &&
      line.kind === 'tool_call' &&
      line.phase !== 'finished'
    ) {
      return true;
    }
  }
  return false;
}
