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
} from './datingRun.ts';

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
  assert.deepEqual(RUNNABLE_APPS.slice(-6, -4), ['com.affinityapps.blk', 'com.tinder']);
  assert.equal(canRunApp('com.tinder'), true);
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
  a(datingAppGroup('com.taggedapp') === 'needs-fixing', 'Tagged needs fixing');
  a(datingAppGroup('com.affinityapps.blk') === 'needs-fixing', 'BLK needs fixing');
  a(datingAppGroup('com.facebook.katana') === 'needs-fixing', 'Facebook needs fixing');
  a(datingAppGroup('com.takimi.android') === 'needs-fixing', 'Taimi needs fixing');
  a(datingAppGroup('com.tinder') === 'coming-soon', 'Tinder coming soon');
  a(datingAppGroup('enterprises.dating.boo') === 'coming-soon', 'Boo coming soon');
  a(datingAppGroup('social.breeze.breeze_app') === 'coming-soon', 'Breeze coming soon');
  a(datingAppGroup('com.getpure.pure') === 'coming-soon', 'Pure coming soon');
  a(datingAppGroup('com.threesome.swingers.threefun') === 'coming-soon', '3Fun coming soon');
  a(datingAppGroup('com.whatsapp') === null, 'WhatsApp in no group');
  a(isBlockedApp('com.takimi.android'), 'Taimi blocked');
  a(!isBlockedApp('com.badoo.mobile'), 'Badoo not blocked');
  a(canRunFromCard('com.badoo.mobile'), 'Badoo card runnable');
  a(canRunFromCard('com.bumble.app'), 'Bumble card runnable');
  a(canRunFromCard('com.hily.app'), 'Hily card runnable');
  a(canRunFromCard('co.yellw.yellowapp'), 'Yubo card runnable');
  a(canRunFromCard('co.hinge.app'), 'Hinge card runnable');
  a(!canRunFromCard('com.takimi.android'), 'Taimi card not runnable');
  a(!canRunFromCard('com.tinder'), 'Tinder card not runnable');
  a(!canRunFromCard('com.threesome.swingers.threefun'), '3Fun card not runnable');
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
    { package: 'enterprises.dating.boo' },
  ]);
  assert.deepEqual(grouped.map((g) => g.group.id), ['works', 'needs-fixing', 'coming-soon']);
  assert.deepEqual(grouped[0].apps.map((x) => x.package), [
    'com.badoo.mobile', 'com.bumble.app', 'com.hily.app', 'co.yellw.yellowapp', 'co.hinge.app',
  ]);
  assert.deepEqual(grouped[1].apps.map((x) => x.package), ['com.taggedapp']);
  assert.deepEqual(grouped[2].apps.map((x) => x.package), [
    'com.tinder', 'enterprises.dating.boo', 'com.threesome.swingers.threefun',
  ]);
  // an app in no group falls into "Still needs fixing", never vanishes
  const withNew = groupDatingCards([{ package: 'com.example.new' }, { package: 'com.badoo.mobile' }]);
  assert.deepEqual(withNew.map((g) => g.group.id), ['works', 'needs-fixing']);
  assert.deepEqual(withNew[1].apps.map((x) => x.package), ['com.example.new']);
  // every runnable app is in exactly one group
  const allGrouped = DATING_APP_GROUPS.flatMap((g) => g.packages);
  assert.equal(new Set(allGrouped).size, allGrouped.length, 'no app in two groups');
  RUNNABLE_APPS.forEach((pkg) => assert.ok(allGrouped.includes(pkg), pkg + ' in a group'));
  console.log('dating page groups tests ok');
}

// Apps to run collapsible: default expanded; localStorage remembers
{
  const {
    readAppsToRunExpanded,
    writeAppsToRunExpanded,
    APPS_TO_RUN_EXPANDED_KEY,
  } = await import('./datingRun.ts');
  const mem = new Map();
  const storage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => { mem.set(k, String(v)); },
  };
  assert.equal(readAppsToRunExpanded(storage), true, 'default expanded');
  writeAppsToRunExpanded(false, storage);
  assert.equal(mem.get(APPS_TO_RUN_EXPANDED_KEY), '0');
  assert.equal(readAppsToRunExpanded(storage), false, 'collapsed after write');
  writeAppsToRunExpanded(true, storage);
  assert.equal(readAppsToRunExpanded(storage), true, 'expanded after write');
  console.log('apps to run expanded tests ok');
}
