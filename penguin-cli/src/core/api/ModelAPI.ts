import axios from 'axios';

export interface ModelInfo {
  id: string;
  context_length?: number;
  max_output_tokens?: number;
  pricing?: {
    prompt?: number;
    completion?: number;
  };
}

export class ModelAPI {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
  }

  /**
   * Fetch available models from OpenRouter
   */
  async fetchAvailableModels(): Promise<ModelInfo[]> {
    try {
      const response = await axios.get('https://openrouter.ai/api/v1/models');
      const data = response.data;
      
      if (data && data.data && Array.isArray(data.data)) {
        return data.data.map((model: any) => ({
          id: model.id,
          context_length: model.context_length,
          max_output_tokens: model.max_output_tokens,
          pricing: model.pricing,
        }));
      }
      
      return [];
    } catch (error) {
      console.error('Failed to fetch models from OpenRouter:', error);
      return this.getFallbackModels();
    }
  }

  /**
   * Get the current model configuration from the backend
   */
  async getCurrentModel(): Promise<{ model: string; provider: string }> {
    try {
      // Use the correct existing endpoint
      const response = await axios.get(`${this.baseUrl}/api/v1/models/current`);
      return response.data;
    } catch (error) {
      // Fallback to local config if API fails
      try {
        const { loadConfig } = await import('../../config/loader.js');
        const config = await loadConfig();
        
        if (config && config.model) {
          return {
            model: config.model.default,
            provider: config.model.provider || 'openrouter',
          };
        }
      } catch (configError) {
        // Ignore config error, use default
      }
      
      // Return default if both API and config fail
      return {
        model: 'anthropic/claude-3-5-sonnet-20241022',
        provider: 'openrouter',
      };
    }
  }

  /**
   * Update the model configuration via backend API
   */
  async setModel(model: string, provider?: string): Promise<boolean> {
    try {
      // Use the correct existing endpoint for switching models
      await axios.post(`${this.baseUrl}/api/v1/models/switch`, {
        model_id: model,
      });
      
      // Also update local config for persistence
      try {
        const { loadConfig, saveConfig } = await import('../../config/loader.js');
        const config = await loadConfig();
        
        if (config) {
          config.model.default = model;
          config.model.provider = provider || 'openrouter';
          
          // Try to get model info for context window and reasoning settings
          const models = await this.fetchAvailableModels();
          const modelInfo = models.find(m => m.id === model);
          
          if (modelInfo) {
            config.model.context_window = modelInfo.context_length;
            
            // Calculate max_tokens as 90% of the smaller value
            if (modelInfo.max_output_tokens && modelInfo.context_length) {
              config.model.max_tokens = Math.floor(Math.min(
                modelInfo.context_length,
                modelInfo.max_output_tokens
              ) * 0.9);
            } else if (modelInfo.context_length) {
              config.model.max_tokens = Math.floor(modelInfo.context_length * 0.9);
            }
            
            // Configure reasoning for GPT-5/O-series models
            const modelLower = model.toLowerCase();
            if (modelLower.includes('gpt-5') || modelLower.includes('gpt5') ||
                modelLower.includes('/o1') || modelLower.includes('/o3')) {
              config.model.reasoning_enabled = true;
              config.model.reasoning_effort = 'medium'; // Default to medium
            } else {
              config.model.reasoning_enabled = false;
              delete config.model.reasoning_effort;
            }
          }
          
          await saveConfig(config);
        }
      } catch (configError) {
        console.error('Failed to update local config:', configError);
        // Don't fail if local config update fails, API update succeeded
      }
      
      return true;
    } catch (error) {
      console.error('Failed to update model via API:', error);
      
      // Fallback to local config only
      try {
        const { loadConfig, saveConfig } = await import('../../config/loader.js');
        const config = await loadConfig();
        
        if (config) {
          config.model.default = model;
          config.model.provider = provider || 'openrouter';
          
          const models = await this.fetchAvailableModels();
          const modelInfo = models.find(m => m.id === model);
          
          if (modelInfo) {
            config.model.context_window = modelInfo.context_length;
            if (modelInfo.max_output_tokens) {
              config.model.max_tokens = Math.floor(Math.min(
                modelInfo.context_length || 100000,
                modelInfo.max_output_tokens
              ) * 0.9);
            }
          }
          
          await saveConfig(config);
          console.log('Model updated in local config. Restart may be required for changes to take effect.');
          return true;
        }
      } catch (fallbackError) {
        console.error('Fallback config update also failed:', fallbackError);
      }
      
      return false;
    }
  }

  /**
   * Get fallback models if API fails
   */
  private getFallbackModels(): ModelInfo[] {
    return [
      { id: 'anthropic/claude-3-5-sonnet-20241022', context_length: 200000 },
      { id: 'anthropic/claude-3-5-haiku-20241022', context_length: 200000 },
      { id: 'openai/gpt-4o', context_length: 128000 },
      { id: 'openai/o1-preview', context_length: 128000 },
      { id: 'google/gemini-2.0-flash-exp', context_length: 1048576 },
      { id: 'mistralai/mistral-large-latest', context_length: 128000 },
    ];
  }
}