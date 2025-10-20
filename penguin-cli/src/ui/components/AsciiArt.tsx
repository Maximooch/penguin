/**
 * ASCII Art Banner for Penguin CLI
 *
 * Features multiple ASCII art styles for branding
 */

import React from 'react';
import { Box, Text } from 'ink';

// The classic Penguin text logo (using figlet-style font)
const PENGUIN_TEXT = `ooooooooo.                                                 o8o
\`888   \`Y88.                                               \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888  \`888P"Y88b
 888         888ooo888  888   888  888   888   888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o o888o o888o
                                   d"     YD
                                   "Y88888P'`;

// The detailed penguin ASCII art
const PENGUIN_BIRD = `                               ████████
                      ▓████████████████░░
                           ▒▒▒▒▒▓██████░▒▓
                               ████████▓▓▒▒
                                ██████▒░▒▒▒▒
                               ░░▒▒▒▒░░░░▒▒▒
                                  ░ ░ ▓▓▒░░░░
                                        ██▒░░░
                                         ███▓▒░
                                          ██▓▒▒░
                                           ██▓▓▓▒
                                           ░█▓██▒▓
                            ░                █▓██▓
                            ░░░              ▒████▒
                             ░░              ░░████▒
                            █░░░             ░░░▒███
                            █░░░░░            ░░▒▓██▓
                           ██▒░░░░░           ░░░▒▒▓█▓
                           ██▓░░░░            ░░░░ ▓██
                           ███░░░░░           ░░░░░▓█▓▓
                           ▓██░░░░░░          ░░░░░▓█ █▓
                            ███░░░░░          ░░░░▒▓▓  █
                            ███░░░░░░░         ░░░░▓█   ▓
                             ███░░░░   ░       ░░░ ▓█   ▓▓
                               █░░░░░ ░░░      ░░░ ░▓    █
                                ░░░░░░░ ░      ░░░  ▓     █
                                 ░░░░░░░░░ ░  ░░░░  ▓      █
                                 ░░░░░░░░░░░░░░░░░░▓▓
                                   ░▒▒░░░░░░░░░░░░░█▓
                                  ░░░░▒▒▒▒▒░░░░░░░░▓
                                 ░ ░░░░░░▒▒▒▒░░░░░░▓
                                 ░▒▒▒░▒▒▒▒▒▓▓▓░░░░▓█
                                ░▓████░       ▒▒░░██▒
                               ▓█████         ▒██████
                      ▓█████▓██▓████         ▓████▒███
                       ███▓███████░  ░███████████`;

// Compact version for smaller terminals
const PENGUIN_COMPACT = `██████╗ ███████╗███╗   ██╗ ██████╗ ██╗   ██╗██╗███╗   ██╗
██╔══██╗██╔════╝████╗  ██║██╔════╝ ██║   ██║██║████╗  ██║
██████╔╝█████╗  ██╔██╗ ██║██║  ███╗██║   ██║██║██╔██╗ ██║
██╔═══╝ ██╔══╝  ██║╚██╗██║██║   ██║██║   ██║██║██║╚██╗██║
██║     ███████╗██║ ╚████║╚██████╔╝╚██████╔╝██║██║ ╚████║
╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝ ╚═╝╚═╝  ╚═══╝`;

// Minimalist penguin emoji style
const PENGUIN_EMOJI = `
   🐧
 P E N G U I N
   A I
`;

export type AsciiArtStyle = 'full' | 'compact' | 'bird' | 'emoji' | 'minimal';

interface AsciiArtProps {
  style?: AsciiArtStyle;
  color?: string;
  showVersion?: boolean;
  version?: string;
}

export function AsciiArt({ style = 'full', color = 'cyan', showVersion = true, version = '0.1.0' }: AsciiArtProps) {
  const getArt = () => {
    switch (style) {
      case 'bird':
        return PENGUIN_BIRD;
      case 'compact':
        return PENGUIN_COMPACT;
      case 'emoji':
        return PENGUIN_EMOJI;
      case 'minimal':
        return '🐧 Penguin AI';
      case 'full':
      default:
        return PENGUIN_TEXT;
    }
  };

  const art = getArt();

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={color}>{art}</Text>
      {showVersion && style !== 'emoji' && (
        <Box marginTop={1}>
          <Text dimColor>
            {' '}v{version} • TypeScript CLI (Ink)
          </Text>
        </Box>
      )}
    </Box>
  );
}

/**
 * Full banner with text + bird combo
 */
export function PenguinBanner({ version = '0.1.0' }: { version?: string }) {
  return (
    <Box flexDirection="column">
      {/* Text logo */}
      <Box>
        <Text color="cyan">{PENGUIN_TEXT}</Text>
      </Box>

      {/* Bird art */}
      <Box marginTop={1} marginLeft={40}>
        <Text color="cyan">{PENGUIN_BIRD}</Text>
      </Box>

      {/* Version footer */}
      <Box marginTop={1}>
        <Text dimColor>
          v{version} • AI-Powered Development Assistant • Type /help for commands
        </Text>
      </Box>
    </Box>
  );
}

/**
 * Startup banner - used on CLI initialization
 */
export function StartupBanner({
  version = '0.1.0',
  workspace,
  compact = false
}: {
  version?: string;
  workspace?: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text color="cyan" bold>🐧 Penguin AI v{version}</Text>
        {workspace && (
          <Text dimColor>Workspace: {workspace}</Text>
        )}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* ASCII art */}
      <AsciiArt style="compact" color="cyan" showVersion={false} />

      {/* Info line */}
      <Box marginTop={1}>
        <Text dimColor>
          v{version} • AI-Powered Development Assistant
        </Text>
      </Box>

      {/* Workspace */}
      {workspace && (
        <Box marginTop={0}>
          <Text dimColor>
            📁 Workspace: <Text color="yellow">{workspace}</Text>
          </Text>
        </Box>
      )}

      {/* Quick help */}
      <Box marginTop={1}>
        <Text dimColor>
          Type <Text color="cyan">/help</Text> for commands • <Text color="cyan">/init</Text> to get started
        </Text>
      </Box>
    </Box>
  );
}
