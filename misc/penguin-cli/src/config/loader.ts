/**
 * Configuration loader for Penguin CLI
 * Loads config from multiple sources with precedence
 */

import { promises as fs } from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';
import * as os from 'os';
import type { PenguinConfig } from './types';

/**
 * Get the user config directory (cross-platform)
 */
export function getUserConfigDir(): string {
  if (process.platform === 'win32') {
    return path.join(process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'), 'penguin');
  }
  // Linux/macOS
  return path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'penguin');
}

/**
 * Get the path to the user config file
 */
export function getConfigPath(): string {
  // Environment variable override
  if (process.env.PENGUIN_CONFIG_PATH) {
    return path.resolve(process.env.PENGUIN_CONFIG_PATH);
  }

  return path.join(getUserConfigDir(), 'config.yml');
}

/**
 * Deep merge two objects
 */
function deepMerge(base: any, override: any): any {
  const result = { ...base };

  for (const key in override) {
    if (override[key] && typeof override[key] === 'object' && !Array.isArray(override[key])) {
      result[key] = deepMerge(result[key] || {}, override[key]);
    } else {
      result[key] = override[key];
    }
  }

  return result;
}

/**
 * Load config from a file
 */
async function loadConfigFile(filePath: string): Promise<Partial<PenguinConfig> | null> {
  try {
    const content = await fs.readFile(filePath, 'utf8');
    return yaml.load(content) as Partial<PenguinConfig>;
  } catch (error) {
    // File doesn't exist or can't be read
    return null;
  }
}

/**
 * Find git root starting from a directory
 */
async function findGitRoot(startPath: string): Promise<string | null> {
  let currentPath = path.resolve(startPath);

  while (true) {
    try {
      await fs.access(path.join(currentPath, '.git'));
      return currentPath;
    } catch {
      const parentPath = path.dirname(currentPath);
      if (parentPath === currentPath) {
        return null;
      }
      currentPath = parentPath;
    }
  }
}

/**
 * Get the default config
 */
function getDefaultConfig(): Partial<PenguinConfig> {
  return {
    workspace: {
      path: path.join(os.homedir(), 'penguin_workspace'),
      create_dirs: ['conversations', 'memory_db', 'logs', 'notes', 'projects', 'context'],
    },
    model: {
      default: 'anthropic/claude-sonnet-4.5',
      provider: 'openrouter',
      client_preference: 'openrouter',
      streaming_enabled: true,
      temperature: 0.3,
      max_tokens: 1000000,
      context_window: 1000000,
    },
    api: {
      base_url: null,
    },
    tools: {
      enabled: true,
      allow_web_access: true,
      allow_file_operations: true,
      allow_code_execution: true,
    },
    diagnostics: {
      enabled: true,
      verbose_logging: true,
    },
    project: {
      root_strategy: 'git-root',
      additional_directories: [],
    },
    context: {
      scratchpad_dir: 'context',
      additional_paths: [],
      autoload_project_docs: true,
    },
    defaults: {
      write_root: 'project',
    },
    prompt: {
      mode: 'direct',
    },
    output: {
      prompt_style: 'steps_final',
      show_tool_results: true,
    },
  };
}

/**
 * Load configuration from multiple sources with precedence
 *
 * Precedence (lowest → highest):
 *   1. Default configuration
 *   2. User config (~/.config/penguin/config.yml)
 *   3. Project config (<project_root>/.penguin/config.yml)
 *   4. Explicit override via PENGUIN_CONFIG_PATH
 */
export async function loadConfig(): Promise<PenguinConfig> {
  let merged = getDefaultConfig();

  // 1. User config
  const userConfigPath = getConfigPath();
  const userConfig = await loadConfigFile(userConfigPath);
  if (userConfig) {
    merged = deepMerge(merged, userConfig);
  }

  // 2. Project config (if in a git repo)
  const gitRoot = await findGitRoot(process.cwd());
  if (gitRoot) {
    const projectConfigPath = path.join(gitRoot, '.penguin', 'config.yml');
    const projectConfig = await loadConfigFile(projectConfigPath);
    if (projectConfig) {
      merged = deepMerge(merged, projectConfig);
    }
  }

  return merged as PenguinConfig;
}

