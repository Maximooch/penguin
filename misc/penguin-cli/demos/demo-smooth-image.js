#!/usr/bin/env node
/**
 * Demo: Smooth Image Rendering
 *
 * This shows what terminal-image looks like with a high-resolution,
 * non-pixelated image for comparison.
 *
 * Since we don't have a smooth penguin image, this demo shows:
 * 1. How to render a smooth gradient
 * 2. What the difference would look like
 * 3. How to create a smooth ASCII penguin
 */

import terminalImage from 'terminal-image';
import { createCanvas } from '@napi-rs/canvas';

const FIGLET_TEXT = `ooooooooo.                                                 o8o
\`888   \`Y88.                                               \`"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.
 888ooo88P'  d88' \`88b \`888P"Y88b  888' \`88b  \`888  \`888  \`888  \`888P"Y88b
 888         888ooo888  888   888  888   888   888   888   888   888   888
 888         888    .o  888   888  \`88bod8P'   888   888   888   888   888
o888o        \`Y8bod8P' o888o o888o \`8oooooo.   \`V88V"V8P' o888o o888o o888o
                                   d"     YD
                                   "Y88888P'`;

async function createSmoothPenguinGradient() {
  // Create a canvas with smooth vaporwave gradient
  const canvas = createCanvas(400, 300);
  const ctx = canvas.getContext('2d');

  // Create smooth gradient (cyan -> purple -> pink -> orange)
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, '#00CED1');    // Cyan
  gradient.addColorStop(0.3, '#4B0082');  // Indigo
  gradient.addColorStop(0.6, '#FF1493');  // Deep Pink
  gradient.addColorStop(1, '#FFA500');    // Orange

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 400, 300);

  // Draw a smooth penguin silhouette
  ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
  ctx.beginPath();

  // Penguin body (smooth curves)
  ctx.ellipse(200, 180, 60, 80, 0, 0, Math.PI * 2);

  // Head
  ctx.ellipse(200, 100, 40, 45, 0, 0, Math.PI * 2);

  // Belly (white)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
  ctx.ellipse(200, 180, 35, 60, 0, 0, Math.PI * 2);

  // Eyes
  ctx.fillStyle = 'white';
  ctx.ellipse(185, 95, 8, 10, 0, 0, Math.PI * 2);
  ctx.ellipse(215, 95, 8, 10, 0, 0, Math.PI * 2);

  ctx.fillStyle = 'black';
  ctx.ellipse(187, 97, 4, 5, 0, 0, Math.PI * 2);
  ctx.ellipse(217, 97, 4, 5, 0, 0, Math.PI * 2);

  // Beak
  ctx.fillStyle = '#FFA500';
  ctx.beginPath();
  ctx.moveTo(200, 105);
  ctx.lineTo(210, 115);
  ctx.lineTo(190, 115);
  ctx.closePath();
  ctx.fill();

  // Flippers
  ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
  ctx.ellipse(150, 160, 15, 50, -0.3, 0, Math.PI * 2);
  ctx.ellipse(250, 160, 15, 50, 0.3, 0, Math.PI * 2);

  // Feet
  ctx.fillStyle = '#FFA500';
  ctx.ellipse(180, 250, 20, 12, 0, 0, Math.PI * 2);
  ctx.ellipse(220, 250, 20, 12, 0, 0, Math.PI * 2);

  ctx.fill();

  return canvas.toBuffer('image/png');
}

async function main() {
  console.clear();

  console.log('\n╔════════════════════════════════════════════════════════════════════════╗');
  console.log('║              DEMO: Smooth vs Pixelated Comparison                     ║');
  console.log('╚════════════════════════════════════════════════════════════════════════╝\n');

  console.log('🎨 Creating smooth vaporwave penguin with gradients...\n');

  try {
    const smoothImage = await createSmoothPenguinGradient();

    const rendered = await terminalImage.buffer(smoothImage, {
      width: 40,
      height: 20,
      preserveAspectRatio: true
    });

    console.log('SMOOTH VERSION (Generated):\n');
    console.log(rendered);

    console.log('\n' + '─'.repeat(70));
    console.log('\n✨ Comparison:\n');
    console.log('PIXEL ART (Original):');
    console.log('  • Intentional pixelation (retro aesthetic)');
    console.log('  • Blocky edges, visible pixels');
    console.log('  • 8-bit / 16-bit style');
    console.log('  • Perfect for retro/vaporwave vibe\n');

    console.log('SMOOTH VERSION (What you asked about):');
    console.log('  • Soft gradients, no visible pixels');
    console.log('  • Anti-aliased edges');
    console.log('  • Modern, photographic look');
    console.log('  • Better for realistic images\n');

    console.log('─'.repeat(70));
    console.log('\n💡 For Penguin CLI Banner:\n');
    console.log('The PIXEL ART version is actually better because:');
    console.log('  1. It matches the vaporwave aesthetic perfectly');
    console.log('  2. Retro pixel art = coding/terminal nostalgia');
    console.log('  3. The blocky style is intentional and looks great');
    console.log('  4. More personality than a smooth photo\n');

    console.log('If you want smooth, you could:');
    console.log('  • Find a high-res penguin photo');
    console.log('  • Commission smooth vector artwork');
    console.log('  • Use an AI image generator (DALL-E, Midjourney)');
    console.log('  • Keep the pixel art (it looks awesome!)\n');

  } catch (error) {
    console.error('\n❌ Error:', error.message);
    console.error('\nNote: This demo requires @napi-rs/canvas');
    console.error('Run: npm install @napi-rs/canvas\n');
  }
}

main().catch(console.error);
