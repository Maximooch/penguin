/**
 * WebSocket client for connecting to Penguin FastAPI backend
 * Handles streaming chat messages and token batching
 */

import WebSocket from 'ws';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
}

export interface StreamEvent {
  event: 'token' | 'tool_start' | 'tool_end' | 'complete' | 'error';
  data: any;
}

export interface ChatClientOptions {
  url?: string;
  conversationId?: string;
  agentId?: string;
  onToken?: (token: string) => void;
  onToolStart?: (tool: string, args: any) => void;
  onToolEnd?: (tool: string, result: any) => void;
  onComplete?: () => void;
  onError?: (error: Error) => void;
  onConnect?: () => void;
  onDisconnect?: (code: number, reason: string) => void;
}

export class ChatClient {
  private ws: WebSocket | null = null;
  private url: string;
  private conversationId?: string;
  private agentId?: string;
  private callbacks: Required<Omit<ChatClientOptions, 'url' | 'conversationId' | 'agentId'>>;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  constructor(options: ChatClientOptions = {}) {
    this.url = options.url || 'ws://localhost:8000/api/v1/chat/stream';
    this.conversationId = options.conversationId;
    this.agentId = options.agentId;

    // Set up callbacks with no-op defaults
    this.callbacks = {
      onToken: options.onToken || (() => {}),
      onToolStart: options.onToolStart || (() => {}),
      onToolEnd: options.onToolEnd || (() => {}),
      onComplete: options.onComplete || (() => {}),
      onError: options.onError || (() => {}),
      onConnect: options.onConnect || (() => {}),
      onDisconnect: options.onDisconnect || (() => {}),
    };
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url);

        this.ws.on('open', () => {
          this.reconnectAttempts = 0;
          this.callbacks.onConnect();
          resolve();
        });

        this.ws.on('message', (data: WebSocket.Data) => {
          this.handleMessage(data);
        });

        this.ws.on('close', (code: number, reason: Buffer) => {
          const reasonStr = reason.toString();
          this.callbacks.onDisconnect(code, reasonStr);

          // Auto-reconnect on abnormal closure
          if (code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnect();
          }
        });

        this.ws.on('error', (error: Error) => {
          this.callbacks.onError(error);
          reject(error);
        });
      } catch (error) {
        reject(error);
      }
    });
  }

  private handleMessage(data: WebSocket.Data): void {
    try {
      const message = JSON.parse(data.toString());
      const { event, data: eventData } = message as StreamEvent;

      switch (event) {
        case 'token':
          if (eventData.token) {
            this.callbacks.onToken(eventData.token);
          }
          break;

        case 'tool_start':
          this.callbacks.onToolStart(eventData.tool, eventData.args);
          break;

        case 'tool_end':
          this.callbacks.onToolEnd(eventData.tool, eventData.result);
          break;

        case 'complete':
          this.callbacks.onComplete();
          break;

        case 'error':
          this.callbacks.onError(new Error(eventData.message || 'Unknown error'));
          break;
      }
    } catch (error) {
      this.callbacks.onError(error as Error);
    }
  }

  sendMessage(text: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected');
    }

    const payload = {
      text,
      conversation_id: this.conversationId,
      agent_id: this.agentId,
    };

    this.ws.send(JSON.stringify(payload));
  }

  private reconnect(): void {
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);

    setTimeout(() => {
      this.connect().catch(() => {
        // Reconnect will be attempted again if needed
      });
    }, delay);
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}
