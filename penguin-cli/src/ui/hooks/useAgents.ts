import { useState, useEffect, useCallback, useRef } from 'react';
import { AgentAPI, AgentProfile, AgentSpawnRequest } from '../../core/api/AgentAPI';

export interface UseAgentsOptions {
  pollInterval?: number; // milliseconds, default 3000 (3s)
  autoRefresh?: boolean;  // default true
}

export function useAgents(options: UseAgentsOptions = {}) {
  const { pollInterval = 3000, autoRefresh = true } = options;

  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const apiRef = useRef<AgentAPI>(new AgentAPI());
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Fetch agent roster
  const fetchAgents = useCallback(async () => {
    try {
      const roster = await apiRef.current.listAgents();
      setAgents(roster);
      setError(null);
      return roster;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to fetch agents');
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  // Spawn new agent
  const spawnAgent = useCallback(async (request: AgentSpawnRequest) => {
    try {
      const result = await apiRef.current.spawnAgent(request);
      await fetchAgents(); // Refresh roster
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to spawn agent');
      setError(error);
      throw error;
    }
  }, [fetchAgents]);

  // Delete agent
  const deleteAgent = useCallback(async (agentId: string, preserveConversation: boolean = true) => {
    try {
      const result = await apiRef.current.deleteAgent(agentId, preserveConversation);
      await fetchAgents(); // Refresh roster
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to delete agent');
      setError(error);
      throw error;
    }
  }, [fetchAgents]);

  // Pause agent
  const pauseAgent = useCallback(async (agentId: string) => {
    try {
      await apiRef.current.pauseAgent(agentId);
      await fetchAgents(); // Refresh roster
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to pause agent');
      setError(error);
      throw error;
    }
  }, [fetchAgents]);

  // Resume agent
  const resumeAgent = useCallback(async (agentId: string) => {
    try {
      await apiRef.current.resumeAgent(agentId);
      await fetchAgents(); // Refresh roster
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to resume agent');
      setError(error);
      throw error;
    }
  }, [fetchAgents]);

  // Get single agent profile
  const getAgent = useCallback(async (agentId: string): Promise<AgentProfile | undefined> => {
    return agents.find(a => a.id === agentId);
  }, [agents]);

  // Get active agents
  const getActiveAgents = useCallback((): AgentProfile[] => {
    return agents.filter(a => a.active);
  }, [agents]);

  // Get sub-agents of a parent
  const getSubAgents = useCallback((parentId: string): AgentProfile[] => {
    return agents.filter(a => a.parent === parentId);
  }, [agents]);

  // Initial fetch
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Polling for updates
  useEffect(() => {
    if (!autoRefresh) {
      return;
    }

    pollTimerRef.current = setInterval(() => {
      fetchAgents();
    }, pollInterval);

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, [autoRefresh, pollInterval, fetchAgents]);

  return {
    agents,
    loading,
    error,
    refresh: fetchAgents,
    spawnAgent,
    deleteAgent,
    pauseAgent,
    resumeAgent,
    getAgent,
    getActiveAgents,
    getSubAgents,
  };
}
