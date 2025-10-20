#!/usr/bin/env node
/**
 * Demo: Side-by-Side Layout
 *
 * Shows the figlet text NEXT TO the penguin image (not above/below)
 * This creates a more compact, horizontal banner
 *
 * Run: node demos/demo-side-by-side.js
 */

import terminalImage from 'terminal-image';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const FIGLET_TEXT = `ooooooooo.                                                 o8o
\`888   \`Y88.                                               \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888  \`888P"Y88b
 888         888ooo888  888   888  888   888   888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o o888o o888o
                                   d"     YD
                                   "Y88888P'`;

function splitIntoLines(text) {
  return text.split('\n');
}

function padRight(str, width) {
  return str + ' '.repeat(Math.max(0, width - str.length));
}

async function main() {
  console.clear();

  console.log('\n╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║                   Side-by-Side Layout Demo                            ║');
  console.log('║                Text NEXT TO Image (Horizontal)                        ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝\n');

  const imagePath = path.join(__dirname, '../../context/image.png');

  if (!fs.existsSync(imagePath)) {
    console.error('❌ image.png not found');
    process.exit(1);
  }

  try {
    // Render the image smaller for side-by-side
    const imageBuffer = fs.readFileSync(imagePath);
    const imageRendered = await terminalImage.buffer(imageBuffer, {
      width: 30,  // Smaller width to fit next to text
      height: 15,
      preserveAspectRatio: true
    });

    const imageLines = splitIntoLines(imageRendered);
    const textLines = splitIntoLines(FIGLET_TEXT);

    // Get terminal width (default to 120 if not available)
    const terminalWidth = process.stdout.columns || 120;

    console.log('LAYOUT OPTION 1: Text on Left, Image on Right\n');
    console.log('─'.repeat(terminalWidth));

    // Calculate layout
    const textWidth = 70;
    const gap = 2;
    const maxLines = Math.max(textLines.length, imageLines.length);

    for (let i = 0; i < maxLines; i++) {
      const textLine = textLines[i] || '';
      const imageLine = imageLines[i] || '';

      // Pad text to fixed width, add gap, then image
      const paddedText = padRight(textLine, textWidth);
      const gapSpace = ' '.repeat(gap);

      console.log('\x1b[36m' + paddedText + '\x1b[0m' + gapSpace + imageLine);
    }

    console.log('─'.repeat(terminalWidth));
    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli • Type /help for commands\n');

    console.log('📊 Metrics:');
    console.log('  • Total height: ~' + maxLines + ' lines (vs ~29 for vertical)');
    console.log('  • Total width: ~' + (textWidth + gap + 30) + ' chars');
    console.log('  • Best for: Wide terminals (120+ columns)\n');

    // Now show alternative: Image on left
    console.log('\n' + '═'.repeat(terminalWidth));
    console.log('\nLAYOUT OPTION 2: Image on Left, Text on Right\n');
    console.log('─'.repeat(terminalWidth));

    const imageWidth = 32; // Approximate width of rendered image

    for (let i = 0; i < maxLines; i++) {
      const imageLine = imageLines[i] || ' '.repeat(imageWidth);
      const textLine = textLines[i] || '';
      const gapSpace = ' '.repeat(gap);

      console.log(imageLine + gapSpace + '\x1b[36m' + textLine + '\x1b[0m');
    }

    console.log('─'.repeat(terminalWidth));
    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli • Type /help for commands\n');

    console.log('📊 Metrics:');
    console.log('  • Total height: ~' + maxLines + ' lines');
    console.log('  • Visual balance: Image draws eye first');
    console.log('  • Best for: Wide terminals (120+ columns)\n');

    // Show compact vertical for comparison
    console.log('\n' + '═'.repeat(terminalWidth));
    console.log('\nCOMPARISON: Original Vertical Layout\n');
    console.log('─'.repeat(terminalWidth));

    console.log('\x1b[36m' + FIGLET_TEXT + '\x1b[0m');
    console.log('\n' + imageRendered);
    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli\n');

    console.log('📊 Metrics:');
    console.log('  • Total height: ~27 lines');
    console.log('  • Total width: ~70 chars');
    console.log('  • Best for: Narrow terminals (80-100 columns)\n');

    // Recommendations
    console.log('\n' + '═'.repeat(terminalWidth));
    console.log('💡 RECOMMENDATIONS\n');
    console.log('Use SIDE-BY-SIDE if:');
    console.log('  ✓ Terminal is 120+ columns wide');
    console.log('  ✓ User has large screen / wide terminal');
    console.log('  ✓ Want to save vertical space\n');

    console.log('Use VERTICAL (stacked) if:');
    console.log('  ✓ Terminal is <100 columns');
    console.log('  ✓ User has split panes / small screen');
    console.log('  ✓ Better mobile/narrow support\n');

    console.log('SMART APPROACH:');
    console.log('  → Detect terminal width');
    console.log('  → If width >= 120: Use side-by-side');
    console.log('  → If width < 120: Use vertical');
    console.log('  → Best of both worlds! 🎯\n');

  } catch (error) {
    console.error('\n❌ Error:', error.message);
  }
}

main().catch(console.error);
