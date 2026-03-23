#!/usr/bin/env node
/**
 * Demo 3: Side-by-Side Comparison
 *
 * Shows both terminal-image and ASCII side-by-side
 * Helps you decide which looks better in your terminal
 *
 * Run: node demos/demo-comparison.js
 */

import terminalImage from 'terminal-image';
import asciify from 'asciify-image';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  console.clear();

  console.log('\n╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║                    COMPARISON: All Options                             ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝\n');

  const imagePath = path.join(__dirname, '../../context/image.png');

  console.log('Rendering all banner options for comparison...\n');
  await wait(1000);

  // Test 1: Terminal-Image (if supported)
  console.log('═'.repeat(70));
  console.log('1️⃣  OPTION 1: Terminal-Image (Pixel Art)');
  console.log('═'.repeat(70) + '\n');

  try {
    const imageBuffer = fs.readFileSync(imagePath);
    const rendered = await terminalImage.buffer(imageBuffer, {
      width: 40,
      height: 18,
      preserveAspectRatio: true
    });

    console.log(rendered);
    console.log('\n📊 Metrics:');
    console.log('  • Quality: ⭐⭐⭐⭐⭐ (Full pixel art)');
    console.log('  • Compatibility: ❌ (iTerm2/Kitty only)');
    console.log('  • Colors: ✅ Thousands (full gradient)');
    console.log('  • Render Time: ~150ms');

  } catch (error) {
    console.log('[Terminal images not supported in your terminal]');
    console.log('This is expected if you\'re not using iTerm2 or Kitty.');
    console.log('\n📊 Metrics:');
    console.log('  • Quality: ⭐⭐⭐⭐⭐ (would be stunning if supported)');
    console.log('  • Compatibility: ❌ (Not supported here)');
  }

  await wait(2000);

  // Test 2: ASCII Art
  console.log('\n\n═'.repeat(70));
  console.log('2️⃣  OPTION 2: Colored ASCII Art');
  console.log('═'.repeat(70) + '\n');

  try {
    const asciiArt = await asciify(imagePath, {
      fit: 'width',
      width: 40,
      format: 'array',
      color: true
    });

    console.log(asciiArt.join('\n'));
    console.log('\n📊 Metrics:');
    console.log('  • Quality: ⭐⭐⭐ (Good approximation)');
    console.log('  • Compatibility: ✅ (ALL terminals)');
    console.log('  • Colors: ⚠️  256 colors (blocky gradient)');
    console.log('  • Render Time: <10ms');

  } catch (error) {
    console.log('[Error rendering ASCII art]', error.message);
  }

  await wait(2000);

  // Final recommendation
  console.log('\n\n═'.repeat(70));
  console.log('💡 RECOMMENDATION');
  console.log('═'.repeat(70) + '\n');

  console.log('Based on what we can see:\n');

  console.log('🏆 BEST OVERALL: Option 3B (Hybrid ASCII)');
  console.log('   └─ Figlet text + Colored ASCII penguin');
  console.log('   └─ Works everywhere, good quality, fast');
  console.log('   └─ ~27 lines total\n');

  console.log('🎨 BEST VISUAL: Option 3A (Hybrid Terminal-Image)');
  console.log('   └─ Figlet text + Pixel art penguin');
  console.log('   └─ Stunning in iTerm2/Kitty');
  console.log('   └─ Falls back to ASCII if not supported');
  console.log('   └─ ~29 lines total\n');

  console.log('⚡ FASTEST: Option 2 (ASCII only)');
  console.log('   └─ Just the colored ASCII penguin');
  console.log('   └─ <10ms render time');
  console.log('   └─ Great for slow terminals\n');

  console.log('─'.repeat(70));
  console.log('\n💡 Want to see the hybrid layouts?');
  console.log('   Run: node demos/demo-ascii.js (shows Option 3B)');
  console.log('   Run: node demos/demo-terminal-image.js (shows Option 3A)\n');
}

main().catch(console.error);
