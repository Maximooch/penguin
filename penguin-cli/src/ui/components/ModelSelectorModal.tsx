import React, { useState, useEffect, useCallback } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { ModelAPI, ModelInfo } from '../../core/api/ModelAPI.js';

interface ModelSelectorModalProps {
  onSelect: (model: string) => void;
  onClose: () => void;
}

const isReasoningModel = (modelId: string): boolean => {
  const lower = modelId.toLowerCase();
  return lower.includes('gpt-5') || lower.includes('gpt5') ||
         lower.includes('/o1') || lower.includes('/o3') ||
         (lower.includes('gemini') && (lower.includes('2.5') || lower.includes('2-5')));
};

const isVisionModel = (modelId: string): boolean => {
  const lower = modelId.toLowerCase();
  return lower.includes('vision') || lower.includes('gpt-4o') ||
         lower.includes('claude') || lower.includes('gemini');
};

export function ModelSelectorModal({ onSelect, onClose }: ModelSelectorModalProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [currentModel, setCurrentModel] = useState<string>('');
  const modelAPI = new ModelAPI();

  // Load models on mount
  useEffect(() => {
    const loadModels = async () => {
      setLoading(true);
      try {
        // Fetch current model
        const current = await modelAPI.getCurrentModel();
        setCurrentModel(current.model);
        
        // Fetch available models
        const availableModels = await modelAPI.fetchAvailableModels();
        
        // Sort models with recommended ones first
        const recommended = [
          'openai/gpt-5',
          'openai/gpt-5-turbo',
          'anthropic/claude-3-5-sonnet-20241022',
          'anthropic/claude-3-5-haiku-20241022',
          'openai/gpt-4o',
          'openai/o1-preview',
          'openai/o3-mini',
          'google/gemini-2.5-pro-preview',
          'google/gemini-2.0-flash-exp',
        ];
        
        const sortedModels = [
          ...availableModels.filter(m => recommended.includes(m.id)),
          ...availableModels.filter(m => !recommended.includes(m.id)),
        ];
        
        setModels(sortedModels);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load models');
      } finally {
        setLoading(false);
      }
    };
    
    loadModels();
  }, []);

  // Filter models based on search term
  const filteredModels = models.filter(model =>
    model.id.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Handle input
  useInput((input, key) => {
    if (key.escape) {
      onClose();
    } else if (key.return) {
      if (filteredModels.length > 0) {
        const selected = filteredModels[selectedIndex];
        onSelect(selected.id);
        onClose();
      }
    } else if (key.upArrow) {
      setSelectedIndex(Math.max(0, selectedIndex - 1));
    } else if (key.downArrow) {
      setSelectedIndex(Math.min(filteredModels.length - 1, selectedIndex + 1));
    } else if (key.backspace || key.delete) {
      setSearchTerm(prev => prev.slice(0, -1));
      setSelectedIndex(0);
    } else if (input && !key.ctrl && !key.meta) {
      setSearchTerm(prev => prev + input);
      setSelectedIndex(0);
    }
  });

  // Calculate visible range for scrolling
  const maxVisible = 15;
  const scrollOffset = Math.max(0, selectedIndex - maxVisible + 1);
  const visibleModels = filteredModels.slice(scrollOffset, scrollOffset + maxVisible);

  const formatTokenCount = (tokens?: number): string => {
    if (!tokens) return 'Unknown';
    if (tokens >= 1000000) {
      return `${(tokens / 1000000).toFixed(1)}M`;
    }
    if (tokens >= 1000) {
      return `${Math.floor(tokens / 1000)}K`;
    }
    return tokens.toString();
  };

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" padding={1}>
      {/* Header */}
      <Box marginBottom={1}>
        <Text bold color="cyan">🤖 Model Selection</Text>
        <Box flexGrow={1} />
        <Text dimColor>ESC: Cancel | Enter: Select</Text>
      </Box>

      {/* Current Model */}
      {currentModel && (
        <Box marginBottom={1}>
          <Text dimColor>Current: </Text>
          <Text color="green">{currentModel}</Text>
        </Box>
      )}

      {/* Search */}
      <Box marginBottom={1}>
        <Text>Search: </Text>
        <Text color="yellow">{searchTerm}</Text>
        <Text dimColor>█</Text>
      </Box>

      {/* Loading/Error State */}
      {loading && <Text dimColor>Loading models...</Text>}
      {error && <Text color="red">Error: {error}</Text>}

      {/* Model List */}
      {!loading && !error && (
        <>
          <Box flexDirection="column" marginBottom={1}>
            {visibleModels.length === 0 ? (
              <Text dimColor>No models found matching "{searchTerm}"</Text>
            ) : (
              visibleModels.map((model, index) => {
                const actualIndex = scrollOffset + index;
                const isSelected = actualIndex === selectedIndex;
                const isCurrent = model.id === currentModel;
                
                const hasReasoning = isReasoningModel(model.id);
                const hasVision = isVisionModel(model.id);
                
                return (
                  <Box key={model.id}>
                    <Text color={isSelected ? 'cyan' : isCurrent ? 'green' : 'white'}>
                      {isSelected ? '▸ ' : '  '}
                      {isCurrent ? '● ' : ''}
                    </Text>
                    <Box width={50}>
                      <Text 
                        bold={isSelected}
                        color={isSelected ? 'cyan' : isCurrent ? 'green' : 'white'}
                      >
                        {model.id}
                      </Text>
                    </Box>
                    <Text dimColor>
                      {' '}[{formatTokenCount(model.context_length)} tokens]
                    </Text>
                    {model.max_output_tokens && (
                      <Text dimColor>
                        {' '}Max: {formatTokenCount(model.max_output_tokens)}
                      </Text>
                    )}
                    {hasReasoning && (
                      <Text color="yellow">
                        {' '}🧠
                      </Text>
                    )}
                    {hasVision && (
                      <Text color="blue">
                        {' '}👁️
                      </Text>
                    )}
                  </Box>
                );
              })
            )}
          </Box>

          {/* Footer */}
          <Box>
            <Text dimColor>
              Showing {visibleModels.length} of {filteredModels.length} models
            </Text>
            {filteredModels.length > maxVisible && (
              <Text dimColor> | ↑↓ to scroll</Text>
            )}
          </Box>

          {/* Tips and Legend */}
          <Box marginTop={1} flexDirection="column">
            <Text dimColor>💡 Tips:</Text>
            <Text dimColor>• Larger context = more conversation history</Text>
            <Text dimColor>• Claude models excel at coding tasks</Text>
            <Text dimColor>• GPT-5/O-series have advanced reasoning 🧠</Text>
            <Text dimColor>• Models with 👁️ support image analysis</Text>
            <Box marginTop={1}>
              <Text dimColor>Legend: </Text>
              <Text color="yellow">🧠 Reasoning</Text>
              <Text dimColor> | </Text>
              <Text color="blue">👁️ Vision</Text>
              <Text dimColor> | </Text>
              <Text color="green">● Current</Text>
            </Box>
          </Box>
        </>
      )}
    </Box>
  );
}