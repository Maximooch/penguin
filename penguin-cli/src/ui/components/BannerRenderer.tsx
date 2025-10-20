/**
 * Banner Renderer - Adaptive Layout System
 *
 * Renders the Penguin banner with adaptive layout:
 * - Wide terminals (120+): Side-by-side (image left, text right)
 * - Narrow terminals (<120): Vertical (stacked)
 *
 * Uses terminal-image for pixel art rendering (iTerm2/Kitty)
 */

import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
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

interface BannerProps {
  version?: string;
  workspace?: string;
  forceLayout?: 'side-by-side' | 'vertical' | 'compact';
}

export function BannerRenderer({ version = '0.1.0', workspace, forceLayout }: BannerProps) {
  const [renderedImage, setRenderedImage] = useState<string | null>(null);
  const [layout, setLayout] = useState<'side-by-side' | 'vertical' | 'compact'>('vertical');
  const [imageSupported, setImageSupported] = useState(false);

  useEffect(() => {
    async function loadImage() {
      // Detect terminal capabilities
      const terminalWidth = process.stdout.columns || 80;
      const isTTY = process.stdout.isTTY;

      // Determine layout
      let chosenLayout: 'side-by-side' | 'vertical' | 'compact';
      if (forceLayout) {
        chosenLayout = forceLayout;
      } else if (terminalWidth >= 120) {
        chosenLayout = 'side-by-side';
      } else if (terminalWidth >= 80) {
        chosenLayout = 'vertical';
      } else {
        chosenLayout = 'compact';
      }
      setLayout(chosenLayout);

      // Try to load pixel art image
      try {
        const imagePath = path.join(process.cwd(), '..', 'context', 'image.png');

        if (fs.existsSync(imagePath)) {
          const imageBuffer = fs.readFileSync(imagePath);

          // Render with appropriate size based on layout
          const imageWidth = chosenLayout === 'side-by-side' ? 30 : 40;
          const imageHeight = chosenLayout === 'side-by-side' ? 15 : 20;

          const rendered = await terminalImage.buffer(imageBuffer, {
            width: imageWidth,
            height: imageHeight,
            preserveAspectRatio: true
          });

          setRenderedImage(rendered);
          setImageSupported(true);
        }
      } catch (error) {
        // Terminal doesn't support images, use text-only
        console.error('[Banner] Terminal images not supported:', error);
        setImageSupported(false);
      }
    }

    loadImage();
  }, [forceLayout]);

  // Fallback: Text-only if images not supported
  if (!imageSupported || !renderedImage) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text color="cyan">{layout === 'compact' ? COMPACT_TEXT : FIGLET_TEXT}</Text>
        <Box marginTop={1}>
          <Text dimColor>
            v{version} • AI-Powered Development Assistant
          </Text>
        </Box>
        {workspace && (
          <Box marginTop={0}>
            <Text dimColor>
              📁 Workspace: <Text color="yellow">{workspace}</Text>
            </Text>
          </Box>
        )}
        <Box marginTop={1}>
          <Text dimColor>
            Type <Text color="cyan">/help</Text> for commands • <Text color="cyan">/init</Text> to get started
          </Text>
        </Box>
      </Box>
    );
  }

  // Side-by-side layout (image left, text right)
  if (layout === 'side-by-side') {
    return <SideBySideBanner image={renderedImage} version={version} workspace={workspace} />;
  }

  // Vertical layout (text above, image below)
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color="cyan">{FIGLET_TEXT}</Text>
      <Box marginTop={1}>
        <Text>{renderedImage}</Text>
      </Box>
      <Box marginTop={1}>
        <Text dimColor>
          v{version} • AI-Powered Development Assistant
        </Text>
      </Box>
      {workspace && (
        <Box marginTop={0}>
          <Text dimColor>
            📁 Workspace: <Text color="yellow">{workspace}</Text>
          </Text>
        </Box>
      )}
      <Box marginTop={1}>
        <Text dimColor>
          Type <Text color="cyan">/help</Text> for commands • <Text color="cyan">/init</Text> to get started
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

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Render line by line */}
      {Array.from({ length: maxLines }).map((_, i) => {
        const imageLine = imageLines[i] || '';
        const textLine = textLines[i] || '';

        return (
          <Box key={i}>
            <Text>{imageLine}</Text>
            <Text color="cyan">{textLine ? `  ${textLine}` : ''}</Text>
          </Box>
        );
      })}

      {/* Footer */}
      <Box marginTop={1}>
        <Text dimColor>
          v{version} • AI-Powered Development Assistant
        </Text>
      </Box>
      {workspace && (
        <Box marginTop={0}>
          <Text dimColor>
            📁 Workspace: <Text color="yellow">{workspace}</Text> • Type <Text color="cyan">/help</Text> for commands
          </Text>
        </Box>
      )}
    </Box>
  );
}
