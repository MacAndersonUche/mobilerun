/**
 * Run: node --experimental-strip-types src/lib/datingRun.test.mjs
 */
import assert from 'node:assert/strict';
import {
  canRunApp,
  clampRunCount,
  datingStartBody,
  runCountFor,
  runCountLabel,
  sortDatingApps,
  RUNNABLE_APPS,
  runModesOf,
  runModeFor,
  hasLikeCap,
  todayCounterKind,
  formatTodayCounters,
  todayCounterNote,
  sumWorkingTodayCounters,
  formatWorkingTodayTotals,
} from './datingRun.ts';

assert.equal(todayCounterKind('com.badoo.mobile'), 'swipes');
assert.equal(todayCounterKind('com.bumble.app'), 'swipes');
assert.equal(todayCounterKind('co.hinge.app'), 'messages');
assert.equal(todayCounterKind('co.yellw.yellowapp'), 'messages');
assert.equal(todayCounterKind('com.facebook.katana'), 'messages');
assert.equal(todayCounterKind('com.hily.app'), 'both');
assert.equal(todayCounterKind('com.taggedapp'), 'both');
assert.equal(
  formatTodayCounters('com.bumble.app', { swipes: 7, openers: 3 }),
  'Today: 7 swipes'
);
assert.equal(
  formatTodayCounters('co.hinge.app', { swipes: 4, openers: 5 }),
  'Today: 5 messages'
);
assert.equal(
  formatTodayCounters('com.facebook.katana', { swipes: 9, openers: 12 }),
  'Today: 12 messages'
);
assert.equal(
  formatTodayCounters('com.hily.app', { swipes: 3, openers: 2 }),
  'Today: 3 swipes · 2 messages'
);
assert.equal(todayCounterNote('com.facebook.katana'), 'Max 50 a day');
assert.equal(todayCounterNote('co.hinge.app'), null);
// Working header totals: only count metrics each app tracks
assert.deepEqual(
  sumWorkingTodayCounters([
    { package: 'com.bumble.app', today: { swipes: 9, openers: 4 } }, // swipes only
    { package: 'co.hinge.app', today: { swipes: 2, openers: 5 } }, // messages only
    { package: 'com.facebook.katana', today: { swipes: 6, openers: 11 } }, // messages
    { package: 'com.hily.app', today: { swipes: 3, openers: 2 } }, // both
  ]),
  { swipes: 12, messages: 18 }
);
assert.equal(
  formatWorkingTodayTotals({ swipes: 12, messages: 18 }),
  '12 swipes · 18 messages'
);
assert.ok(!formatWorkingTodayTotals({ swipes: 1, messages: 2 }).includes('—'));

assert.equal(canRunApp('co.hinge.app'), true);
assert.equal(canRunApp('com.whatsapp'), false);
assert.equal(canRunApp('ai.mobilerun.mockdating'), false);

const all = datingStartBody({
  deviceId: 'android_x',
  dryRun: true,
  contactScope: 'new',
  counts: { 'co.hinge.app': 3, 'com.whatsapp': 9 },
  apps: ['com.whatsapp', 'co.hinge.app', 'com.hily.app', 'com.taggedapp'],
});
// r45: Tagged is runnable now (auto swipe / auto message)
assert.deepEqual(all.apps, ['co.hinge.app', 'com.hily.app', 'com.taggedapp']);
// Each app its own number; unset apps use the default 5; no socials
assert.deepEqual(all.counts, { 'co.hinge.app': 3, 'com.hily.app': 5, 'com.taggedapp': 5 });
assert.equal(all.device_id, 'android_x');
assert.equal('stand_in_package' in all, false);

