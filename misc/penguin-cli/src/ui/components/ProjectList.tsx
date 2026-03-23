/**
 * Project List Component
 * Displays a formatted list of projects with status indicators
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Project } from '../../core/api/ProjectAPI.js';

interface ProjectListProps {
  projects: Project[];
  onSelect?: (project: Project) => void;
}

export function ProjectList({ projects, onSelect }: ProjectListProps) {
  if (projects.length === 0) {
    return (
      <Box flexDirection="column" paddingX={2} paddingY={1}>
        <Text dimColor>No projects found.</Text>
        <Text dimColor>Create one with: <Text color="cyan">/project create &lt;name&gt;</Text></Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">📋 Projects ({projects.length})</Text>
      </Box>

      {projects.map((project, index) => (
        <Box key={project.id} flexDirection="column" marginBottom={1}>
          <Box>
            <Text color="yellow">▸ </Text>
            <Text bold>{project.name}</Text>
            <Text dimColor> ({project.id.slice(0, 8)})</Text>
          </Box>

          {project.description && (
            <Box paddingLeft={2}>
              <Text dimColor>{project.description}</Text>
            </Box>
          )}

          <Box paddingLeft={2}>
            <Text dimColor>Status: </Text>
            <Text color={project.status === 'active' ? 'green' : 'yellow'}>
              {project.status}
            </Text>
            <Text dimColor> • Created: {new Date(project.created_at).toLocaleDateString()}</Text>
          </Box>

          {index < projects.length - 1 && (
            <Box paddingY={0}>
              <Text dimColor>─────────────────────────────────</Text>
            </Box>
          )}
        </Box>
      ))}
    </Box>
  );
}
