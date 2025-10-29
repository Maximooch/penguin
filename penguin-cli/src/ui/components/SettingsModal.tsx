/**
 * Settings Modal Component
 * Provides a configuration interface for various settings
 */
import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import SelectInput from 'ink-select-input';
import { loadConfig, saveConfig } from '../../config/loader.js';
import { PenguinConfig } from '../../config/types.js';
import { ModelAPI } from '../../core/api/ModelAPI.js';

interface SettingsModalProps {
  onClose: () => void;
  modelAPI: ModelAPI;
}

export function SettingsModal({ onClose, modelAPI }: SettingsModalProps) {
  const [config, setConfig] = useState<PenguinConfig | null>(null);
  const [currentSection, setCurrentSection] = useState<'main' | 'model' | 'reasoning'>('main');
  const [currentModel, setCurrentModel] = useState<{ model: string; provider: string } | null>(null);
  const [reasoningEffort, setReasoningEffort] = useState<'low' | 'medium' | 'high'>('medium');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Handle ESC key to close or go back
  useInput((input, key) => {
    if (key.escape) {
      if (currentSection !== 'main') {
        setCurrentSection('main');
      } else {
        onClose();
      }
    }
  });

  useEffect(() => {
    // Load current configuration
    Promise.all([
      loadConfig(),
      modelAPI.getCurrentModel()
    ]).then(([cfg, model]) => {
      setConfig(cfg);
      setCurrentModel(model);
      if (cfg?.model?.reasoning_effort) {
        setReasoningEffort(cfg.model.reasoning_effort);
      }
      setLoading(false);
    }).catch(err => {
      setError(`Failed to load settings: ${err.message}`);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text color="cyan" bold>⚙️  Settings</Text>
        <Text dimColor>Loading configuration...</Text>
      </Box>
    );
  }

  if (error) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="red" paddingX={2} paddingY={1}>
        <Text color="red" bold>⚙️  Settings Error</Text>
        <Text color="red">{error}</Text>
        <Text dimColor>Press ESC to close</Text>
      </Box>
    );
  }

  const mainMenuItems = [
    { label: '🤖 Model Configuration', value: 'model' },
    { label: '🧠 Reasoning Settings', value: 'reasoning' },
    { label: '🔙 Close Settings (ESC)', value: 'close' }
  ];

  const reasoningEffortItems = [
    { label: '⚡ Low (Faster, less thorough)', value: 'low' },
    { label: '⚖️  Medium (Balanced)', value: 'medium' },
    { label: '🎯 High (Slower, more thorough)', value: 'high' },
    { label: '🔙 Back', value: 'back' }
  ];

  const handleMainSelect = (item: any) => {
    if (item.value === 'close') {
      onClose();
    } else {
      setCurrentSection(item.value);
    }
  };

  const handleReasoningSelect = async (item: any) => {
    if (item.value === 'back') {
      setCurrentSection('main');
      return;
    }

    try {
      if (config) {
        const newConfig = { ...config };
        if (!newConfig.model) {
          newConfig.model = {} as any;
        }
        newConfig.model.reasoning_effort = item.value;
        setReasoningEffort(item.value);
        
        await saveConfig(newConfig);
        setConfig(newConfig);
        setCurrentSection('main');
      }
    } catch (err: any) {
      setError(`Failed to save setting: ${err.message}`);
    }
  };

  // Check if current model supports reasoning
  const supportsReasoning = currentModel && (
    currentModel.model.toLowerCase().includes('gpt-5') ||
    currentModel.model.toLowerCase().includes('gpt5') ||
    currentModel.model.toLowerCase().includes('/o1') ||
    currentModel.model.toLowerCase().includes('/o3') ||
    (currentModel.model.toLowerCase().includes('gemini') && 
     (currentModel.model.toLowerCase().includes('2.5') || 
      currentModel.model.toLowerCase().includes('2-5')))
  );

  if (currentSection === 'model') {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text color="cyan" bold>🤖 Model Configuration</Text>
        <Box marginY={1}>
          <Text>Current Model: </Text>
          <Text color="green" bold>{currentModel?.model || 'Unknown'}</Text>
        </Box>
        <Text>Provider: <Text color="blue">{currentModel?.provider || 'Unknown'}</Text></Text>
        {config?.model?.context_window && (
          <Text>Context Window: <Text color="yellow">{config.model.context_window.toLocaleString()} tokens</Text></Text>
        )}
        {config?.model?.max_tokens && (
          <Text>Max Output: <Text color="yellow">{config.model.max_tokens.toLocaleString()} tokens</Text></Text>
        )}
        <Box marginTop={1}>
          <Text dimColor>Press ESC to go back</Text>
        </Box>
      </Box>
    );
  }

  if (currentSection === 'reasoning') {
    if (!supportsReasoning) {
      return (
        <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={2} paddingY={1}>
          <Text color="yellow" bold>🧠 Reasoning Settings</Text>
          <Box marginY={1}>
            <Text>Current model doesn't support reasoning configuration.</Text>
          </Box>
          <Text dimColor>Models that support reasoning: GPT-5, O1, O3, Gemini 2.5</Text>
          <Box marginTop={1}>
            <Text dimColor>Press ESC to go back</Text>
          </Box>
        </Box>
      );
    }

    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text color="cyan" bold>🧠 Reasoning Settings</Text>
        <Box marginY={1}>
          <Text>Select reasoning effort level for {currentModel?.model}:</Text>
        </Box>
        <Text dimColor>Current: <Text color="green">{reasoningEffort}</Text></Text>
        <Box marginTop={1}>
          <SelectInput items={reasoningEffortItems} onSelect={handleReasoningSelect} />
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
      <Text color="cyan" bold>⚙️  Settings</Text>
      <Box marginY={1}>
        <SelectInput items={mainMenuItems} onSelect={handleMainSelect} />
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Navigate with ↑↓ keys, Enter to select</Text>
      </Box>
    </Box>
  );
}