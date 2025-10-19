/**
 * Chat service - manages conversation state
 * Handles message history and user/assistant interactions
 */

import type { Message, ChatConfig } from '../types';

export class ChatService {
  private config: ChatConfig;
  private messageHistory: Message[] = [];

  constructor(config: ChatConfig) {
    this.config = config;
  }

  /**
   * Add a user message to history
   */
  addUserMessage(text: string): Message {
    const message: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    this.messageHistory.push(message);
    return message;
  }

  /**
   * Add an assistant message to history
   */
  addAssistantMessage(content: string): Message {
    const message: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
    };
    this.messageHistory.push(message);
    return message;
  }

  /**
   * Get all messages
   */
  getMessages(): Message[] {
    return [...this.messageHistory];
  }

  /**
   * Get recent messages (for pagination)
   */
  getRecentMessages(count: number): Message[] {
    return this.messageHistory.slice(-count);
  }

  /**
   * Clear message history
   */
  clearHistory(): void {
    this.messageHistory = [];
  }

  /**
   * Get conversation ID from config
   */
  getConversationId(): string | undefined {
    return this.config.conversationId;
  }

  /**
   * Get agent ID from config
   */
  getAgentId(): string | undefined {
    return this.config.agentId;
  }

  /**
   * Update config
   */
  updateConfig(config: Partial<ChatConfig>): void {
    this.config = { ...this.config, ...config };
  }
}
