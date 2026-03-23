/**
 * Command Registry System for Penguin Ink CLI
 *
 * Loads and manages commands from commands.yml configuration.
 * Port of command_registry.py to TypeScript.
 */

import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';
import { logger } from '../../utils/logger';
import type {
  Command,
  CommandCategory,
  CommandConfig,
  CommandParameter,
  ParsedCommand,
  CommandHandler,
  CommandHandlers,
} from './types.js';

export class CommandRegistry {
  private commands: Map<string, Command> = new Map();
  private aliases: Map<string, string> = new Map();
  private categories: Map<string, CommandCategory> = new Map();
  private handlers: CommandHandlers = {};

  constructor(private configPath?: string) {
    if (!configPath) {
      // Default to commands.yml in the penguin/cli directory
      this.configPath = path.join(process.cwd(), '..', 'penguin', 'cli', 'commands.yml');
    }
    this.loadCommands();
  }

  /**
   * Load commands from YAML configuration file.
   */
  private loadCommands(): void {
    // Always register builtin commands first
    this.registerBuiltinCommands();

    if (!this.configPath || !fs.existsSync(this.configPath)) {
      logger.debug(`[CommandRegistry] Commands config not found: ${this.configPath}`);
      return;
    }

    try {
      const fileContent = fs.readFileSync(this.configPath, 'utf8');
      const config = yaml.load(fileContent) as CommandConfig;

      // Process categories
      if (config.categories) {
        for (const category of config.categories) {
          this.categories.set(category.name, category);
        }
      }

      // Process commands (these can override builtins)
      if (config.commands) {
        for (const cmdDef of config.commands) {
          const command = this.createCommand(cmdDef);
          if (command.enabled !== false) {  // Changed from command.enabled to handle undefined
            this.register(command);
          }
        }
      }

      logger.debug(`[CommandRegistry] Loaded ${this.commands.size} commands (including builtins)`);
      // Debug: Show first few commands
      const commandNames = Array.from(this.commands.keys()).slice(0, 15);
      logger.debug(`[CommandRegistry] Sample commands: ${commandNames.join(', ')}`);
    } catch (error) {
      logger.warn(`[CommandRegistry] Error loading commands config:`, error as Error);
    }
  }

  /**
   * Create a Command object from YAML definition.
   */
  private createCommand(cmdDef: any): Command {
    const parameters: CommandParameter[] = [];

    if (cmdDef.parameters) {
      for (const paramDef of cmdDef.parameters) {
        parameters.push({
          name: paramDef.name,
          type: paramDef.type || 'string',
          required: paramDef.required ?? true,
          description: paramDef.description || '',
          default: paramDef.default,
        });
      }
    }

    return {
      name: cmdDef.name,
      category: cmdDef.category || 'general',
      description: cmdDef.description || '',
      handler: cmdDef.handler || '',
      aliases: cmdDef.aliases || [],
      parameters,
      enabled: cmdDef.enabled ?? true,
    };
  }

  /**
   * Register a command in the registry.
   */
  register(command: Command): void {
    this.commands.set(command.name, command);

    // Register aliases
    for (const alias of command.aliases) {
      this.aliases.set(alias, command.name);
    }
  }

  /**
   * Register a command handler function.
   */
  registerHandler(handlerName: string, handler: CommandHandler): void {
    this.handlers[handlerName] = handler;
  }

  /**
   * Find command by exact name or alias.
   */
  findCommand(input: string): Command | null {
    if (this.commands.has(input)) {
      return this.commands.get(input)!;
    }
    if (this.aliases.has(input)) {
      const commandName = this.aliases.get(input)!;
      return this.commands.get(commandName)!;
    }
    return null;
  }

  /**
   * Parse user input into command and arguments.
   *
   * Returns ParsedCommand or null if not a valid command.
   */
  parseInput(input: string): ParsedCommand | null {
    let trimmed = input.trim();
    if (!trimmed) return null;

    // Remove leading slash if present
    if (trimmed.startsWith('/')) {
      trimmed = trimmed.slice(1);
    }

    const parts = trimmed.split(/\s+/);
    let command: Command | null = null;
    let remainingArgs = '';

    // 1) Try exact match on full string
    if (this.commands.has(trimmed) || this.aliases.has(trimmed)) {
      command = this.findCommand(trimmed);
      if (command) {
        const usedTokens = command.name.split(/\s+/).length;
        remainingArgs = parts.slice(usedTokens).join(' ');
      }
    }

    // 2) Try longest prefix match (for multi-word commands like "chat list")
    if (!command) {
      let bestName: string | null = null;
      let bestLen = -1;

      for (const [cmdName] of this.commands) {
        const cmdTokens = cmdName.split(/\s+/);
        if (parts.length >= cmdTokens.length) {
          const match = cmdTokens.every((token, i) => parts[i] === token);
          if (match && cmdTokens.length > bestLen) {
            bestName = cmdName;
            bestLen = cmdTokens.length;
          }
        }
      }

      if (bestName) {
        command = this.commands.get(bestName)!;
        remainingArgs = parts.slice(bestLen).join(' ');
      }
    }

    if (!command) return null;

    // Parse arguments
    const args = this.parseArgs(command, remainingArgs);
    return { command, args };
  }

