// Temporary fail-closed mitigations for advisories without an upstream release.
// Refuse unexpected source instead of silently leaving an install unprotected.
const fs = require('node:fs');
function patch(name, file, before, after) {
  const filename = require.resolve(`${name}/${file}`);
  const source = fs.readFileSync(filename, 'utf8');
  if (source.includes(after)) return;
  if (!source.includes(before)) throw new Error(`Review security patch: ${name}/${file}`);
  fs.writeFileSync(filename, source.replace(before, after));
}
patch('http-cache-semantics', 'index.js',
  '        this._assertRequestHasHeaders(req);\n\n        // In all circumstances',
  '        this._assertRequestHasHeaders(req);\n\n        // GHSA-ch52-4w7c-c8xp: never reuse a non-storable response.\n        if (!this.storable() || this.maxAge() === 0) return this._evaluateRequestMissResult(req);\n\n        // In all circumstances');
patch('braces', 'lib/parse.js',
  '    block = stack[stack.length - 1];\n    value = advance();',
  '    // GHSA-vfj7-8cjw-p6xm: bound AST depth before recursive walkers run.\n    if (stack.length > 100) throw new SyntaxError("Brace nesting exceeds security limit");\n    block = stack[stack.length - 1];\n    value = advance();');
