/**
 * Quick Settings Component
 * Displays current settings in a compact format
 * Alternative to full-screen modal
 */
import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
import { loadConfig } from '../../config/loader.js';
import { PenguinConfig } from '../../config/types.js';
import { ModelAPI } from '../../core/api/ModelAPI.js';

interface QuickSettingsProps {
  modelAPI: ModelAPI;
  isExpanded?: boolean;
}

export function QuickSettings({ modelAPI, isExpanded = false }: QuickSettingsProps) {
  const [config, setConfig] = useState<PenguinConfig | null>(null);
  const [currentModel, setCurrentModel] = useState<{ model: string; provider: string } | null>(null);

  useEffect(() => {
    // Load current configuration
    Promise.all([
      loadConfig(),
      modelAPI.getCurrentModel()
    ]).then(([cfg, model]) => {
      setConfig(cfg);
      setCurrentModel(model);
    }).catch(err => {
      // Silent fail for quick settings
    });
  }, []);

  if (!config || !currentModel) {
    return null;
  }

  // Compact view - single line
  if (!isExpanded) {
    return (
      <Box paddingX={1} borderStyle="single" borderColor="gray">
        <Text dimColor>Model: </Text>
        <Text color="cyan">{currentModel.model.split('/').pop()}</Text>
        {config.model.reasoning_effort && (
          <>
            <Text dimColor> • Reasoning: </Text>
            <Text color="yellow">{config.model.reasoning_effort}</Text>
          </>
        )}
        <Text dimColor> • Press Ctrl+S for settings</Text>
      </Box>
    );
  }

  // Expanded view - detailed info
  const isReasoningModel = 
    currentModel.model.toLowerCase().includes('gpt-5') ||
    currentModel.model.toLowerCase().includes('gpt5') ||
    currentModel.model.toLowerCase().includes('/o1') ||
    currentModel.model.toLowerCase().includes('/o3') ||
    (currentModel.model.toLowerCase().includes('gemini') && 
     (currentModel.model.toLowerCase().includes('2.5') || 
      currentModel.model.toLowerCase().includes('2-5')));

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1} borderStyle="single" borderColor="cyan">
      <Text color="cyan" bold>⚙️  Quick Settings</Text>
      
      <Box marginTop={1}>
        <Text>Model: </Text>
        <Text color="green" bold>{currentModel.model}</Text>
      </Box>

      <Box>
        <Text>Provider: </Text>
        <Text color="blue">{currentModel.provider}</Text>
      </Box>

      {config.model.context_window && (
        <Box>
          <Text>Context: </Text>
          <Text color="yellow">{config.model.context_window.toLocaleString()} tokens</Text>
        </Box>
      )}

      {isReasoningModel && config.model.reasoning_effort && (
        <Box>
          <Text>Reasoning: </Text>
          <Text color="magenta">{config.model.reasoning_effort}</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor italic>
          /models - switch model • /model info - details • Ctrl+S - all settings
        </Text>
      </Box>
    </Box>
  );
}