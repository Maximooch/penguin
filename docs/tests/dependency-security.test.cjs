const assert = require('node:assert/strict');
const test = require('node:test');
const braces = require('braces');
const CachePolicy = require('http-cache-semantics');
test('deep brace patterns are rejected before recursive traversal', () => {
  for (const fn of [braces, braces.parse, braces.compile, braces.expand, braces.stringify]) {
    assert.throws(() => fn('{'.repeat(1000) + 'a,b' + '}'.repeat(1000)), /security limit/);
    assert.throws(() => fn('('.repeat(1000) + 'a' + ')'.repeat(1000)), /security limit/);
  }
  assert.deepEqual(braces.expand('a/{b,c}'), ['a/b', 'a/c']);
});
test('max-stale cannot reuse security-zeroed responses in shared caches', () => {
  for (const control of ['private', 'no-store', 'max-age=3600', 'no-cache']) {
    const req = {url: '/account', method: 'GET', headers: {}};
    const policy = new CachePolicy(req, {status: 200, headers: {
      'cache-control': control, 'set-cookie': 'session=secret',
    }});
    const incoming = {...req, headers: {'cache-control': 'max-stale=999999'}};
    assert.equal(policy.satisfiesWithoutRevalidation(incoming), false);
    assert.equal(policy.evaluateRequest(incoming).response, undefined);
  }
});
test('ordinary public cache responses still work', () => {
  const req = {url: '/public', method: 'GET', headers: {}};
  const policy = new CachePolicy(req, {status: 200, headers: {'cache-control': 'public, max-age=3600'}});
  assert.equal(policy.satisfiesWithoutRevalidation(req), true);
});
