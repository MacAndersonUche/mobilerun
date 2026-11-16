/**
 * Run: node src/lib/pairingLinks.test.mjs
 */
import assert from 'node:assert/strict';

const MOBILERUN_PACKAGE = 'ai.mobilerun.selfhosted';

function buildDeepLink(token) {
  return `mobilerun://pair?c=${encodeURIComponent(token)}`;
}

function buildIntentUrl({ token, httpsFallback, packageName }) {
  const pkg = packageName || MOBILERUN_PACKAGE;
  const fallback = encodeURIComponent(httpsFallback);
  return (
    `intent://pair?c=${encodeURIComponent(token)}` +
    `#Intent;scheme=mobilerun;package=${pkg};` +
    `S.browser_fallback_url=${fallback};end`
  );
}

function shortHttpsLink(code) {
  return `https://macsmobilerun.netlify.app/p/${encodeURIComponent(code)}`;
}

const token = 'AB3K7Q2M';
assert.equal(buildDeepLink(token), `mobilerun://pair?c=${encodeURIComponent(token)}`);
assert.equal(shortHttpsLink(token), `https://macsmobilerun.netlify.app/p/${token}`);
const https = shortHttpsLink(token);
const intent = buildIntentUrl({ token, httpsFallback: https });
assert.ok(intent.startsWith('intent://pair?c='));
assert.ok(intent.includes('package=ai.mobilerun.selfhosted'));
assert.ok(https.length < 60, `short link too long: ${https.length}`);
console.log('pairingLinks.test.mjs OK');
