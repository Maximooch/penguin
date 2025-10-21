/**
 * Setup wizard for Penguin CLI
 * Interactive configuration using inquirer
 */

import inquirer from 'inquirer';
import { search } from '@inquirer/prompts';
import chalk from 'chalk';
import * as os from 'os';
import * as path from 'path';
import { promises as fs } from 'fs';
import type { PenguinConfig, SetupWizardResult } from './types';
import { saveConfig, saveApiKey, markSetupComplete, getUserConfigDir } from './loader';

/**
 * Display a section header
 */
function displaySectionHeader(title: string): void {
  console.log(`\n${chalk.cyan.bold(`━━━━ ${title} ━━━━`)}`);
}

/**
 * Display welcome banner
 */
function displayWelcomeBanner(): void {
  console.clear();
  console.log(chalk.cyan.bold('\n╭───────────────────────────────────────────╮'));
  console.log(chalk.cyan.bold('│') + chalk.white.bold('  🐧 PENGUIN SETUP WIZARD  ') + chalk.cyan.bold('│'));
  console.log(chalk.cyan.bold('╰───────────────────────────────────────────╯'));
  console.log('\nWelcome! Let\'s configure your environment for optimal performance.\n');
}

/**
 * Fetch available models from OpenRouter
 */
async function fetchModelsFromOpenRouter(): Promise<any[]> {
  try {
    console.log(chalk.cyan('Fetching latest models from OpenRouter...'));
    const response = await fetch('https://openrouter.ai/api/v1/models', {
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) {
      console.log(chalk.yellow('⚠️  Failed to fetch models from OpenRouter'));
      return getFallbackModels();
    }

    const data = await response.json() as { data?: any[] };
    const models = data.data || [];
    console.log(chalk.green('✓') + ` Found ${chalk.bold(models.length.toString())} available models`);
    return models;
  } catch (error) {
    console.log(chalk.yellow('⚠️  Failed to fetch models from OpenRouter'));
    return getFallbackModels();
  }
}

/**
 * Get fallback models list if API fails
 */
function getFallbackModels(): any[] {
  console.log(chalk.dim('ℹ️  Using fallback model list'));
  return [
    { id: 'anthropic/claude-sonnet-4.5', context_length: 200000 },
    { id: 'anthropic/claude-opus-4', context_length: 200000 },
    { id: 'anthropic/claude-3.5-sonnet', context_length: 200000 },
    { id: 'openai/o3-mini', context_length: 128000 },
    { id: 'google/gemini-2.5-pro-preview', context_length: 1000000 },
    { id: 'mistralai/mistral-large-2411', context_length: 128000 },
  ];
}

/**
 * Prepare model choices for selection
 */
function prepareModelChoices(models: any[]): { choices: string[]; modelMap: Map<string, string> } {
  const choices: string[] = [];
  const modelMap = new Map<string, string>();

  // Recommended models
  const recommended = [
    'anthropic/claude-sonnet-4.5',
    'anthropic/claude-3-5-sonnet-20240620',
    'openai/o3-mini',
    'google/gemini-2-5-pro-preview',
    'mistral/devstral',
  ];

  // Add recommended models first
  for (const recId of recommended) {
    const model = models.find(m => m.id === recId);
    if (model) {
      const contextLength = model.context_length || 'unknown';
      const display = `${model.id} (${contextLength} tokens)`;
      choices.push(display);
      modelMap.set(display, model.id);
    }
  }

  // Add remaining models
  for (const model of models) {
    if (recommended.includes(model.id)) {
      continue;
    }

    const contextLength = model.context_length || 'unknown';
    const display = `${model.id} (${contextLength} tokens)`;
    choices.push(display);
    modelMap.set(display, model.id);
  }

  // Add custom option
  choices.push('Custom (specify)');

  return { choices, modelMap };
}

/**
 * Run the setup wizard
 */
export async function runSetupWizard(): Promise<SetupWizardResult> {
  displayWelcomeBanner();

  // Step 1: Workspace Configuration
  displaySectionHeader('Workspace Configuration');
  console.log('This is where Penguin will store your projects and contextual data.');

  const defaultWorkspace = path.join(os.homedir(), 'penguin_workspace');
  console.log(chalk.dim('(Press Enter to accept default)'));

  const { workspacePath } = await inquirer.prompt([
    {
      type: 'input',
      name: 'workspacePath',
      message: 'Workspace directory:',
      default: defaultWorkspace,
    },
  ]);

  // Step 2: Model Selection
  displaySectionHeader('Model Selection');
  console.log('Choose which AI model Penguin will use by default.\n');

  // Always fetch fresh models from API
  const models = await fetchModelsFromOpenRouter();

  let modelSelection: string;
  let model: string;

  if (models.length > 0) {
    const { choices, modelMap } = prepareModelChoices(models);
    console.log(chalk.dim('\n💡 Tip: Larger context windows (more tokens) let Penguin process more information at once.'));
    console.log(chalk.dim('   For code-heavy tasks, 32K+ tokens is recommended.'));
    console.log(chalk.dim('   Type to search, ↑↓ to navigate\n'));

    // Use search prompt for better model selection with filtering
    modelSelection = await search({
      message: 'Choose your default AI model:',
      source: async (input) => {
        if (!input) {
          // Show all choices when no search input
          return choices.map(choice => ({ value: choice, name: choice }));
        }

        // Filter choices based on search input (case-insensitive, matches anywhere)
        const filtered = choices.filter(choice =>
          choice.toLowerCase().includes(input.toLowerCase())
        );

        return filtered.map(choice => ({ value: choice, name: choice }));
      },
      pageSize: 15,
    });

    if (modelSelection === 'Custom (specify)') {
      console.log(chalk.dim('(Format: provider/model-name)'));
      const customAnswer = await inquirer.prompt([
        {
          type: 'input',
          name: 'customModel',
          message: 'Enter custom model identifier:',
          validate: (input) => input.length > 0 || 'Model identifier cannot be empty',
        },
      ]);
      model = customAnswer.customModel;
    } else {
      model = modelMap.get(modelSelection) || modelSelection.split(' ')[0];
    }
  } else {
    // Fallback to default list
    const fallbackChoices = [
      'anthropic/claude-sonnet-4.5 (200K tokens)',
      'anthropic/claude-3-5-sonnet-20240620 (200K tokens)',
      'openai/o3-mini (128K tokens)',
      'google/gemini-2-5-pro-preview (1M tokens)',
      'mistral/devstral (32K tokens)',
      'Custom (specify)',
    ];

    const answers = await inquirer.prompt([
      {
        type: 'list',
        name: 'modelSelection',
        message: 'Choose your default AI model:',
        choices: fallbackChoices,
        pageSize: 10,
      },
    ]);

    modelSelection = answers.modelSelection;

    if (modelSelection === 'Custom (specify)') {
      const customAnswer = await inquirer.prompt([
        {
          type: 'input',
          name: 'customModel',
          message: 'Enter custom model identifier:',
          validate: (input) => input.length > 0 || 'Model identifier cannot be empty',
        },
      ]);
      model = customAnswer.customModel;
    } else {
      model = modelSelection.split(' ')[0];
    }
  }

  console.log(chalk.green('✓') + ` Selected model: ${chalk.cyan.bold(model)}`);

  // Determine provider
  const providerFromModel = model.includes('/') ? model.split('/')[0] : 'anthropic';

  // Check if model should use OpenRouter
  const willUseOpenRouter = models.some(m => m.id === model) ||
    ['openai', 'anthropic', 'google', 'mistral'].includes(providerFromModel);

  const actualProvider = willUseOpenRouter ? 'openrouter' : providerFromModel;

  if (willUseOpenRouter) {
    console.log(chalk.dim('ℹ️  This model will be accessed through OpenRouter for unified API access.'));
  }

  // Auto-detect context length and calculate max tokens
  let contextWindow: number | undefined;
  let maxTokens: number | undefined;

  const selectedModel = models.find(m => m.id === model);
  if (selectedModel) {
    contextWindow = selectedModel.context_length;
    const modelMaxOutput = selectedModel.max_output_tokens;

    // Calculate max tokens as 90% of the smaller value between context window and max output
    if (modelMaxOutput && contextWindow) {
      maxTokens = Math.floor(Math.min(contextWindow, modelMaxOutput) * 0.9);
    } else if (contextWindow) {
      maxTokens = Math.floor(contextWindow * 0.9);
    } else if (modelMaxOutput) {
      maxTokens = Math.floor(modelMaxOutput * 0.9);
    }
  }

  // Step 3: API Configuration
  displaySectionHeader('API Configuration');
  console.log(`Configure access to the ${actualProvider} API.`);

  const { needApiKey } = await inquirer.prompt([
    {
      type: 'confirm',
      name: 'needApiKey',
      message: `Do you need to set up an API key for ${actualProvider}?`,
      default: true,
    },
  ]);

  let apiKey: string | undefined;

  if (needApiKey) {
    // Show help text based on provider
    if (actualProvider === 'openrouter') {
      console.log(chalk.dim('\nℹ️  OpenRouter API keys can be obtained at: https://openrouter.ai/keys'));
      console.log(chalk.dim('   OpenRouter provides unified access to models from multiple providers.'));
    } else if (actualProvider === 'anthropic') {
      console.log(chalk.dim('\nℹ️  Anthropic API keys can be obtained at: https://console.anthropic.com/'));
    } else if (actualProvider === 'openai') {
      console.log(chalk.dim('\nℹ️  OpenAI API keys can be obtained at: https://platform.openai.com/api-keys'));
    }

    console.log(chalk.dim('(Input is hidden for security)'));

    const answer = await inquirer.prompt([
      {
        type: 'password',
        name: 'apiKey',
        message: `Enter your ${actualProvider} API key:`,
        mask: '*',
        validate: (input) => input.length > 10 || 'API key seems too short',
      },
    ]);

    apiKey = answer.apiKey;

    // Save API key
    if (apiKey && await saveApiKey(actualProvider, apiKey)) {
      console.log(chalk.green('✓') + ' API key saved to ~/.config/penguin/.env and exported for this session');
    } else {
      console.log(chalk.yellow('⚠️  Could not persist API key automatically.'));
    }
  } else {
    console.log(chalk.yellow('ℹ️  No API key provided. You\'ll need to set this up later.'));
  }

  // Step 4: Advanced Options
  displaySectionHeader('Advanced Options');

  const { showAdvanced } = await inquirer.prompt([
    {
      type: 'confirm',
      name: 'showAdvanced',
      message: 'Would you like to configure advanced options?',
      default: false,
    },
  ]);

  let temperature = 0.7;
  let allowWebAccess = true;
  let allowCodeExecution = true;
  let diagnosticsEnabled = false;
  let verboseLogging = false;

  if (showAdvanced) {
    console.log(chalk.bold('\nPerformance Settings'));
    console.log(chalk.dim('(Lower = more deterministic, Higher = more creative)'));

    const advancedAnswers = await inquirer.prompt([
      {
        type: 'input',
        name: 'temperature',
        message: 'Model temperature (0.0-1.0):',
        default: '0.7',
        validate: (input) => {
          const num = parseFloat(input);
          return (!isNaN(num) && num >= 0 && num <= 1) || 'Please enter a number between 0.0 and 1.0';
        },
      },
    ]);

    temperature = parseFloat(advancedAnswers.temperature);

    // If context window wasn't auto-detected, ask for it
    // Context window and max tokens are auto-detected from model metadata
    // No need to ask the user - we use 90% of model limits to avoid API errors

    // Security & Permissions
    console.log(chalk.bold('\nSecurity & Permissions'));

    const securityAnswers = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'allowWebAccess',
        message: 'Allow Penguin to access the web?',
        default: true,
      },
      {
        type: 'confirm',
        name: 'allowCodeExecution',
        message: 'Allow Penguin to execute code?',
        default: true,
      },
    ]);

    allowWebAccess = securityAnswers.allowWebAccess;
    allowCodeExecution = securityAnswers.allowCodeExecution;

    // Note: Diagnostics/telemetry not yet implemented - skipping for now
  }

  // Build configuration
  const config: PenguinConfig = {
    workspace: {
      path: workspacePath,
      create_dirs: ['conversations', 'memory_db', 'logs', 'notes', 'projects', 'context'],
    },
    model: {
      default: model,
      provider: willUseOpenRouter ? 'openrouter' : providerFromModel,
      client_preference: willUseOpenRouter ? 'openrouter' : 'litellm',
      streaming_enabled: true,
      temperature,
      context_window: contextWindow,
      max_tokens: maxTokens,
    },
    api: {
      base_url: null,
    },
    tools: {
      enabled: true,
      allow_web_access: allowWebAccess,
      allow_file_operations: true,
      allow_code_execution: allowCodeExecution,
    },
    diagnostics: {
      enabled: diagnosticsEnabled,
      verbose_logging: verboseLogging,
    },
  };

  // Step 5: Finalize
  displaySectionHeader('Configuration Summary');

  console.log('\n' + chalk.bold('Your Configuration:'));
  console.log(`  • Workspace: ${chalk.cyan(config.workspace.path)}`);
  console.log(`  • Model: ${chalk.cyan(config.model.default)}`);
  console.log(`  • Provider: ${chalk.cyan(config.model.provider)}`);
  console.log(`  • Temperature: ${chalk.cyan(config.model.temperature.toString())}`);
  if (contextWindow) {
    console.log(`  • Context Window: ${chalk.cyan(`${contextWindow.toLocaleString()} tokens`)}`);
  }
  if (maxTokens) {
    console.log(`  • Max Output: ${chalk.cyan(`${maxTokens.toLocaleString()} tokens`)} ${chalk.dim('(90% of limit)')}`);
  }
  console.log(`  • Web Access: ${config.tools.allow_web_access ? chalk.green('Enabled') : chalk.red('Disabled')}`);
  console.log(`  • Code Execution: ${config.tools.allow_code_execution ? chalk.green('Enabled') : chalk.red('Disabled')}`);

  const { confirmSave } = await inquirer.prompt([
    {
      type: 'confirm',
      name: 'confirmSave',
      message: 'Save this configuration?',
      default: true,
    },
  ]);

  if (confirmSave) {
    console.log(chalk.cyan('Saving configuration...'));

    const savedConfigPath = await saveConfig(config);
    console.log(chalk.green.bold('✓ Configuration saved successfully!'));
    console.log(chalk.dim(`Saved to: ${savedConfigPath}`));

    // Mark setup as complete
    await markSetupComplete();

    // Create workspace directory
    try {
      await fs.mkdir(config.workspace.path, { recursive: true });

      // Create subdirectories
      for (const subdir of config.workspace.create_dirs) {
        await fs.mkdir(path.join(config.workspace.path, subdir), { recursive: true });
      }

      console.log(chalk.green.bold('✓ Created workspace directory:') + ` ${config.workspace.path}`);
    } catch (error) {
      console.log(chalk.red('⚠️  Could not create workspace directory:'), error);
    }

    // Show API key setup reminder
    if (apiKey) {
      const envVarName = `${actualProvider.toUpperCase()}_API_KEY`;
      console.log(chalk.yellow.bold('\n📋 Next Steps:'));
      console.log('Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):');
      console.log(chalk.cyan(`  export ${envVarName}="your-api-key-here"`));
      console.log(chalk.dim('\nThe API key has been saved to ~/.config/penguin/.env'));
      console.log(chalk.dim('Penguin will automatically load it from there.'));
    }

    // Final success message
    console.log(chalk.green.bold('\n╭───────────────────────────────────────────╮'));
    console.log(chalk.green.bold('│') + chalk.white.bold('    🎉 PENGUIN SETUP COMPLETE!    ') + chalk.green.bold('│'));
    console.log(chalk.green.bold('╰───────────────────────────────────────────╯'));
    console.log('\nYou\'re ready to start using Penguin AI Assistant!\n');
    console.log(chalk.dim('You can always update these settings by running /setup in the CLI.'));
    console.log(chalk.dim('Run `penguin` to launch the assistant.\n'));
  } else {
    console.log(chalk.yellow('Configuration not saved. Run setup again when ready.'));
  }

  return {
    config,
    apiKey,
    provider: actualProvider,
  };
}
