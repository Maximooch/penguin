/**
 * Task List Component
 * Displays a formatted list of tasks with priority and status
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Task } from '../../core/api/ProjectAPI.js';

interface TaskListProps {
  tasks: Task[];
  showProject?: boolean;
  onSelect?: (task: Task) => void;
}

export function TaskList({ tasks, showProject = true, onSelect }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <Box flexDirection="column" paddingX={2} paddingY={1}>
        <Text dimColor>No tasks found.</Text>
        <Text dimColor>Create one with: <Text color="cyan">/task create &lt;name&gt;</Text></Text>
      </Box>
    );
  }

  const getPriorityColor = (priority?: number) => {
    if (!priority) return 'gray';
    if (priority >= 3) return 'red';
    if (priority === 2) return 'yellow';
    return 'green';
  };

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return '✓';
      case 'active':
        return '●';
      case 'pending':
        return '○';
      case 'blocked':
        return '✗';
      default:
        return '•';
    }
  };

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">✓ Tasks ({tasks.length})</Text>
      </Box>

      {tasks.map((task, index) => (
        <Box key={task.id} flexDirection="column" marginBottom={1}>
          <Box>
            <Text color={getPriorityColor(task.priority)}>
              {getStatusIcon(task.status)}{' '}
            </Text>
            <Text bold>{task.title}</Text>
            <Text dimColor> ({task.id.slice(0, 8)})</Text>
          </Box>

          {task.description && (
            <Box paddingLeft={2}>
              <Text dimColor>{task.description}</Text>
            </Box>
          )}

          <Box paddingLeft={2} gap={1}>
            <Text dimColor>Priority: </Text>
            <Text color={getPriorityColor(task.priority)}>
              {task.priority || 1}
            </Text>

            {showProject && (
              <>
                <Text dimColor> • Project: </Text>
                <Text>{task.project_id.slice(0, 8)}</Text>
              </>
            )}

            <Text dimColor> • Status: </Text>
            <Text color={task.status === 'active' ? 'green' : 'yellow'}>
              {task.status}
            </Text>
          </Box>

          {index < tasks.length - 1 && (
            <Box paddingY={0}>
              <Text dimColor>─────────────────────────────────</Text>
            </Box>
          )}
        </Box>
      ))}
    </Box>
  );
}