const one = datingStartBody({
  deviceId: '',
  dryRun: false,
  contactScope: 'new',
  counts: { 'com.facebook.katana': 80, 'com.bumble.app': 20 },
  apps: ['com.facebook.katana'],
});
assert.deepEqual(one.apps, ['com.facebook.katana']);
assert.deepEqual(one.counts, { 'com.facebook.katana': 50 }); // FB cap 50
assert.equal(runCountFor('com.bumble.app', { 'com.bumble.app': 20 }), 20);
assert.equal(clampRunCount('com.badoo.mobile', 0), 1);
assert.equal(clampRunCount('com.badoo.mobile', 900), 500);
assert.equal(runCountLabel('com.bumble.app'), 'Swipes per run');
assert.match(runCountLabel('com.hily.app'), /max 5/); // r46: Hily messages
assert.equal(one.device_id, undefined);
console.log('datingRun ok');

// r45: free typing, validate on submit; caps kept
{
  const { parseCountInput, parseRunCount, runCountHint } = await import('./datingRun.ts');
  const a = (c, m) => { if (!c) throw new Error(m); };
  a(parseCountInput('', 10).ok === false, 'blank refused at submit');
  a(parseCountInput('abc', 10).ok === false, 'letters refused');
  a(parseCountInput('0', 10).ok === false, 'zero refused');
  a(parseCountInput('7', 10).ok && parseCountInput('7', 10).n === 7, '7 ok');
  a(parseCountInput('11', 10).ok === false, 'over cap refused');
  const fb = parseRunCount('com.facebook.katana', '60');
  a(!fb.ok && /50/.test(fb.error), 'FB cap 50 shown');
  a(parseRunCount('com.bumble.app', '250').ok, 'bumble 250 ok');
  a(/50/.test(runCountHint('com.facebook.katana')), 'FB hint');
  console.log('r45 count input tests ok');
}

// r45: Tagged run mode
{
  const { datingStartBody, runModeFor, canRunApp } = await import('./datingRun.ts');
  const a = (c, m) => { if (!c) throw new Error(m); };
  a(canRunApp('com.taggedapp'), 'tagged runnable');
  a(runModeFor('com.taggedapp', {}) === 'swipe', 'default swipe');
  const b = datingStartBody({ deviceId: 'd', dryRun: false, contactScope: 'new',
    counts: { 'com.taggedapp': 7 }, apps: ['com.taggedapp', 'com.bumble.app'],
    modes: { 'com.taggedapp': 'message' } });
  a(b.modes['com.taggedapp'] === 'message' && !('com.bumble.app' in b.modes), 'modes body');
  a(b.counts['com.taggedapp'] === 7, 'tagged count');
  console.log('r45 tagged mode tests ok');
}

// r46: Hily Likes only / Message + likes, max likes per mode
{
  const m = await import('./datingRun.ts');
  const a = (c, msg) => { if (!c) throw new Error(msg); };
  a(m.hasRunMode('com.hily.app') && m.hasLikeCap('com.hily.app'), 'hily has modes + likes');
  a(!m.hasLikeCap('com.taggedapp'), 'tagged has no like cap');
  a(m.runModeFor('com.hily.app', {}) === 'message_likes', 'hily default message + likes');
  a(m.runModeFor('com.hily.app', { 'com.hily.app': 'swipe' }) === 'message_likes', 'tagged mode refused for hily');
  a(m.runModesOf('com.hily.app').map((x) => x.label).join('|') === 'Likes only|Message + likes', 'labels');
  a(!m.showsCount('com.hily.app', { 'com.hily.app': 'likes' }), 'no message box in Likes only');
  a(m.showsCount('com.hily.app', {}), 'message box in Message + likes');
  a(!m.parseRunCount('com.hily.app', '6').ok, 'hily messages max 5');
  a(!m.parseLikeCap('501').ok && m.parseLikeCap('120').ok, 'likes max 500');
  const b = m.datingStartBody({ deviceId: 'd', dryRun: false, contactScope: 'new',
    counts: { 'com.hily.app': 3 }, apps: ['com.hily.app', 'com.bumble.app'],
    modes: { 'com.hily.app': 'likes' }, likeCaps: { 'com.hily.app:likes': 80 } });
  a(b.modes['com.hily.app'] === 'likes', 'hily mode in body');
  a(b.like_caps['com.hily.app:likes'] === 80, 'likes-only cap');
  a(b.like_caps['com.hily.app:message_likes'] === 30, 'other mode keeps its own default');
  a(!Object.keys(b.like_caps).some((k) => k.startsWith('com.bumble')), 'no bumble caps');
  console.log('r46 hily mode tests ok');
}

