import React from 'react';
import { Box, Text } from 'ink';
import { AgentProfile } from '../../core/api/AgentAPI';

export interface AgentRosterProps {
  agents: AgentProfile[];
  selectedAgentId?: string;
  onSelect?: (agentId: string) => void;
  maxHeight?: number;
}

export function AgentRoster({ agents, selectedAgentId, onSelect, maxHeight = 10 }: AgentRosterProps) {
  const renderStatusIndicator = (agent: AgentProfile): string => {
    if (agent.paused) {
      return '⏸'; // Paused
    }
    if (agent.active) {
      return '●'; // Active (solid dot)
    }
    return '○'; // Idle (hollow dot)
  };

  const renderRole = (agent: AgentProfile): string => {
    if (agent.parent) {
      return 'Parent';
    }
    if (agent.is_sub_agent) {
      return 'Sub-agent';
    }
    return 'Agent';
  };

  // Sort agents: parents first, then children
  const sortedAgents = [...agents].sort((a, b) => {
    const aIsParent = a.children.length > 0;
    const bIsParent = b.children.length > 0;
    if (aIsParent && !bIsParent) return -1;
    if (!aIsParent && bIsParent) return 1;
    if (a.parent && !b.parent) return 1;
    if (!a.parent && b.parent) return -1;
    return a.id.localeCompare(b.id);
  });

  // Limit displayed agents if maxHeight specified
  const displayedAgents = maxHeight ? sortedAgents.slice(0, maxHeight) : sortedAgents;
  const hasMore = sortedAgents.length > displayedAgents.length;

  return (
    <Box flexDirection="column" width={18}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          AGENTS ({agents.length})
        </Text>
      </Box>

      {displayedAgents.length === 0 ? (
        <Box>
          <Text dimColor>No agents</Text>
        </Box>
      ) : (
        <Box flexDirection="column">
          {displayedAgents.map((agent) => {
            const isSelected = agent.id === selectedAgentId;
            const isIndented = agent.is_sub_agent && agent.parent;

            return (
              <Box key={agent.id} marginBottom={0}>
                <Text
                  color={
                    isSelected ? 'cyan' : agent.active ? 'green' : agent.paused ? 'yellow' : 'white'
                  }
                  bold={isSelected}
                  dimColor={!agent.active && !isSelected}
                >
                  {isIndented ? '  ' : ''}
                  {renderStatusIndicator(agent)} {agent.id}
                </Text>
              </Box>
            );
          })}

          {hasMore && (
            <Box marginTop={1}>
              <Text dimColor>
                +{sortedAgents.length - displayedAgents.length} more
              </Text>
            </Box>
          )}
        </Box>
      )}

      {agents.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text dimColor>
            ● Active  ○ Idle  ⏸ Paused
          </Text>
        </Box>
      )}
    </Box>
  );
}
