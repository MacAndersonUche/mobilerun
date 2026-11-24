/**
 * Run: node --experimental-strip-types src/lib/datingSchedule.test.mjs
 */
import assert from 'node:assert/strict';
import {
  clampRuns,
  daysLabel,
  scheduleBody,
  scheduleSummary,
  validTime,
} from './datingSchedule.ts';

assert.equal(validTime('09:30'), true);
assert.equal(validTime('24:00'), false);
assert.equal(daysLabel([]), 'Every day');
assert.equal(daysLabel([4, 0]), 'Mon, Fri');
assert.equal(clampRuns(0), 1);
assert.equal(clampRuns(99), 10);

const body = scheduleBody({
  enabled: true,
  items: [
    { app: 'com.bumble.app', runs: 2, count: 20 },
    { app: 'com.facebook.katana', runs: 1, count: 90 },
    { app: 'com.whatsapp', runs: 1, count: 5 },
  ],
  time: ' 21:05 ',
  days: [0, 1, 2, 3, 4, 5, 6],
  dry_run: true,
  device_id: 'android_x',
});
assert.deepEqual(body.items, [
  { app: 'com.bumble.app', runs: 2, count: 20 },
  { app: 'com.facebook.katana', runs: 1, count: 50 },
]);
assert.equal(body.time, '21:05');
assert.deepEqual(body.days, []);
assert.equal(
  scheduleSummary(
    { enabled: true, items: body.items, time: '21:05', days: [], dry_run: true },
    (p) => (p === 'com.bumble.app' ? 'Bumble' : 'Facebook Dating')
  ),
  'Bumble ×2 (20/run) → Facebook Dating (50/run) · 21:05 Every day · dry run'
);
console.log('datingSchedule ok');
