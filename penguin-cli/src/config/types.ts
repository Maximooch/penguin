/**
 * Configuration types for Penguin CLI
 * Matches the structure from penguin/config.yml
 */

export interface WorkspaceConfig {
  path: string;
  create_dirs: string[];
}

export interface ModelConfig {
  default: string;
  provider: string;
  client_preference: string;
  streaming_enabled: boolean;
  temperature: number;
  max_tokens?: number;
  context_window?: number;
}

export interface ApiConfig {
  base_url: string | null;
}

export interface ToolsConfig {
  enabled: boolean;
  allow_web_access: boolean;
  allow_file_operations: boolean;
  allow_code_execution: boolean;
}

export interface DiagnosticsConfig {
  enabled: boolean;
  verbose_logging: boolean;
}

export interface ProjectConfig {
  root_strategy: string;
  additional_directories: string[];
}

export interface ContextConfig {
  scratchpad_dir: string;
  additional_paths: string[];
  autoload_project_docs: boolean;
}

export interface DefaultsConfig {
  write_root: string;
}

export interface PromptConfig {
  mode: string;
}

export interface OutputConfig {
  prompt_style: string;
  show_tool_results: boolean;
}

export interface PenguinConfig {
  workspace: WorkspaceConfig;
  model: ModelConfig;
  api: ApiConfig;
  tools: ToolsConfig;
  diagnostics: DiagnosticsConfig;
  project?: ProjectConfig;
  context?: ContextConfig;
  defaults?: DefaultsConfig;
  prompt?: PromptConfig;
  output?: OutputConfig;
}

export interface SetupWizardResult {
  config: PenguinConfig;
  apiKey?: string;
  provider: string;
}
