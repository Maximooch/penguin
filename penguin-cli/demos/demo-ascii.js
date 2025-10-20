#!/usr/bin/env node
/**
 * Demo 2: Colored ASCII Art Conversion
 *
 * Converts the pixel art penguin to colored ASCII
 * Works in ANY terminal!
 *
 * Run: node demos/demo-ascii.js
 */

import asciify from 'asciify-image';
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
  console.log('║               DEMO 2: Colored ASCII Art (Universal)                   ║');
  console.log('║                    Works in ALL terminals!                            ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝\n');

  const imagePath = path.join(__dirname, '../../context/image.png');

  console.log('🎨 Converting pixel art to colored ASCII...\n');

  try {
    // Option 2: Just the ASCII penguin
    console.log('OPTION 2: ASCII Art Only\n');
    console.log('─'.repeat(70) + '\n');

    const asciiArt = await asciify(imagePath, {
      fit: 'width',
      width: 50,
      format: 'array',
      color: true
    });

    console.log(asciiArt.join('\n'));

    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli');
    console.log('Type /help for commands • /init to get started\n');

    console.log('─'.repeat(70));
    console.log('\n✅ This is Option 2 (colored ASCII art)');
    console.log('📏 Height: ~25-30 lines (depends on image)');
    console.log('🎨 256-color ANSI codes (cyan → blue → pink gradient)');
    console.log('⚡ Instant rendering (<10ms)\n');

    // Option 3B: Hybrid layout
    console.log('\n' + '═'.repeat(70));
    console.log('\nOPTION 3B: Hybrid Layout (Text + ASCII Art)\n');
    console.log('─'.repeat(70) + '\n');

    console.log('\x1b[36m' + FIGLET_TEXT + '\x1b[0m');

    // Compact ASCII for hybrid
    const compactAscii = await asciify(imagePath, {
      fit: 'width',
      width: 35,
      format: 'array',
      color: true
    });

    console.log('\n' + compactAscii.join('\n'));

    console.log('\nv0.1.0 • AI-Powered Development Assistant');
    console.log('📁 Workspace: penguin-cli • Type /help for commands\n');

    console.log('─'.repeat(70));
    console.log('\n✅ This is Option 3B (figlet text + ASCII penguin)');
    console.log('📏 Total height: ~27 lines');
    console.log('🌍 Universal terminal support!');
    console.log('💡 RECOMMENDED as default banner\n');

  } catch (error) {
    console.error('\n❌ Error converting image:', error.message);
    console.error('\nMake sure context/image.png exists and is a valid PNG file.\n');
  }
}

main().catch(console.error);