/**
 * Save configuration to user config file
 */
export async function saveConfig(config: PenguinConfig): Promise<string> {
  const configPath = getConfigPath();
  const configDir = path.dirname(configPath);

  // Ensure directory exists
  await fs.mkdir(configDir, { recursive: true });

  // Write config
  const yamlContent = yaml.dump(config, {
    indent: 2,
    lineWidth: -1, // Don't wrap lines
    noRefs: true,
  });

  await fs.writeFile(configPath, yamlContent, 'utf8');

  return configPath;
}

/**
 * Check if setup is complete
 */
export async function isSetupComplete(): Promise<boolean> {
  const setupCompleteFile = path.join(getUserConfigDir(), '.penguin_setup_complete');

  try {
    await fs.access(setupCompleteFile);
    return true;
  } catch {
    // Check if config exists and is valid
    const configPath = getConfigPath();
    try {
      await fs.access(configPath);
      const config = await loadConfig();

      // Verify required fields
      return !!(
        config.model?.default &&
        config.workspace?.path &&
        checkApiAccess(config.model.provider)
      );
    } catch {
      return false;
    }
  }
}

/**
 * Mark setup as complete
 */
export async function markSetupComplete(): Promise<void> {
  const setupCompleteFile = path.join(getUserConfigDir(), '.penguin_setup_complete');
  const configDir = path.dirname(setupCompleteFile);

  await fs.mkdir(configDir, { recursive: true });
  await fs.writeFile(
    setupCompleteFile,
    `Setup completed on ${os.hostname()} at ${new Date().toISOString()}\n`,
    'utf8'
  );
}

/**
 * Check if API access is configured for the given provider
 */
function checkApiAccess(provider: string): boolean {
  const apiKeyEnvVars: Record<string, string[]> = {
    'anthropic': ['ANTHROPIC_API_KEY'],
    'openai': ['OPENAI_API_KEY'],
    'openrouter': ['OPENROUTER_API_KEY'],
    'google': ['GOOGLE_API_KEY', 'GEMINI_API_KEY'],
    'mistral': ['MISTRAL_API_KEY'],
    'deepseek': ['DEEPSEEK_API_KEY'],
    'ollama': [], // Local, no API key needed
    'local': [],  // Local, no API key needed
  };

  const envVars = apiKeyEnvVars[provider?.toLowerCase()] || [];
  if (envVars.length === 0) {
    return true; // Local provider
  }

  return envVars.some(varName => !!process.env[varName]);
}

/**
 * Validate configuration and check for issues
 */
export async function validateConfig(): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> {
  const errors: string[] = [];
  const warnings: string[] = [];

  try {
    const config = await loadConfig();

    // Check required fields
    if (!config.model?.default) {
      errors.push('Missing model.default in configuration');
    }

    if (!config.workspace?.path) {
      errors.push('Missing workspace.path in configuration');
    }

    // Check API key
    const provider = config.model?.provider || 'openrouter';
    if (!checkApiAccess(provider)) {
      const envVarName = `${provider.toUpperCase()}_API_KEY`;
      errors.push(`Missing API key: ${envVarName} environment variable not set`);
    }

    // Check workspace directory
    if (config.workspace?.path) {
      try {
        await fs.access(config.workspace.path);
      } catch {
        warnings.push(`Workspace directory does not exist: ${config.workspace.path}`);
      }
    }

    // Check config file syntax
    const configPath = getConfigPath();
    try {
      await fs.access(configPath);
      const content = await fs.readFile(configPath, 'utf8');
      yaml.load(content); // Will throw if invalid YAML
    } catch (error) {
      if ((error as any).code !== 'ENOENT') {
        errors.push(`Invalid YAML syntax in ${configPath}`);
      }
    }

    // Check model configuration
    if (config.model?.temperature !== undefined) {
      if (config.model.temperature < 0 || config.model.temperature > 1) {
        warnings.push('Temperature should be between 0 and 1');
      }
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings,
    };
  } catch (error) {
    errors.push(`Failed to load configuration: ${error}`);
    return { valid: false, errors, warnings };
  }
}