  /**
   * Parse arguments string into parameter dict.
   */
  private parseArgs(command: Command, argsStr: string): Record<string, any> {
    const args: Record<string, any> = {};

    if (!argsStr || !argsStr.trim()) {
      // No arguments provided - use defaults
      for (const param of command.parameters) {
        if (!param.required) {
          args[param.name] = param.default;
        }
      }
      return args;
    }

    // Simple split by whitespace (could use shlex-like parsing later)
    const parts = argsStr.trim().split(/\s+/);

    for (let i = 0; i < command.parameters.length; i++) {
      const param = command.parameters[i];
      const isLastParam = i === command.parameters.length - 1;

      if (i < parts.length) {
        // For the last parameter, capture all remaining text
        const raw = isLastParam ? parts.slice(i).join(' ') : parts[i];

        // Type conversion
        switch (param.type) {
          case 'int':
            const parsed = parseInt(raw, 10);
            args[param.name] = isNaN(parsed) ? param.default : parsed;
            break;
          case 'bool':
            args[param.name] = ['true', 'yes', '1', 'on'].includes(raw.toLowerCase());
            break;
          default:
            args[param.name] = raw;
        }
      } else if (!param.required) {
        args[param.name] = param.default;
      }
    }

    return args;
  }

  /**
   * Get command suggestions for autocomplete.
   */
  getSuggestions(partial: string): string[] {
    if (!partial) return [];

    // Remove leading slash
    const search = partial.startsWith('/') ? partial.slice(1) : partial;
    const suggestions: string[] = [];

    // Check commands
    for (const [cmdName] of this.commands) {
      if (cmdName.startsWith(search)) {
        suggestions.push(`/${cmdName}`);
      }
    }

    // Check aliases
    for (const [alias] of this.aliases) {
      if (alias.startsWith(search)) {
        suggestions.push(`/${alias}`);
      }
    }

    return suggestions.sort().slice(0, 10); // Limit to 10
  }

  /**
   * Get help text for all commands.
   */
  getHelpText(): string {
    const lines: string[] = ['**Available Commands:**\n'];

    // Group commands by category
    const byCategory = new Map<string, Command[]>();
    for (const [, command] of this.commands) {
      if (!byCategory.has(command.category)) {
        byCategory.set(command.category, []);
      }
      byCategory.get(command.category)!.push(command);
    }

    // Sort categories and commands
    const sortedCategories = Array.from(byCategory.keys()).sort();

    for (const categoryName of sortedCategories) {
      const commands = byCategory.get(categoryName)!;
      if (commands.length === 0) continue;

      // Category header
      const category = this.categories.get(categoryName);
      const icon = category?.icon || '';
      const title = categoryName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
      lines.push(`\n**${icon} ${title}:**`);

      // Commands in category
      for (const cmd of commands.sort((a, b) => a.name.localeCompare(b.name))) {
        let cmdStr = `/${cmd.name}`;
        if (cmd.aliases.length > 0) {
          const aliasStr = cmd.aliases.map((a) => `/${a}`).join(', ');
          cmdStr += ` (${aliasStr})`;
        }

        lines.push(`- \`${cmdStr}\` - ${cmd.description}`);

        // Parameters
        if (cmd.parameters.length > 0) {
          for (const param of cmd.parameters) {
            const req = param.required ? 'required' : 'optional';
            lines.push(`    • ${param.name} (${param.type}, ${req}): ${param.description}`);
          }
        }
      }
    }

    return lines.join('\n');
  }

  /**
   * Execute a command by name with arguments.
   */
  async execute(commandName: string, args: Record<string, any>, context?: any): Promise<void> {
    const command = this.findCommand(commandName);
    if (!command) {
      throw new Error(`Command not found: ${commandName}`);
    }

    const handler = this.handlers[command.handler];
    if (!handler) {
      throw new Error(`Handler not found: ${command.handler} for command ${commandName}`);
    }

    await handler(args, context);
  }

  /**
   * Register minimal builtin commands as fallback.
   */
  private registerBuiltinCommands(): void {
    const builtins: Command[] = [
      {
        name: 'help',
        category: 'system',
        description: 'Show help',
        handler: '_show_help',
        aliases: ['h', '?'],
        parameters: [],
        enabled: true,
      },
      {
        name: 'clear',
        category: 'chat',
        description: 'Clear chat',
        handler: 'action_clear_log',
        aliases: ['cls'],
        parameters: [],
        enabled: true,
      },
      {
        name: 'quit',
        category: 'system',
        description: 'Exit',
        handler: 'action_quit',
        aliases: ['exit', 'q'],
        parameters: [],
        enabled: true,
      },
      {
        name: 'config edit',
        category: 'configuration',
        description: 'Open config file in $EDITOR',
        handler: 'config_edit',
        aliases: [],
        parameters: [],
        enabled: true,
      },
      {
        name: 'config check',
        category: 'configuration',
        description: 'Validate configuration',
        handler: 'config_check',
        aliases: [],
        parameters: [],
        enabled: true,
      },
      {
        name: 'config debug',
        category: 'configuration',
        description: 'Show diagnostic information',
        handler: 'config_debug',
        aliases: [],
        parameters: [],
        enabled: true,
      },
      {
        name: 'image',
        category: 'workflow',
        description: 'Attach an image to your message',
        handler: 'attach_image',
        aliases: ['img'],
        parameters: [
          {
            name: 'path',
            type: 'string',
            required: true,
            description: 'Path to the image file',
          },
          {
            name: 'message',
            type: 'string',
            required: false,
            description: 'Optional message about the image',
          },
        ],
        enabled: true,
      },
    ];

    for (const command of builtins) {
      this.register(command);
    }
  }

  /**
   * Get all registered commands.
   */
  getAllCommands(): Command[] {
    return Array.from(this.commands.values());
  }

  /**
   * Get all categories.
   */
  getAllCategories(): CommandCategory[] {
    return Array.from(this.categories.values());
  }
}
