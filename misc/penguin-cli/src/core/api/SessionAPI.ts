/**
 * Session API Client
 *
 * Makes HTTP REST API calls to manage conversations/sessions
 */

import type { Session } from '../types.js';

export interface SessionListResponse {
  conversations: Session[];
}

export interface SessionCreateResponse {
  conversation_id: string;
}

export interface SessionDeleteResponse {
  status: string;
  conversation_id: string;
}

export class SessionAPI {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
  }

  /**
   * List all available conversations/sessions
   */
  async listSessions(): Promise<Session[]> {
    const response = await fetch(`${this.baseUrl}/api/v1/conversations`);
    if (!response.ok) {
      throw new Error(`Failed to list sessions: ${response.statusText}`);
    }
    const data = (await response.json()) as SessionListResponse;
    return data.conversations;
  }

  /**
   * Get a specific conversation/session by ID
   */
  async getSession(sessionId: string): Promise<Session> {
    const response = await fetch(`${this.baseUrl}/api/v1/conversations/${sessionId}`);
    if (!response.ok) {
      throw new Error(`Failed to get session ${sessionId}: ${response.statusText}`);
    }
    return (await response.json()) as Session;
  }

  /**
   * Create a new conversation/session
   */
  async createSession(): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/v1/conversations/create`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to create session: ${response.statusText}`);
    }
    const data = (await response.json()) as SessionCreateResponse;
    return data.conversation_id;
  }

  /**
   * Delete a conversation/session by ID
   */
  async deleteSession(sessionId: string): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/api/v1/conversations/${sessionId}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      if (response.status === 404) {
        return false;
      }
      throw new Error(`Failed to delete session ${sessionId}: ${response.statusText}`);
    }
    return true;
  }
}
