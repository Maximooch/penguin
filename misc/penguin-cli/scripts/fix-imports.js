#!/usr/bin/env node
/**
 * Post-build script to add .js extensions to relative imports for ESM compatibility
 */

import { readdir, readFile, writeFile } from 'fs/promises';
import { join, dirname, extname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = join(__dirname, '..', 'dist');

async function fixImportsInFile(filePath) {
  const content = await readFile(filePath, 'utf-8');

  // Match relative imports that don't have extensions
  const fixed = content.replace(
    /from\s+['"](\.[^'"]*)['"]/g,
    (match, importPath) => {
      // Skip if already has extension
      if (extname(importPath)) {
        return match;
      }
      // Add .js extension
      return match.replace(importPath, `${importPath}.js`);
    }
  );

  if (fixed !== content) {
    await writeFile(filePath, fixed, 'utf-8');
    console.log(`Fixed imports in: ${filePath}`);
  }
}

async function processDirectory(dir) {
  const entries = await readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      await processDirectory(fullPath);
    } else if (entry.isFile() && (entry.name.endsWith('.js') || entry.name.endsWith('.mjs'))) {
      await fixImportsInFile(fullPath);
    }
  }
}

async function main() {
  console.log('Fixing ESM imports in dist/...');
  await processDirectory(distDir);
  console.log('Done!');
}

main().catch(console.error);