// r49: Tinder and BLK at the bottom; everything else keeps its order
{
  const pk = (a) => a.p;
  const got = sortDatingApps(
    [{ p: 'com.tinder' }, { p: 'com.bumble.app' }, { p: 'com.affinityapps.blk' },
     { p: 'com.hily.app' }, { p: 'co.hinge.app' }],
    pk
  ).map(pk);
  assert.deepEqual(got, ['com.bumble.app', 'com.hily.app', 'co.hinge.app',
    'com.affinityapps.blk', 'com.tinder']);
  // BLK then Tinder sit just above the r50+ coming-soon tail (Boo…MeetMe)
  const blkAt = RUNNABLE_APPS.indexOf('com.affinityapps.blk');
  assert.deepEqual(RUNNABLE_APPS.slice(blkAt, blkAt + 2), [
    'com.affinityapps.blk', 'com.tinder',
  ]);
  assert.equal(canRunApp('com.tinder'), true);
  assert.equal(canRunApp('com.myyearbook.m'), true);
}

// r50: new apps at the very bottom (after BLK, Tinder); Taimi stays put
{
  const pk = (a) => a.p;
  const got = sortDatingApps(
    ['com.getpure.pure', 'com.takimi.android', 'com.tinder', 'enterprises.dating.boo',
     'com.affinityapps.blk', 'com.bumble.app', 'social.breeze.breeze_app',
     'com.threesome.swingers.threefun'].map((p) => ({ p })),
    pk
  ).map(pk);
  assert.deepEqual(got, ['com.takimi.android', 'com.bumble.app', 'com.affinityapps.blk',
    'com.tinder', 'com.getpure.pure', 'enterprises.dating.boo', 'social.breeze.breeze_app',
    'com.threesome.swingers.threefun']);
  for (const p of ['enterprises.dating.boo', 'social.breeze.breeze_app', 'com.getpure.pure',
    'com.threesome.swingers.threefun', 'com.takimi.android']) assert.equal(canRunApp(p), true);
  assert.deepEqual(runModesOf('enterprises.dating.boo').map((m) => m.label),
    ['Auto like', 'Auto message + like']);
  assert.deepEqual(runModesOf('com.getpure.pure').map((m) => m.label), ['Auto tap', 'Auto message']);
  assert.equal(runModesOf('social.breeze.breeze_app').length, 0);
  assert.equal(runModeFor('com.takimi.android', {}), 'likes');
  assert.equal(hasLikeCap('com.takimi.android', 'likes'), false);
  assert.equal(hasLikeCap('enterprises.dating.boo', 'message_likes'), true);
  assert.equal(hasLikeCap('com.hily.app', 'likes'), true);
}

// r51b: saved/API lists that omit new runnable apps get them appended
{
  const { ensureRunnableConfigApps } = await import('./datingRun.ts');
  const seeded = ensureRunnableConfigApps(
    [{ package_name: 'com.bumble.app', name: 'Bumble' }],
    (pkg) => ({ package_name: pkg, name: pkg })
  );
  const pkgs = seeded.map((a) => a.package_name);
  assert.equal(pkgs[0], 'com.bumble.app');
  for (const p of ['com.takimi.android', 'enterprises.dating.boo', 'social.breeze.breeze_app',
    'com.getpure.pure', 'com.threesome.swingers.threefun', 'com.tinder']) {
    assert.equal(pkgs.includes(p), true, 'missing ' + p);
  }
  const again = ensureRunnableConfigApps(seeded, (pkg) => ({ package_name: pkg, name: 'dup' }));
  assert.equal(again.filter((a) => a.package_name === 'enterprises.dating.boo').length, 1);
  console.log('r51b ensureRunnableConfigApps tests ok');
}

