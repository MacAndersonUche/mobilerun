/**
 * Lightweight node test for hosted-URL healing (no vitest in package).
 * Run: node src/config.logic.test.mjs
 */
import assert from 'node:assert/strict';

const isUnreachableFromHosted = (url, hosted = true) => {
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (h === 'localhost' || h === '127.0.0.1' || h === '0.0.0.0') return true;
    if (h.endsWith('.local')) return true;
    if (/^192\.168\.\d+\.\d+$/.test(h)) return true;
    if (/^10\.\d+\.\d+\.\d+$/.test(h)) return true;
    if (/^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$/.test(h)) return true;
    if (u.protocol === 'http:' && hosted) return true;
    return false;
  } catch {
    return true;
  }
};

assert.equal(isUnreachableFromHosted('http://192.168.1.10:8000'), true);
assert.equal(isUnreachableFromHosted('http://macbook.local:8000'), true);
assert.equal(isUnreachableFromHosted('http://localhost:8000'), true);
assert.equal(
  isUnreachableFromHosted(
    'https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com',
  ),
  false,
);
assert.equal(
  isUnreachableFromHosted(
    'http://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com',
  ),
  true,
); // mixed content on https Netlify
console.log('config.logic.test.mjs OK');
