#!/usr/bin/env node
/**
 * Demo 1: Terminal-Image (iTerm2/Kitty)
 *
 * Shows the pixel art penguin using terminal-image
 * Full colors, true image rendering
 *
 * Run: node demos/demo-terminal-image.js
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

async function main() {
  console.clear();

  console.log('\n╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║                 DEMO 1: Terminal-Image (Pixel Art)                    ║');
  console.log('║                      Requires: iTerm2, Kitty, WezTerm                 ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝\n');

  const imagePath = path.join(__dirname, '../../context/image.png');

  if (!fs.existsSync(imagePath)) {
    console.error('❌ Error: image.png not found at:', imagePath);
    console.error('Please ensure context/image.png exists');
    process.exit(1);
  }

  try {
    // Show the actual pixel art
    const imageBuffer = fs.readFileSync(imagePath);

    console.log('🎨 Rendering pixel art penguin with full colors...\n');

    const rendered = await terminalImage.buffer(imageBuffer, {
      width: 40,
      height: 20,
      preserveAspectRatio: true
    });

    console.log(rendered);

    console.log('\n' + '─'.repeat(70));
    console.log('\n✨ That\'s the actual image with vaporwave gradients!');
    console.log('This only works in iTerm2, Kitty, and WezTerm.\n');

    // Now show hybrid layout
    console.log('\n' + '═'.repeat(70));
    console.log('\nOPTION 3A: Hybrid Layout (Text + Pixel Art)\n');
    console.log('─'.repeat(70) + '\n');

    console.log('\x1b[36m' + FIGLET_TEXT + '\x1b[0m');
    console.log('\n' + rendered);

    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli');
    console.log('Type /help for commands • /init to get started\n');

    console.log('─'.repeat(70));
    console.log('\n✅ This is Option 1 (pixel art only) + Option 3A (hybrid)');
    console.log('📏 Total height: ~29 lines');
    console.log('🎨 Full vaporwave gradient colors preserved!\n');

  } catch (error) {
    console.error('\n❌ Error rendering image:', error.message);
    console.error('\nThis might mean:');
    console.error('  1. Your terminal doesn\'t support images (use iTerm2 or Kitty)');
    console.error('  2. The image file is corrupted');
    console.error('  3. Terminal inline images are disabled\n');
    console.error('Try running demos/demo-ascii.js instead for universal support!\n');
  }
}

main().catch(console.error);