/**
 * Get diagnostic information about the configuration
 */
export async function getConfigDiagnostics(): Promise<string> {
  const lines: string[] = [];

  lines.push('# Penguin Configuration Diagnostics\n');

  // Config file locations
  lines.push('## Configuration Files:');
  lines.push(`- User config: ${getConfigPath()}`);
  lines.push(`- Config directory: ${getUserConfigDir()}`);

  const gitRoot = await findGitRoot(process.cwd());
  if (gitRoot) {
    const projectConfig = path.join(gitRoot, '.penguin', 'config.yml');
    lines.push(`- Project config: ${projectConfig}`);
  }
  lines.push('');

  // Config status
  lines.push('## Configuration Status:');
  const validation = await validateConfig();
  lines.push(`- Valid: ${validation.valid ? '✅' : '❌'}`);

  if (validation.errors.length > 0) {
    lines.push(`- Errors (${validation.errors.length}):`);
    validation.errors.forEach(err => lines.push(`  - ${err}`));
  }

  if (validation.warnings.length > 0) {
    lines.push(`- Warnings (${validation.warnings.length}):`);
    validation.warnings.forEach(warn => lines.push(`  - ${warn}`));
  }
  lines.push('');

  // Current configuration
  try {
    const config = await loadConfig();
    lines.push('## Current Configuration:');
    lines.push(`- Model: ${config.model?.default || 'not set'}`);
    lines.push(`- Provider: ${config.model?.provider || 'not set'}`);
    lines.push(`- Temperature: ${config.model?.temperature ?? 'not set'}`);
    lines.push(`- Workspace: ${config.workspace?.path || 'not set'}`);
    lines.push(`- Streaming: ${config.model?.streaming_enabled ? 'enabled' : 'disabled'}`);
    lines.push('');

    // API Keys
    lines.push('## API Keys:');
    const providers = ['openrouter', 'anthropic', 'openai', 'google'];
    providers.forEach(provider => {
      const hasKey = checkApiAccess(provider);
      lines.push(`- ${provider}: ${hasKey ? '✅ set' : '❌ not set'}`);
    });
    lines.push('');

    // Environment
    lines.push('## Environment:');
    lines.push(`- Platform: ${process.platform}`);
    lines.push(`- Node version: ${process.version}`);
    lines.push(`- CWD: ${process.cwd()}`);
    lines.push(`- Home: ${os.homedir()}`);
    if (gitRoot) {
      lines.push(`- Git root: ${gitRoot}`);
    }
  } catch (error) {
    lines.push(`Error loading configuration: ${error}`);
  }

  return lines.join('\n');
}

/**
 * Save API key to ~/.config/penguin/.env file
 */
export async function saveApiKey(provider: string, apiKey: string): Promise<boolean> {
  try {
    const envPath = path.join(getUserConfigDir(), '.env');
    const envDir = path.dirname(envPath);

    await fs.mkdir(envDir, { recursive: true });

    // Read existing content
    let existing: string[] = [];
    try {
      const content = await fs.readFile(envPath, 'utf8');
      existing = content.split('\n');
    } catch {
      // File doesn't exist yet
    }

    const key = `${provider.toUpperCase()}_API_KEY`;
    const kv = `${key}=${apiKey}`;

    // Replace or append
    let replaced = false;
    for (let i = 0; i < existing.length; i++) {
      if (existing[i].startsWith(`${key}=`)) {
        existing[i] = kv;
        replaced = true;
        break;
      }
    }

    if (!replaced) {
      existing.push(kv);
    }

    await fs.writeFile(envPath, existing.join('\n') + '\n', 'utf8');

    // Set in current process
    process.env[key] = apiKey;

    return true;
  } catch (error) {
    console.error('Failed to save API key:', error);
    return false;
  }
}
