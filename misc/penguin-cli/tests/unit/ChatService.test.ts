/**
 * ChatService Tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { ChatService } from '../../src/core/chat/ChatService';

describe('ChatService', () => {
  let service: ChatService;

  beforeEach(() => {
    service = new ChatService({
      apiUrl: 'ws://test',
      conversationId: 'test-123',
    });
  });

  it('adds user messages to history', () => {
    const message = service.addUserMessage('Hello');

    expect(message.role).toBe('user');
    expect(message.content).toBe('Hello');
    expect(service.getMessages()).toHaveLength(1);
  });

  it('clears history', () => {
    service.addUserMessage('Test');
    service.clearHistory();

    expect(service.getMessages()).toHaveLength(0);
  });
});
