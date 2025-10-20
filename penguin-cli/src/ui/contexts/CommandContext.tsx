/**
 * Command Context for Penguin Ink CLI
 *
 * Provides command registry and execution to React components.
 */

import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { CommandRegistry } from '../../core/commands/CommandRegistry.js';
import type { ParsedCommand, CommandHandler } from '../../core/commands/types.js';

interface CommandContextValue {
  registry: CommandRegistry;
  parseInput: (input: string) => ParsedCommand | null;
  getSuggestions: (partial: string) => string[];
  getHelpText: () => string;
  execute: (commandName: string, args: Record<string, any>, context?: any) => Promise<void>;
  registerHandler: (handlerName: string, handler: CommandHandler) => void;
}

const CommandContext = createContext<CommandContextValue | null>(null);

interface CommandProviderProps {
  children: ReactNode;
  configPath?: string;
}

export function CommandProvider({ children, configPath }: CommandProviderProps) {
  const [registry] = useState(() => new CommandRegistry(configPath));

  const contextValue: CommandContextValue = {
    registry,
    parseInput: (input: string) => registry.parseInput(input),
    getSuggestions: (partial: string) => registry.getSuggestions(partial),
    getHelpText: () => registry.getHelpText(),
    execute: (commandName: string, args: Record<string, any>, context?: any) =>
      registry.execute(commandName, args, context),
    registerHandler: (handlerName: string, handler: CommandHandler) =>
      registry.registerHandler(handlerName, handler),
  };

  return <CommandContext.Provider value={contextValue}>{children}</CommandContext.Provider>;
}

export function useCommand() {
  const context = useContext(CommandContext);
  if (!context) {
    throw new Error('useCommand must be used within CommandProvider');
  }
  return context;
}