// Dating page groups: works all the time / still needs fixing / apps to come
{
  const {
    datingAppGroup,
    groupDatingCards,
    canRunFromCard,
    isBlockedApp,
    DATING_APP_GROUPS,
  } = await import('./datingRun.ts');
  const a = (c, m) => { if (!c) throw new Error(m); };
  a(datingAppGroup('com.badoo.mobile') === 'works', 'Badoo works');
  a(datingAppGroup('com.bumble.app') === 'works', 'Bumble works');
  a(datingAppGroup('com.hily.app') === 'works', 'Hily works (verified live 5/5)');
  a(datingAppGroup('co.yellw.yellowapp') === 'works', 'Yubo works (verified live 5/5)');
  a(datingAppGroup('co.hinge.app') === 'works', 'Hinge works (verified live 5/5 r53n)');
  a(datingAppGroup('com.taggedapp') === 'works', 'Tagged works (messages sending)');
  a(datingAppGroup('com.facebook.katana') === 'works', 'Facebook works (verified live 5/5)');
  a(DATING_APP_GROUPS.find((g) => g.id === 'works')?.title === 'Working', 'Working label');
  a(datingAppGroup('com.affinityapps.blk') === 'coming-soon', 'BLK coming soon');
  a(datingAppGroup('com.takimi.android') === 'coming-soon', 'Taimi coming soon');
  a(datingAppGroup('com.tinder') === 'coming-soon', 'Tinder coming soon');
  a(datingAppGroup('enterprises.dating.boo') === 'coming-soon', 'Boo coming soon');
  a(datingAppGroup('social.breeze.breeze_app') === 'coming-soon', 'Breeze coming soon');
  a(datingAppGroup('com.getpure.pure') === 'coming-soon', 'Pure coming soon');
  a(datingAppGroup('com.threesome.swingers.threefun') === 'coming-soon', '3Fun coming soon');
  a(datingAppGroup('com.myyearbook.m') === 'coming-soon', 'MeetMe coming soon');
  a(datingAppGroup('com.whatsapp') === null, 'WhatsApp in no group');
  a(isBlockedApp('com.takimi.android'), 'Taimi blocked');
  a(!isBlockedApp('com.badoo.mobile'), 'Badoo not blocked');
  a(canRunFromCard('com.badoo.mobile'), 'Badoo card runnable');
  a(canRunFromCard('com.bumble.app'), 'Bumble card runnable');
  a(canRunFromCard('com.hily.app'), 'Hily card runnable');
  a(canRunFromCard('co.yellw.yellowapp'), 'Yubo card runnable');
  a(canRunFromCard('co.hinge.app'), 'Hinge card runnable');
  a(canRunFromCard('com.taggedapp'), 'Tagged card runnable');
  a(canRunFromCard('com.facebook.katana'), 'Facebook card runnable');
  a(!canRunFromCard('com.takimi.android'), 'Taimi card not runnable');
  a(!canRunFromCard('com.tinder'), 'Tinder card not runnable');
  a(!canRunFromCard('com.affinityapps.blk'), 'BLK card not runnable');
  a(!canRunFromCard('com.threesome.swingers.threefun'), '3Fun card not runnable');
  a(!canRunFromCard('com.myyearbook.m'), 'MeetMe card not runnable');
  a(!canRunFromCard('com.whatsapp'), 'WhatsApp card not runnable');
  // groups in order; within a group, cards follow the group's package list
  const grouped = groupDatingCards([
    { package: 'com.threesome.swingers.threefun' },
    { package: 'com.bumble.app' },
    { package: 'com.tinder' },
    { package: 'co.hinge.app' },
    { package: 'com.badoo.mobile' },
    { package: 'com.hily.app' },
    { package: 'co.yellw.yellowapp' },
    { package: 'com.taggedapp' },
    { package: 'com.affinityapps.blk' },
    { package: 'com.facebook.katana' },
    { package: 'com.takimi.android' },
    { package: 'enterprises.dating.boo' },
    { package: 'com.myyearbook.m' },
  ]);
  assert.deepEqual(grouped.map((g) => g.group.id), ['works', 'coming-soon']);
  assert.deepEqual(grouped[0].apps.map((x) => x.package), [
    'com.badoo.mobile', 'com.bumble.app', 'com.hily.app', 'co.yellw.yellowapp',
    'co.hinge.app', 'com.taggedapp', 'com.facebook.katana',
  ]);
  assert.deepEqual(grouped[1].apps.map((x) => x.package), [
    'com.tinder', 'enterprises.dating.boo', 'com.threesome.swingers.threefun',
    'com.myyearbook.m', 'com.affinityapps.blk', 'com.takimi.android',
  ]);
  // an app in no group falls into "Apps to come", never vanishes
  const withNew = groupDatingCards([{ package: 'com.example.new' }, { package: 'com.badoo.mobile' }]);
  assert.deepEqual(withNew.map((g) => g.group.id), ['works', 'coming-soon']);
  assert.deepEqual(withNew[1].apps.map((x) => x.package), ['com.example.new']);
  // every runnable app is in exactly one group
  const allGrouped = DATING_APP_GROUPS.flatMap((g) => g.packages);
  assert.equal(new Set(allGrouped).size, allGrouped.length, 'no app in two groups');
  RUNNABLE_APPS.forEach((pkg) => assert.ok(allGrouped.includes(pkg), pkg + ' in a group'));
  console.log('dating page groups tests ok');
}

