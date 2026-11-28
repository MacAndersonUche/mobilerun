/**
 * Run: node --experimental-strip-types src/lib/liveActivity.test.mjs
 */
import assert from 'node:assert/strict';
import { activityJobActive } from './liveActivity.ts';

assert.equal(activityJobActive(null, false), false);
assert.equal(activityJobActive(null, true), true);
assert.equal(activityJobActive({ status: 'idle' }, false), false);
assert.equal(activityJobActive({ status: 'running' }, false), true);
assert.equal(activityJobActive({ status: 'queued' }, false), true);
assert.equal(activityJobActive({ status: 'pending' }, false), true);
assert.equal(activityJobActive({ status: 'completed' }, false), false);
assert.equal(activityJobActive({ status: 'RUNNING' }, false), true);
console.log('liveActivity ok');
