/**
 * Command System Types for Penguin Ink CLI
 *
 * Mirrors the Python command_registry.py architecture.
 */

export interface CommandParameter {
  name: string;
  type: 'string' | 'int' | 'bool';
  required: boolean;
  description: string;
  default?: any;
}

export interface Command {
  name: string;
  category: string;
  description: string;
  handler: string;
  aliases: string[];
  parameters: CommandParameter[];
  enabled: boolean;
}

export interface CommandCategory {
  name: string;
  description: string;
  icon: string;
}

export interface CommandConfig {
  version: string;
  categories: CommandCategory[];
  commands: Command[];
}

export interface ParsedCommand {
  command: Command;
  args: Record<string, any>;
}

export type CommandHandler = (args: Record<string, any>, context?: any) => void | Promise<void>;

export interface CommandHandlers {
  [handlerName: string]: CommandHandler;
}
