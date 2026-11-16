/**
 * Run: node src/lib/pairingLinks.test.mjs
 */
import assert from 'node:assert/strict';

const MOBILERUN_PACKAGE = 'ai.mobilerun.selfhosted';

function buildDeepLink(token) {
  return `mobilerun://pair?token=${encodeURIComponent(token)}`;
}

function buildIntentUrl({ token, httpsFallback, packageName }) {
  const pkg = packageName || MOBILERUN_PACKAGE;
  const fallback = encodeURIComponent(httpsFallback);
  return (
    `intent://pair?token=${encodeURIComponent(token)}` +
    `#Intent;scheme=mobilerun;package=${pkg};` +
    `S.browser_fallback_url=${fallback};end`
  );
}

const token = 'abc_TOKEN-123';
assert.equal(buildDeepLink(token), `mobilerun://pair?token=${encodeURIComponent(token)}`);
const https = `https://macsmobilerun.netlify.app/pair?token=${token}`;
const intent = buildIntentUrl({ token, httpsFallback: https });
assert.ok(intent.startsWith('intent://pair?token='));
assert.ok(intent.includes(`package=${MOBILERUN_PACKAGE}`));
assert.ok(intent.includes('scheme=mobilerun'));
assert.ok(intent.includes(encodeURIComponent(https)));
console.log('pairingLinks.test.mjs ok');
