import axios, { AxiosInstance } from 'axios';

export interface AgentProfile {
  id: string;
  persona?: string | null;
  persona_description?: string | null;
  persona_defined: boolean;
  model: {
    model: string;
    provider: string;
    client_preference: string;
    max_tokens?: number | null;
    temperature: number;
    streaming_enabled: boolean;
  };
  model_override: boolean;
  parent?: string | null;
  children: string[];
  default_tools: string[];
  active: boolean;
  paused: boolean;
  is_sub_agent: boolean;
  system_prompt_preview?: string;
}

export interface AgentSpawnRequest {
  id: string;
  model_config_id: string; // Required field
  role?: string;
  persona?: string;
  model_overrides?: Record<string, any>;
  activate?: boolean;
  share_session_with?: string;
  share_context_window_with?: string;
  default_tools?: string[];
}

export interface DelegateRequest {
  content: string;
  parent_agent_id?: string;
  summary?: string;
  metadata?: Record<string, any>;
}

export interface ProtocolMessage {
  sender?: string;
  recipient?: string;
  content: any;
  message_type: 'message' | 'action' | 'status' | 'event';
  metadata?: Record<string, any>;
  channel?: string;
  timestamp?: string;
  session_id?: string;
  message_id?: string;
}

export class AgentAPI {
  private client: AxiosInstance;

  constructor(baseURL: string = 'http://localhost:8000') {
    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  // Agent Management
  // ------------------------------------------------------------------

  async listAgents(): Promise<AgentProfile[]> {
    const response = await this.client.get<AgentProfile[]>('/api/v1/agents');
    return response.data;
  }

  async getAgent(agentId: string): Promise<AgentProfile> {
    const response = await this.client.get<AgentProfile>(`/api/v1/agents/${agentId}`);
    return response.data;
  }

  async spawnAgent(request: AgentSpawnRequest): Promise<AgentProfile> {
    const response = await this.client.post<AgentProfile>('/api/v1/agents', request);
    return response.data;
  }

  async deleteAgent(agentId: string, preserveConversation: boolean = true): Promise<{ removed: boolean }> {
    const response = await this.client.delete<{ removed: boolean }>(`/api/v1/agents/${agentId}`, {
      params: { preserve_conversation: preserveConversation },
    });
    return response.data;
  }

  async pauseAgent(agentId: string): Promise<void> {
    await this.client.post(`/api/v1/agents/${agentId}/pause`);
  }

  async resumeAgent(agentId: string): Promise<void> {
    await this.client.post(`/api/v1/agents/${agentId}/resume`);
  }

  // Agent Communication
  // ------------------------------------------------------------------

  async delegateToAgent(agentId: string, request: DelegateRequest): Promise<{ ok: boolean; delegated_to: string; parent: string }> {
    const response = await this.client.post<{ ok: boolean; delegated_to: string; parent: string }>(`/api/v1/agents/${agentId}/delegate`, request);
    return response.data;
  }

  async sendMessageToAgent(
    agentId: string,
    content: string,
    options?: {
      sender?: string;
      message_type?: string;
      channel?: string;
      metadata?: Record<string, any>;
    }
  ): Promise<void> {
    await this.client.post(`/api/v1/messages`, {
      recipient: agentId,
      content,
      sender: options?.sender || 'human',
      message_type: options?.message_type || 'message',
      channel: options?.channel,
      metadata: options?.metadata,
    });
  }

  async humanReplyToAgent(
    agentId: string,
    content: string,
    options?: {
      message_type?: string;
      channel?: string;
      metadata?: Record<string, any>;
    }
  ): Promise<{ ok: boolean }> {
    const response = await this.client.post<{ ok: boolean }>(`/api/v1/messages/human-reply`, {
      agent_id: agentId,
      content,
      message_type: options?.message_type || 'message',
      channel: options?.channel,
      metadata: options?.metadata,
    });
    return response.data;
  }

  // Agent History
  // ------------------------------------------------------------------

  async getAgentHistory(
    agentId: string,
    options?: {
      include_system?: boolean;
      limit?: number;
    }
  ): Promise<any[]> {
    const response = await this.client.get(`/api/v1/agents/${agentId}/history`, {
      params: options,
    });
    return response.data;
  }

  async getAgentSessions(agentId: string): Promise<any[]> {
    const response = await this.client.get(`/api/v1/agents/${agentId}/sessions`);
    return response.data;
  }

  // WebSocket Connection
  // ------------------------------------------------------------------

  connectMessageBus(
    onMessage: (message: ProtocolMessage) => void,
    options?: {
      agentId?: string;
      channel?: string;
      messageType?: string;
      includeBus?: boolean;
      includeUI?: boolean;
    },
    onError?: (error: Error) => void,
    onClose?: () => void
  ): WebSocket {
    const params = new URLSearchParams();
    if (options?.agentId) params.append('agent_id', options.agentId);
    if (options?.channel) params.append('channel', options.channel);
    if (options?.messageType) params.append('message_type', options.messageType);
    if (options?.includeBus !== undefined) params.append('include_bus', String(options.includeBus));
    if (options?.includeUI !== undefined) params.append('include_ui', String(options.includeUI));

    const wsUrl = `ws://localhost:8000/api/v1/ws/messages?${params.toString()}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('[AgentAPI] WebSocket message received:', data);
        if (data.event === 'bus.message' && data.data) {
          console.log('[AgentAPI] Processing bus.message:', data.data);
          onMessage(data.data as ProtocolMessage);
        } else {
          console.log('[AgentAPI] Ignoring message with event:', data.event);
        }
      } catch (err) {
        console.error('[AgentAPI] Failed to parse WebSocket message:', err);
      }
    };

    ws.onerror = (event) => {
      if (onError) {
        onError(new Error('WebSocket error'));
      }
    };

    ws.onclose = () => {
      if (onClose) {
        onClose();
      }
    };

    return ws;
  }
}