// Collapsibles always start collapsed: clear any remembered expanded pref
{
  const {
    clearCollapsibleExpandedPrefs,
    APPS_TO_COME_EXPANDED_KEY,
  } = await import('./datingRun.ts');
  const mem = new Map([[APPS_TO_COME_EXPANDED_KEY, '1']]);
  const storage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => { mem.set(k, String(v)); },
    removeItem: (k) => { mem.delete(k); },
  };
  assert.equal(mem.get(APPS_TO_COME_EXPANDED_KEY), '1', 'stale expanded pref present');
  clearCollapsibleExpandedPrefs(storage);
  assert.equal(mem.has(APPS_TO_COME_EXPANDED_KEY), false, 'stale expanded pref cleared');
  clearCollapsibleExpandedPrefs(storage); // idempotent
  assert.equal(mem.has(APPS_TO_COME_EXPANDED_KEY), false, 'clear is idempotent');
  console.log('collapsible start-collapsed tests ok');
}

// Apps for Start: always seed runnable dating apps (never empty when config load fails)
{
  const { appsForStartRows, RUNNABLE_APPS: apps } = await import('./datingRun.ts');
  const seed = (pkg) => ({ package_name: pkg, name: pkg, enabled: true });
  const isSocial = (pkg) =>
    ['com.whatsapp', 'com.instagram.android', 'com.facebook.orca',
      'org.telegram.messenger', 'com.snapchat.android', 'com.twitter.android']
      .includes(pkg);
  // Empty config (failed / pending load) still lists every runnable dating app
  const empty = appsForStartRows([], seed, isSocial);
  assert.equal(empty.length, apps.length, 'seeds all RUNNABLE_APPS');
  assert.ok(empty.every((a) => !isSocial(a.package_name)), 'no socials');
  assert.ok(empty.some((a) => a.package_name === 'co.hinge.app'), 'includes Hinge');
  assert.ok(empty.some((a) => a.package_name === 'com.bumble.app'), 'includes Bumble');
  // Preserves saved opener_mode / enabled from config
  const mixed = appsForStartRows(
    [{ package_name: 'com.bumble.app', name: 'Bumble', enabled: false, opener_mode: 'ai' }],
    seed,
    isSocial
  );
  const bumble = mixed.find((a) => a.package_name === 'com.bumble.app');
  assert.equal(bumble?.enabled, false, 'keeps saved enabled');
  assert.equal(bumble?.opener_mode, 'ai', 'keeps saved opener_mode');
  assert.ok(mixed.length >= apps.length, 'still has full runnable set');
  console.log('appsForStartRows tests ok');
}
