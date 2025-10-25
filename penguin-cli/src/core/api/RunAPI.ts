/**
 * RunMode API Client
 *
 * Makes HTTP REST API calls to manage autonomous task execution
 */

export interface RunModeStatus {
  status: 'idle' | 'running' | 'stopped';
  current_task?: string;
  task_id?: string;
  start_time?: string;
}

export interface TaskExecuteResponse {
  status: string;
  response?: string;
  iterations?: number;
  execution_time?: number;
  action_results?: any[];
  task_metadata?: any;
}

export interface TaskStreamMessage {
  type: 'task_started' | 'task_progress' | 'task_completed' | 'task_completed_eventbus' | 'task_failed' | 'message' | 'error' | 'token' | 'reasoning' | 'shutdown_completed' | 'run_mode_ended';
  task_id?: string;
  task_name?: string;
  content?: string;
  token?: string;
  progress?: number;
  iteration?: number;
  max_iterations?: number;
  result?: any;
  error?: string;
}

export class RunAPI {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
  }

  /**
   * Start continuous autonomous execution mode via WebSocket streaming
   * Note: This method just validates parameters. Actual WebSocket connection
   * should be established using connectStreamAndExecute()
   */
  async startContinuous(taskName?: string, description?: string): Promise<{ status: string }> {
    // Just return success - the actual execution happens via WebSocket
    return { status: 'started' };
  }

  /**
   * Run a specific task (synchronous execution with Engine)
   */
  async runTask(name: string, description?: string, context?: Record<string, any>): Promise<TaskExecuteResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/tasks/execute-sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name,
        description,
        continuous: false,
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to run task: ${response.statusText}`);
    }

    return (await response.json()) as TaskExecuteResponse;
  }

  /**
   * Stop current execution (note: backend doesn't have dedicated stop endpoint yet)
   */
  async stop(): Promise<{ status: string }> {
    // For now, return success - backend RunMode handles stop via shutdown signal
    return { status: 'stopped' };
  }

  /**
   * Connect to task stream WebSocket and send task request for real-time execution
   */
  connectStreamAndExecute(
    taskName: string,
    description: string | undefined,
    continuous: boolean,
    conversationId: string | undefined,
    onMessage: (message: TaskStreamMessage) => void,
    onError?: (error: Error) => void,
    onClose?: () => void
  ): WebSocket {
    const wsUrl = this.baseUrl.replace(/^http/, 'ws') + '/api/v1/tasks/stream';
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      // Send task request once connected with conversation ID
      ws.send(JSON.stringify({
        name: taskName,
        description: description,
        continuous: continuous,
        conversation_id: conversationId,
      }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Backend sends: {event: string, data: {...}}
        const message: TaskStreamMessage = {
          type: data.event as any,
          ...data.data,
        };
        onMessage(message);
      } catch (error) {
        onError?.(new Error(`Failed to parse stream message: ${error}`));
      }
    };

    ws.onerror = (event) => {
      onError?.(new Error('WebSocket error'));
    };

    ws.onclose = () => {
      onClose?.();
    };

    return ws;
  }
}
