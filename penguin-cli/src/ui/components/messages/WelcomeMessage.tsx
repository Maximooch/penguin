/**
 * WelcomeMessage Component
 *
 * Renders the banner/welcome screen at session start.
 * Supports terminal images (iTerm2/Kitty) with fallback to ASCII art.
 * Displayed as part of Static items to ensure proper ordering.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { WelcomeLine } from '../../../core/accumulator/types.js';
import terminalImage from 'terminal-image';
import fs from 'fs';
import path from 'path';

const FIGLET_TEXT = `ooooooooo.                                                 o8o
\`888   \`Y88.                                               \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888  \`888P"Y88b
 888         888ooo888  888   888  888   888   888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o o888o o888o
                                   d"     YD
                                   "Y88888P'`;

const COMPACT_TEXT = `██████╗ ███████╗███╗   ██╗ ██████╗ ██╗   ██╗██╗███╗   ██╗
██╔══██╗██╔════╝████╗  ██║██╔════╝ ██║   ██║██║████╗  ██║
██████╔╝█████╗  ██╔██╗ ██║██║  ███╗██║   ██║██║██╔██╗ ██║
██╔═══╝ ██╔══╝  ██║╚██╗██║██║   ██║██║   ██║██║██║╚██╗██║
██║     ███████╗██║ ╚████║╚██████╔╝╚██████╔╝██║██║ ╚████║
╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝ ╚═╝╚═╝  ╚═══╝`;

// Module-level cache - load image once at module init time
let cachedImage: string | null = null;
let cachedLayout: 'side-by-side' | 'vertical' | 'compact' = 'vertical';
let imageLoadPromise: Promise<void> | null = null;

// Determine layout based on terminal width
function detectLayout(): 'side-by-side' | 'vertical' | 'compact' {
  const terminalWidth = process.stdout.columns || 80;
  if (terminalWidth >= 120) return 'side-by-side';
  if (terminalWidth >= 80) return 'vertical';
  return 'compact';
}

// Pre-load image at module init (runs once when module is imported)
async function preloadImage(): Promise<void> {
  const layout = detectLayout();
  cachedLayout = layout;

  try {
    // Try multiple possible paths for the image
    const possiblePaths = [
      path.join(process.cwd(), '..', 'context', 'image.png'),
      path.join(process.cwd(), 'context', 'image.png'),
      path.join(process.cwd(), '..', '..', 'context', 'image.png'),
    ];

    let imagePath: string | null = null;
    for (const p of possiblePaths) {
      if (fs.existsSync(p)) {
        imagePath = p;
        break;
      }
    }

    if (imagePath) {
      const imageBuffer = fs.readFileSync(imagePath);
      const imageWidth = layout === 'side-by-side' ? 30 : 40;
      const imageHeight = layout === 'side-by-side' ? 15 : 20;

      cachedImage = await terminalImage.buffer(imageBuffer, {
        width: imageWidth,
        height: imageHeight,
        preserveAspectRatio: true
      });
    }
  } catch {
    // Terminal doesn't support images, use text-only
    cachedImage = null;
  }
}

// Start loading immediately when module is imported
imageLoadPromise = preloadImage();

/**
 * Wait for the banner image to finish loading.
 * Call this before rendering the app to ensure the image is ready.
 */
export async function waitForBannerImage(): Promise<void> {
  if (imageLoadPromise) {
    await imageLoadPromise;
  }
}

interface WelcomeMessageProps {
  line: WelcomeLine;
  contentWidth?: number;
}

export function WelcomeMessage({ line, contentWidth }: WelcomeMessageProps) {
  const { theme } = useTheme();
  const layout = cachedLayout;
  const renderedImage = cachedImage;
  const imageSupported = cachedImage !== null;

  // Text-only fallback (most common case)
  if (!imageSupported || !renderedImage) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text color={theme.status.info}>{layout === 'compact' ? COMPACT_TEXT : FIGLET_TEXT}</Text>
        <Box marginTop={1}>
          <Text dimColor>
            v{line.version} • AI-Powered Development Assistant
          </Text>
        </Box>
        {line.workspace && (
          <Box marginTop={0}>
            <Text dimColor>
              📁 Workspace: <Text color={theme.status.warning}>{line.workspace}</Text>
            </Text>
          </Box>
        )}
        <Box marginTop={0}>
          <Text dimColor>
            Type <Text color={theme.status.info}>/help</Text> for commands
          </Text>
        </Box>
      </Box>
    );
  }

  // Side-by-side layout (image left, text right)
  if (layout === 'side-by-side') {
    return (
      <SideBySideBanner
        image={renderedImage}
        version={line.version}
        workspace={line.workspace}
      />
    );
  }

  // Vertical layout (text above, image below)
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={theme.status.info}>{FIGLET_TEXT}</Text>
      <Box marginTop={1}>
        <Text>{renderedImage}</Text>
      </Box>
      <Box marginTop={1}>
        <Text dimColor>
          v{line.version} • AI-Powered Development Assistant
        </Text>
      </Box>
      {line.workspace && (
        <Box marginTop={0}>
          <Text dimColor>
            📁 Workspace: <Text color={theme.status.warning}>{line.workspace}</Text>
          </Text>
        </Box>
      )}
      <Box marginTop={0}>
        <Text dimColor>
          Type <Text color={theme.status.info}>/help</Text> for commands
        </Text>
      </Box>
    </Box>
  );
}

/**
 * Side-by-side layout component
 * Image on left, text on right
 */
function SideBySideBanner({
  image,
  version,
  workspace
}: {
  image: string;
  version: string;
  workspace?: string;
}) {
  const imageLines = image.split('\n');
  const textLines = FIGLET_TEXT.split('\n');
  const maxLines = Math.max(imageLines.length, textLines.length);

  // ANSI color codes
  const cyan = '\x1b[36m';
  const yellow = '\x1b[33m';
  const dim = '\x1b[2m';
  const reset = '\x1b[0m';

  // Build the combined output
  const lines: string[] = [];

  // Render each line with image + text side by side
  for (let i = 0; i < maxLines; i++) {
    const imageLine = imageLines[i] || '';
    const textLine = textLines[i] || '';

    // Add spacing between image and text
    const spacing = '  ';
    const coloredText = textLine ? `${cyan}${textLine}${reset}` : '';

    lines.push(imageLine + spacing + coloredText);
  }

  // Add footer
  lines.push('');
  lines.push(`${dim}v${version} • AI-Powered Development Assistant${reset}`);

  if (workspace) {
    lines.push(`${dim}📁 Workspace: ${yellow}${workspace}${reset}${dim} • Type ${cyan}/help${reset}${dim} for commands${reset}`);
  } else {
    lines.push(`${dim}Type ${cyan}/help${reset}${dim} for commands${reset}`);
  }

  // Join all lines and render as a single Text component
  const combined = lines.join('\n');

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text>{combined}</Text>
    </Box>
  );
}
