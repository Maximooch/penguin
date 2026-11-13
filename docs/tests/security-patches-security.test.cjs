const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../scripts/security-patches.cjs'), 'utf8');
const prefix = '        this._assertRequestHasHeaders(req);\n\n';
const comment = '        // GHSA-ch52-4w7c-c8xp: never reuse a non-storable response.\n';
const oldGuard = '        if (!this.storable() || this.maxAge() === 0) return this._evaluateRequestMissResult(req);\n\n';
const currentGuard = "        if (!this.storable() || this.maxAge() === 0 || (this._isShared && this._rescc['s-maxage'] !== undefined && this.stale())) return this._evaluateRequestMissResult(req);\n\n";
const suffix = '        // In all circumstances';
function fixture(source) {
  const files = {
    'http-cache-semantics/index.js': source,
    'braces/lib/parse.js': '    block = stack[stack.length - 1];\n    value = advance();',
  };
  let writes = 0;
  const require = () => ({
    readFileSync: (name) => files[name],
    writeFileSync: (name, value) => { files[name] = value; writes++; },
  });
  require.resolve = (name) => name;
  return {files, run: () => vm.runInNewContext(script, {require}), writes: () => writes};
}
for (const [name, source] of [
  ['pristine', prefix + suffix],
  ['previously patched Vercel cache', prefix + comment + oldGuard + suffix],
]) {
  test(`patches ${name} and remains idempotent`, () => {
    const state = fixture(source);
    state.run();
    assert.equal(state.files['http-cache-semantics/index.js'], prefix + comment + currentGuard + suffix);
    const writes = state.writes();
    state.run();
    assert.equal(state.writes(), writes);
  });
}
test('unexpected upstream source fails closed without writing', () => {
  const state = fixture('unexpected upstream source');
  assert.throws(state.run, /Review security patch: http-cache-semantics/);
  assert.equal(state.writes(), 0);
});
