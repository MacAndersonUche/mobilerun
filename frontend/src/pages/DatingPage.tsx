import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Heart, Play, Square, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import ModeSpeedPicker from '../components/ModeSpeedPicker';
import LiveActivityFeed, {
  ActivityPayload,
  activityJobActive,
} from '../components/LiveActivityFeed';
import {
  parseRunCount,
  runCountHint,
  hasRunMode,
  runModeFor,
  datingStartBody,
  runCountFor,
  runCountLabel,
  type RunMode,
  runModesOf,
  hasLikeCap,
  likeCapKey,
  likeCapFor,
  likeCapHint,
  parseLikeCap,
  showsCount,
  sortDatingApps,
  RUNNABLE_APPS,
  ensureRunnableConfigApps,
  appsForStartRows,
  shouldShowAppsForStart,
  datingAppGroup,
  groupDatingCards,
  canRunFromCard,
  isBlockedApp,
  TAIMI_BLOCKED_NOTE,
  clearCollapsibleExpandedPrefs,
  formatTodayCounters,
  todayCounterNote,
  sumWorkingTodayCounters,
  formatWorkingTodayTotals,
} from '../lib/datingRun';
import { isSocialPackage } from '../lib/socialRun';
import DatingSchedules from '../components/DatingSchedules';

type Speed = 'fast' | 'balanced' | 'careful';

interface AppStats {
  name: string;
  package: string;
  today: {
    swipes: number;
    likes: number;
    openers: number;
    replies: number;
    total_messages: number;
  };
  targets: {
    opener_target: number;
    opener_progress: number;
  };
  total: {
    swipes: number;
    openers: number;
    replies: number;
    messages: number;
    matches: number;
  };
  inbox: {
    unread: number;
    new_matches: number;
  };
  last_active: string | null;
}

interface DatingStatus {
  running: boolean;
  paused: boolean;
  current_app: string | null;
  job_id?: string;
  activity?: ActivityPayload;
}

interface AppConfig {
  name: string;
  package_name: string;
  enabled: boolean;
  daily_swipe_cap: number;
  daily_opener_target_min?: number;
  daily_opener_target_max?: number;
  opener_mode?: OpenerMode;
}

type OpenerMode = 'templates' | 'ai';

const DATING_APP_NAMES: Record<string, string> = {
  'com.takimi.android': 'Taimi',
  'com.bumble.app': 'Bumble',
  'co.yellw.yellowapp': 'Yubo',
  'com.badoo.mobile': 'Badoo',
  'com.affinityapps.blk': 'BLK',
  'com.tinder': 'Tinder',
  'enterprises.dating.boo': 'Boo',
  'social.breeze.breeze_app': 'Breeze',
  'com.getpure.pure': 'Pure',
  'com.threesome.swingers.threefun': '3Fun',
  'com.myyearbook.m': 'MeetMe',
  'com.hily.app': 'Hily',
  'co.hinge.app': 'Hinge',
  'com.taggedapp': 'Tagged',
  'com.whatsapp': 'WhatsApp',
  'com.facebook.katana': 'Facebook',
  'com.snapchat.android': 'Snapchat',
  'com.instagram.android': 'Instagram',
};

function datingAppDisplayName(
  packageName: string | undefined,
  appName?: string | null
): string {
  const named = (appName || '').trim();
  if (named) return named;
  const pkg = (packageName || '').trim();
  if (DATING_APP_NAMES[pkg]) return DATING_APP_NAMES[pkg];
  const parts = pkg
    .split('.')
    .filter((p) => p && !['app', 'android', 'mobile'].includes(p.toLowerCase()));
  const tail = parts[parts.length - 1] || pkg;
  return tail ? tail.charAt(0).toUpperCase() + tail.slice(1) : 'Unknown';
}

/** Seed a missing runnable app into Apps for Start / config state. */
function seedConfigApp(pkg: string): AppConfig {
  return {
    name: datingAppDisplayName(pkg),
    package_name: pkg,
    // First run: disabled until the user picks apps in Apps for Start.
    enabled: false,
    daily_swipe_cap: 50,
  };
}

function cardsForDatingApps(
  apps: AppStats[],
  configApps: AppConfig[]
): AppStats[] {
  const blank = (): Omit<AppStats, 'name' | 'package'> => ({
    today: { swipes: 0, likes: 0, openers: 0, replies: 0, total_messages: 0 },
    targets: { opener_target: 75, opener_progress: 0 },
    total: { swipes: 0, openers: 0, replies: 0, messages: 0, matches: 0 },
    inbox: { unread: 0, new_matches: 0 },
    last_active: null,
  });
  const byPkg = new Map<string, AppStats>();
  for (const a of configApps) {
    byPkg.set(a.package_name, {
      ...blank(),
      name: datingAppDisplayName(a.package_name, a.name),
      package: a.package_name,
    });
  }
  // r51b: always show runnable apps even if /api/dating/config is stale
  for (const pkg of RUNNABLE_APPS) {
    if (!byPkg.has(pkg)) {
      byPkg.set(pkg, {
        ...blank(),
        name: datingAppDisplayName(pkg),
        package: pkg,
      });
    }
  }
  for (const a of apps) {
    const prev = byPkg.get(a.package);
    byPkg.set(a.package, {
      ...a,
      name: datingAppDisplayName(a.package, a.name || prev?.name),
    });
  }
  return sortDatingApps(Array.from(byPkg.values()), (a) => a.package);
}

interface OpenerTemplate {
  id: string;
  text: string;
  bucket: 'morning' | 'afternoon' | 'evening' | 'any' | string;
  enabled: boolean;
}

function omitKey<T>(o: Record<string, T>, k: string): Record<string, T> {
  const out = { ...o };
  delete out[k];
  return out;
}

export default function DatingPage() {
  const [status, setStatus] = useState<DatingStatus | null>(null);
  const [apps, setApps] = useState<AppStats[]>([]);
  // Seed RUNNABLE_APPS immediately so Apps for Start is never an empty body
  // while /api/dating/config loads (or if that request fails).
  const [configApps, setConfigApps] = useState<AppConfig[]>(() =>
    ensureRunnableConfigApps([], seedConfigApp)
  );
  const [persona, setPersona] = useState('');
  const [replyPersona, setReplyPersona] = useState('');
  const [inviteDaysMin, setInviteDaysMin] = useState(3);
  const [inviteDaysMax, setInviteDaysMax] = useState(7);
  const [homeLocation, setHomeLocation] = useState('Stoke-on-Trent');
  const [radiusMiles, setRadiusMiles] = useState(50);
  const [inviteEnabled, setInviteEnabled] = useState(true);
  const [handoffEnabled, setHandoffEnabled] = useState(true);
  const [calendarOnHandoff, setCalendarOnHandoff] = useState(true);
  const [contactAskEnabled, setContactAskEnabled] = useState(true);
  const [contactAskOrder, setContactAskOrder] = useState<string[]>([
    'whatsapp',
    'snapchat',
  ]);
  const [contactAskWhatsappText, setContactAskWhatsappText] = useState(
    'Would it be easier to chat on WhatsApp? Totally optional - no pressure either way.'
  );
  const [contactAskSnapchatText, setContactAskSnapchatText] = useState(
    'No worries - would Snapchat be easier instead? Totally optional, only if you like.'
  );
  const [dateFlowStats, setDateFlowStats] = useState<{
    chats_active: number;
    invites_sent: number;
    dates_booked: number;
    by_app?: Record<string, { chats_active: number; invites_sent: number; dates_booked: number }>;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  // Sync lock so a double-tap cannot fire two Starts before React re-renders.
  const startLockRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  // Per app, per run (each app card): swipes or messages. Saved per app on
  // the server; Hily = messages (max 5), Facebook Dating max 50.
  const [runCounts, setRunCounts] = useState<Record<string, number>>({});
  // r45: what is typed in each card's count box (free text until Start/blur)
  const [countDrafts, setCountDrafts] = useState<Record<string, string>>({});
  const [countErrors, setCountErrors] = useState<Record<string, string>>({});
  // r45: per-app run mode (Tagged: auto swipe / auto message)
  const [runModes, setRunModes] = useState<Record<string, string>>({});
  // r46: max likes per Hily mode ("<pkg>:<mode>" -> n) + typed drafts
  const [likeCaps, setLikeCaps] = useState<Record<string, number>>({});
  const [likeDrafts, setLikeDrafts] = useState<Record<string, string>>({});
  const [likeErrors, setLikeErrors] = useState<Record<string, string>>({});
  // First-contact only — reply checking/tracking removed from dating runs.
  const contactScope = 'new' as const;
  // Always collapsed on load — never restore expanded from localStorage (#94
  // left phones expanded after a prior open). Session toggle only.
  const [appsToComeExpanded, setAppsToComeExpanded] = useState(false);
  const [appsForStartExpanded, setAppsForStartExpanded] = useState(false);
  // Single Working section — collapsed on every page load.
  const [workingExpanded, setWorkingExpanded] = useState(false);
  useEffect(() => {
    clearCollapsibleExpandedPrefs();
  }, []);
  const [deviceId, setDeviceId] = useState('');
  const [devices, setDevices] = useState<
    Array<{ device_id: string; name?: string; connected?: boolean }>
  >([]);
  const [openerMode, setOpenerMode] = useState<OpenerMode>('templates');
  const [templates, setTemplates] = useState<OpenerTemplate[]>([]);
  const [bucketNow, setBucketNow] = useState('morning');
  const [bucketCounts, setBucketCounts] = useState<Record<string, number>>({});
  const [newTemplateText, setNewTemplateText] = useState('');
  const [newTemplateBucket, setNewTemplateBucket] = useState('any');

  const authHeaders = () => ({
    Authorization: `Bearer ${getAuthToken()}`,
  });

  const loadAll = async () => {
    const soft = async <T,>(path: string, fallback: T): Promise<T> => {
      try {
        const res = await axios.get(`${getBackendUrl()}${path}`, {
          headers: authHeaders(),
        });
        return res.data as T;
      } catch (e) {
        console.warn('Dating optional load failed', path, e);
        return fallback;
      }
    };
    try {
      // Status is required for Running/Stopped. Stats/config/openers are soft
      // so a 500 on /api/dating/stats (e.g. Lambda FS) never blanks the page
      // while a dating job is actively running.
      const statusRes = await axios.get(`${getBackendUrl()}/api/dating/status`, {
        headers: authHeaders(),
      });
      const statsRes = await soft<{ apps?: AppStats[]; today?: { swipes?: number; messages?: number } }>(
        '/api/dating/stats',
        { apps: [], today: { swipes: 0, messages: 0 } }
      );
      const configRes = await soft<{
        apps?: AppConfig[];
        persona_prompt?: string;
        date_flow?: Record<string, unknown>;
        reply_persona_prompt?: string;
        date_flow_stats?: typeof dateFlowStats;
        speed_preset?: string;
        opener_mode?: string;
      }>('/api/dating/config', { apps: [] });
      const openersRes = await soft<{
        library?: { templates?: OpenerTemplate[] };
        bucket_now?: string;
        bucket_counts?: Record<string, number>;
      }>('/api/dating/openers', {
        library: { templates: [] },
        bucket_now: 'morning',
        bucket_counts: {},
      });
      const rc = await soft<{
        counts?: Record<string, number>;
        modes?: Record<string, string>;
        like_caps?: Record<string, number>;
      }>('/api/dating/run-counts', { counts: {}, modes: {}, like_caps: {} });
      setRunCounts(rc.counts || {});
      setRunModes(rc.modes || {});
      setLikeCaps(rc.like_caps || {});
      setStatus(statusRes.data);
      const appRows = statsRes.apps || [];
      setApps(appRows);
      setConfigApps(
        ensureRunnableConfigApps(configRes.apps || [], seedConfigApp)
      );
      setPersona(configRes.persona_prompt || '');
      const df = (configRes.date_flow || {}) as Record<string, any>;
      setReplyPersona(
        df.reply_persona_prompt || configRes.reply_persona_prompt || ''
      );
      setInviteDaysMin(df.invite_days_min ?? 3);
      setInviteDaysMax(df.invite_days_max ?? 7);
      setHomeLocation(df.home_location || 'Stoke-on-Trent');
      setRadiusMiles(df.radius_miles ?? 50);
      setInviteEnabled(df.invite_enabled ?? true);
      setHandoffEnabled(df.handoff_enabled ?? true);
      setCalendarOnHandoff(df.calendar_on_handoff ?? true);
      setContactAskEnabled(df.contact_ask_enabled ?? true);
      if (Array.isArray(df.contact_ask_order) && df.contact_ask_order.length) {
        setContactAskOrder(df.contact_ask_order);
      }
      if (df.contact_ask_whatsapp_text || df.contact_ask_text) {
        setContactAskWhatsappText(
          df.contact_ask_whatsapp_text || df.contact_ask_text
        );
      }
      if (df.contact_ask_snapchat_text) {
        setContactAskSnapchatText(df.contact_ask_snapchat_text);
      }
      setDateFlowStats(configRes.date_flow_stats || null);
      if (
        configRes.speed_preset &&
        ['fast', 'balanced', 'careful'].includes(configRes.speed_preset)
      ) {
        setSpeed(configRes.speed_preset as Speed);
      }
      if (
        configRes.opener_mode === 'templates' ||
        configRes.opener_mode === 'ai'
      ) {
        setOpenerMode(configRes.opener_mode);
      }
      setTemplates(openersRes.library?.templates || []);
      setBucketNow(openersRes.bucket_now || 'morning');
      setBucketCounts(openersRes.bucket_counts || {});
      setActivity(statusRes.data.activity || null);
      setError(null);
    } catch (e: unknown) {
      console.error(e);
      setError('Failed to load dating mode. Is the backend running and authenticated?');
      // Keep Apps for Start populated even when config load fails — Working
      // cards already seed from RUNNABLE_APPS; match that guarantee here.
      setConfigApps((prev) => ensureRunnableConfigApps(prev, seedConfigApp));
    }
  };

  const loadDevices = async () => {
    try {
      const res = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: authHeaders(),
      });
      const list = (res.data || []) as Array<{
        device_id: string;
        name?: string;
        connected?: boolean;
      }>;
      setDevices(list);
      const online = list.find((d) => d.connected);
      if (online && !deviceId) setDeviceId(online.device_id);
    } catch {
      /* optional */
    }
  };

  useEffect(() => {
    loadAll();
    loadDevices();
    const interval = setInterval(() => {
      loadAll();
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  const control = async (
    action: 'start' | 'stop',
    onlyApp?: string
  ) => {
    if (action === 'start') {
      if (startLockRef.current || loading) return;
      startLockRef.current = true;
    }
    setLoading(true);
    try {
      // Restart only: stop the active job first. Do not stop on a fresh Start
      // — that raced with double-taps and created two Hily jobs in one second.
      if (action === 'start' && status?.running) {
        try {
          await axios.post(
            `${getBackendUrl()}/api/dating/stop`,
            {},
            { headers: authHeaders() }
          );
        } catch {
          /* ok */
        }
      }
      // r45: validate typed counts on Start only
      let counts = runCounts;
      let caps = likeCaps;
      if (action === 'start') {
        const startApps = onlyApp
          ? [onlyApp]
          : configApps.filter((a) => a.enabled).map((a) => a.package_name);
        const errs: Record<string, string> = {};
        const next = { ...runCounts };
        startApps.forEach((pkg) => {
          if (countDrafts[pkg] === undefined || !showsCount(pkg, runModes)) return;
          const r = parseRunCount(pkg, countDrafts[pkg]);
          if (r.ok) next[pkg] = r.n;
          else errs[pkg] = r.error;
        });
        // r46: typed max-likes boxes (per app mode)
        const nextCaps = { ...likeCaps };
        const likeErrs: Record<string, string> = {};
        Object.entries(likeDrafts).forEach(([key, raw]) => {
          if (!startApps.some((p) => key.startsWith(`${p}:`))) return;
          const r = parseLikeCap(raw);
          if (r.ok) nextCaps[key] = r.n;
          else likeErrs[key] = r.error;
        });
        setCountErrors(errs);
        setLikeErrors(likeErrs);
        const allErrs = [...Object.values(errs), ...Object.values(likeErrs)];
        if (allErrs.length) {
          alert(allErrs.join('\n'));
          return;
        }
        counts = next;
        caps = nextCaps;
      }
      const body =
        action === 'start'
          ? datingStartBody({
              deviceId,
              contactScope,
              counts,
              modes: runModes,
              likeCaps: caps,
              apps: onlyApp
                ? [onlyApp]
                : configApps.filter((a) => a.enabled).map((a) => a.package_name),
            })
          : {};
      await axios.post(`${getBackendUrl()}/api/dating/${action}`, body, {
        headers: authHeaders(),
      });
      await loadAll();
    } catch (e) {
      console.error(e);
      const detail = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : `Failed to ${action} dating mode`;
      alert(detail);
    } finally {
      if (action === 'start') startLockRef.current = false;
      setLoading(false);
    }
  };

  const saveRunCount = async (pkg: string, raw: string) => {
    const r = parseRunCount(pkg, raw);
    if (!r.ok) {
      // keep what was typed; Start will refuse until it is fixed
      setCountErrors((prev) => ({ ...prev, [pkg]: r.error }));
      return;
    }
    const n = r.n;
    setCountErrors((prev) => omitKey(prev, pkg));
    setCountDrafts((prev) => omitKey(prev, pkg));
    setRunCounts((prev) => ({ ...prev, [pkg]: n }));
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/run-counts`,
        { counts: { [pkg]: n } },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const saveLikeCap = async (key: string, raw: string) => {
    const r = parseLikeCap(raw);
    if (!r.ok) {
      setLikeErrors((prev) => ({ ...prev, [key]: r.error }));
      return;
    }
    const n = r.n;
    setLikeErrors((prev) => omitKey(prev, key));
    setLikeDrafts((prev) => omitKey(prev, key));
    setLikeCaps((prev) => ({ ...prev, [key]: n }));
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/run-counts`,
        { like_caps: { [key]: n } },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const saveRunMode = async (pkg: string, mode: RunMode) => {
    setRunModes((prev) => ({ ...prev, [pkg]: mode }));
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/run-counts`,
        { modes: { [pkg]: mode } },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const saveConfig = async () => {
    setLoading(true);
    try {
      const perApp: Record<string, OpenerMode> = {};
      configApps.forEach((a) => {
        if (a.opener_mode === 'templates' || a.opener_mode === 'ai') {
          perApp[a.package_name] = a.opener_mode;
        }
      });
      await axios.post(
        `${getBackendUrl()}/api/dating/config`,
        {
          enabled_apps: configApps
            .filter((a) => a.enabled)
            .map((a) => a.package_name),
          round_robin: true,
          review_before_send: false,
          persona_prompt: persona,
          active_hours_start: '09:00',
          active_hours_end: '23:00',
          // Daily target UI removed — keep backend defaults when saving.
          min_total_messages_per_day: 100,
          max_total_messages_per_day: 500,
          speed_preset: speed,
          opener_mode: openerMode,
          per_app_opener_mode: perApp,
          reply_persona_prompt: replyPersona,
          invite_days_min: inviteDaysMin,
          invite_days_max: inviteDaysMax,
          home_location: homeLocation,
          radius_miles: radiusMiles,
          invite_enabled: inviteEnabled,
          handoff_enabled: handoffEnabled,
          calendar_on_handoff: calendarOnHandoff,
          contact_ask_enabled: contactAskEnabled,
          contact_ask_order: contactAskOrder,
          contact_ask_whatsapp_text: contactAskWhatsappText,
          contact_ask_snapchat_text: contactAskSnapchatText,
          contact_ask_text: contactAskWhatsappText,
        },
        { headers: authHeaders() }
      );
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: 'dating', speed_preset: speed },
        { headers: authHeaders() }
      );
      await loadAll();
    } catch (e) {
      console.error(e);
      alert('Failed to save config');
    } finally {
      setLoading(false);
    }
  };

  const enabledCount = templates.filter((t) => t.enabled).length;

  const saveTemplates = async (next: OpenerTemplate[]) => {
    const enabled = next.filter((t) => t.enabled).length;
    if (enabled < 2 || enabled > 50) {
      alert('Keep 2-50 templates enabled');
      return;
    }
    setLoading(true);
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/openers`,
        {
          opener_mode: openerMode,
          templates: next,
        },
        { headers: authHeaders() }
      );
      setTemplates(next);
      await loadAll();
    } catch (e: unknown) {
      console.error(e);
      alert('Failed to save opener library');
    } finally {
      setLoading(false);
    }
  };

  const addTemplate = async () => {
    const text = newTemplateText.trim();
    if (!text) return;
    const next = [
      ...templates,
      {
        id: `t_${Date.now().toString(36)}`,
        text,
        bucket: newTemplateBucket,
        enabled: true,
      },
    ];
    await saveTemplates(next);
    setNewTemplateText('');
  };

  const setAppOpenerMode = (packageName: string, mode: OpenerMode) => {
    setConfigApps((prev) =>
      prev.map((a) =>
        a.package_name === packageName ? { ...a, opener_mode: mode } : a
      )
    );
  };

  const onSpeedChange = async (next: Speed) => {
    setSpeed(next);
    try {
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: 'dating', speed_preset: next },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const toggleApp = (packageName: string) => {
    setConfigApps((prev) =>
      prev.map((a) =>
        a.package_name === packageName ? { ...a, enabled: !a.enabled } : a
      )
    );
  };

  const statusLabel = !status?.running
    ? 'Stopped'
    : status.paused
      ? 'Paused'
      : 'Running';

  return (
    <div className="mr-page space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Heart className="text-rose-400 shrink-0" /> Dating
          </h1>
          <p className="text-mute mt-1 text-sm sm:text-base">
            MacMobileRun · app selection, openers, start/stop, activity
          </p>
          <p className="text-mute mt-1 text-sm">
            Covers new contacts, existing chats, or both - dating here,{' '}
            <Link to="/social" className="text-accent underline underline-offset-2">
              Social
            </Link>{' '}
            for unread chat follow-ups.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadAll()}
          className={`min-h-[44px] inline-flex items-center gap-2 rounded px-3 py-2 text-sm ${
            status?.running && !status.paused
              ? 'bg-green-900 text-green-300 hover:bg-green-800'
              : status?.paused
                ? 'bg-yellow-900 text-yellow-300 hover:bg-yellow-800'
                : 'bg-surface-elev text-mute hover:bg-gray-600'
          }`}
          title="Refresh status"
          aria-label={`Status ${statusLabel}. Refresh`}
          data-testid="dating-status-refresh"
        >
          <span>
            {statusLabel}
            {status?.current_app ? ` · ${status.current_app}` : ''}
          </span>
          <RefreshCw size={14} aria-hidden />
        </button>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-200 px-4 py-3 rounded">
          {error}
        </div>
      )}

      <ModeSpeedPicker
        mode="dating"
        speed={speed}
        hideMode
        onSpeedChange={onSpeedChange}
      />

      {/* Controls - stack on phone for one-handed use */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
          <button
            disabled={loading}
            onClick={() => control('start')}
            className="tap-target flex items-center justify-center gap-2 rounded-xl bg-rose-600 px-3 text-sm font-medium hover:bg-rose-500 disabled:opacity-50"
            data-testid="dating-start"
            title={status?.running ? 'Restarts dating mode (stops current job first)' : 'Start dating mode'}
          >
            <Play size={16} /> {status?.running ? 'Restart' : 'Start'}
          </button>
          <button
            disabled={loading}
            onClick={() => control('stop')}
            title="Stops every running dating job and frees the phone"
            className="tap-target flex items-center justify-center gap-2 rounded-xl bg-surface-elev px-3 text-sm font-medium hover:bg-gray-600 disabled:opacity-50"
            data-testid="dating-stop"
          >
            <Square size={16} /> Stop
          </button>
        </div>
        {devices.length > 0 && (
          <select
            className="mr-input w-full text-sm sm:max-w-xs"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            data-testid="dating-device"
            aria-label="Dating device"
          >
            <option value="">Select device…</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {(d.connected ? '● ' : '○ ') + (d.name || d.device_id)}
              </option>
            ))}
          </select>
        )}
      </div>

      <LiveActivityFeed
        title="Dating live activity"
        activity={activity}
        loading={!!status?.running && !status?.paused}
        collapsible
        jobActive={activityJobActive(activity, !!status?.running)}
      />

      {/* Working (one collapsible) + Apps to come */}
      <div className="space-y-6" data-testid="dating-apps-to-run">
            {groupDatingCards(
              cardsForDatingApps(apps, configApps).filter(
                (app) => !isSocialPackage(app.package)
              )
            ).map(({ group, apps: groupApps }) => {
              const isComingSoon = group.id === 'coming-soon';
              const isWorking = group.id === 'works';
              const groupExpanded = isComingSoon
                ? appsToComeExpanded
                : isWorking
                  ? workingExpanded
                  : true;
              const workingTotals = isWorking
                ? sumWorkingTodayCounters(groupApps)
                : null;
              return (
              <section
                key={group.id}
                aria-label={group.title}
                className="space-y-3"
                data-testid={
                  isComingSoon
                    ? 'dating-apps-to-come'
                    : isWorking
                      ? 'dating-apps-working'
                      : undefined
                }
              >
                {(isComingSoon || isWorking) ? (
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-lg border border-line bg-surface px-4 py-3 text-left hover:bg-canvas-elev"
                    aria-expanded={groupExpanded}
                    aria-controls={
                      isComingSoon
                        ? 'dating-apps-to-come-panel'
                        : 'dating-apps-working-panel'
                    }
                    data-testid={
                      isComingSoon
                        ? 'dating-apps-to-come-toggle'
                        : 'dating-apps-working-toggle'
                    }
                    onClick={() =>
                      isComingSoon
                        ? setAppsToComeExpanded((prev) => !prev)
                        : setWorkingExpanded((prev) => !prev)
                    }
                  >
                    {groupExpanded ? (
                      <ChevronDown size={18} className="shrink-0 text-mute" aria-hidden />
                    ) : (
                      <ChevronRight size={18} className="shrink-0 text-mute" aria-hidden />
                    )}
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                        <span className="text-lg font-semibold text-white">
                          {group.title}
                        </span>
                        {workingTotals && (
                          <span
                            className="text-sm font-medium text-mute"
                            data-testid="dating-working-today-totals"
                          >
                            {formatWorkingTodayTotals(workingTotals)}
                          </span>
                        )}
                      </span>
                      <span className="block text-xs text-mute">{group.subtitle}</span>
                    </span>
                  </button>
                ) : (
                  <div>
                    <h3 className="text-lg font-semibold">{group.title}</h3>
                    <p className="text-xs text-mute">{group.subtitle}</p>
                  </div>
                )}
                {groupExpanded && (
                <div
                  id={
                    isComingSoon
                      ? 'dating-apps-to-come-panel'
                      : isWorking
                        ? 'dating-apps-working-panel'
                        : undefined
                  }
                  className={isWorking ? 'space-y-2' : 'grid md:grid-cols-2 gap-4'}
                  role={isComingSoon || isWorking ? 'region' : undefined}
                  aria-label={isComingSoon || isWorking ? group.title : undefined}
                >
                  {groupApps.map((app) => (
                <div
                  key={app.package}
                  className="bg-surface border border-line rounded-lg overflow-hidden"
                  data-testid={`dating-app-card-${app.package}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2 px-4 py-3">
                    <div className="min-w-0">
                      <h4 className="font-semibold text-white">{app.name}</h4>
                      {datingAppGroup(app.package) === 'coming-soon' && (
                        <span className="mt-1 inline-block rounded bg-surface-elev px-2 py-0.5 text-xs text-mute">
                          Coming soon - no working driver yet
                        </span>
                      )}
                      {isBlockedApp(app.package) && (
                        <p className="mt-1 text-xs text-yellow-300">{TAIMI_BLOCKED_NOTE}</p>
                      )}
                      <p
                        className="mt-1 text-xs text-mute"
                        data-testid={`dating-today-${app.package}`}
                      >
                        {formatTodayCounters(app.package, app.today)}
                      </p>
                      {todayCounterNote(app.package) && (
                        <p
                          className="mt-0.5 text-[11px] text-mute/80"
                          data-testid={`dating-today-note-${app.package}`}
                        >
                          {todayCounterNote(app.package)}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1 text-right text-sm text-mute">
                      {!isWorking && <div>{app.inbox.unread} unread</div>}
                      {canRunFromCard(app.package) && (
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() => control('start', app.package)}
                          className="flex items-center gap-1 rounded-lg bg-rose-600 px-2 py-1 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                          data-testid={`dating-run-${app.package}`}
                          title={`Start only ${app.name}`}
                        >
                          <Play size={12} /> Start
                        </button>
                      )}
                    </div>
                  </div>
                  {canRunFromCard(app.package) && (
                  <div className="space-y-3 border-t border-line px-4 py-3">
                  {showsCount(app.package, runModes) && (
                    <label className="flex items-center justify-between gap-2 rounded bg-canvas-elev px-3 py-2 text-sm text-white">
                      <span>{runCountLabel(app.package)}</span>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={
                          countDrafts[app.package] ??
                          String(runCounts[app.package] ?? runCountFor(app.package, runCounts))
                        }
                        onChange={(e) =>
                          setCountDrafts((prev) => ({ ...prev, [app.package]: e.target.value }))
                        }
                        onBlur={(e) => saveRunCount(app.package, e.target.value)}
                        className="mr-input w-20 text-sm"
                        data-testid={`dating-run-count-${app.package}`}
                        aria-label={`${app.name} ${runCountLabel(app.package)}`}
                        title="Used by Start and by this app's Start button. Saved for this app."
                      />
                    </label>
                  )}
                  {hasRunMode(app.package) && (
                    <div
                      className="flex overflow-hidden rounded-lg border border-line text-xs"
                      data-testid={`dating-run-mode-${app.package}`}
                      role="group"
                      aria-label={`${app.name} run mode`}
                    >
                      {runModesOf(app.package).map((m) => (
                        <button
                          key={m.value}
                          type="button"
                          onClick={() => saveRunMode(app.package, m.value)}
                          className={`flex-1 px-2 py-1 ${
                            runModeFor(app.package, runModes) === m.value
                              ? 'bg-rose-600 text-white'
                              : 'bg-canvas-elev text-mute'
                          }`}
                        >
                          {m.label}
                        </button>
                      ))}
                    </div>
                  )}
                  {hasLikeCap(app.package, runModeFor(app.package, runModes)) &&
                    (() => {
                      const mode = runModeFor(app.package, runModes);
                      const key = likeCapKey(app.package, mode);
                      return (
                        <>
                          <label className="flex items-center justify-between gap-2 rounded bg-canvas-elev px-3 py-2 text-sm text-white">
                            <span>
                              Max likes (
                              {runModesOf(app.package).find((m) => m.value === mode)?.label || mode})
                            </span>
                            <input
                              type="text"
                              inputMode="numeric"
                              value={likeDrafts[key] ?? String(likeCapFor(app.package, mode, likeCaps))}
                              onChange={(e) =>
                                setLikeDrafts((prev) => ({ ...prev, [key]: e.target.value }))
                              }
                              onBlur={(e) => saveLikeCap(key, e.target.value)}
                              className="mr-input w-20 text-sm"
                              data-testid={`dating-like-cap-${app.package}-${mode}`}
                              aria-label={`${app.name} max likes`}
                              title="Saved separately for each mode."
                            />
                          </label>
                          <div
                            className={`-mt-1 px-3 text-xs ${likeErrors[key] ? 'text-red-300' : 'text-mute'}`}
                          >
                            {likeErrors[key] || likeCapHint(app.package, mode)}
                          </div>
                        </>
                      );
                    })()}
                  {showsCount(app.package, runModes) && (
                    <div
                      className={`-mt-1 px-3 text-xs ${countErrors[app.package] ? 'text-red-300' : 'text-mute'}`}
                      data-testid={`dating-run-count-hint-${app.package}`}
                    >
                      {countErrors[app.package] || runCountHint(app.package)}
                    </div>
                  )}
                  </div>
                  )}
                </div>
                  ))}
                </div>
                )}
              </section>
            );
            })}
      </div>

      {/* r44: schedule per-app / combo runs */}
      <DatingSchedules
        authHeaders={authHeaders}
        deviceId={deviceId}
        runCounts={runCounts}
        appName={(pkg) => datingAppDisplayName(pkg)}
      />

      {/* App toggles + persona - only on first run / when Working has none enabled */}
      {shouldShowAppsForStart(configApps) && (
      <div
        className="bg-surface border border-line rounded-lg space-y-4 overflow-hidden"
        data-testid="dating-apps-for-start"
      >
        <button
          type="button"
          className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-canvas-elev"
          aria-expanded={appsForStartExpanded}
          aria-controls="dating-apps-for-start-panel"
          data-testid="dating-apps-for-start-toggle"
          onClick={() => setAppsForStartExpanded((prev) => !prev)}
        >
          {appsForStartExpanded ? (
            <ChevronDown size={18} className="shrink-0 text-mute" aria-hidden />
          ) : (
            <ChevronRight size={18} className="shrink-0 text-mute" aria-hidden />
          )}
          <span className="min-w-0">
            <span className="block text-lg font-semibold text-white">Apps for Start</span>
            <span className="block text-xs text-mute">
              Tap an app to include it in Start. Templates/AI = how first messages are written.
            </span>
          </span>
        </button>
        {appsForStartExpanded && (
        <div
          id="dating-apps-for-start-panel"
          className="space-y-4 px-4 pb-4"
          role="region"
          aria-label="Apps for Start"
        >
        <div className="space-y-2" data-testid="dating-apps-for-start-list">
          {appsForStartRows(configApps, seedConfigApp, isSocialPackage).map(
            (app) => (
            <div
              key={app.package_name}
              className="flex flex-wrap items-center gap-2 justify-between rounded-xl border border-line bg-canvas-elev px-3 py-2"
              data-testid={`dating-app-for-start-${app.package_name}`}
            >
              <button
                type="button"
                onClick={() => toggleApp(app.package_name)}
                className={`px-3 py-1 rounded text-sm border ${
                  app.enabled
                    ? 'bg-rose-900/50 border-rose-600 text-rose-200'
                    : 'bg-surface border-line text-white'
                }`}
              >
                {datingAppDisplayName(app.package_name, app.name)}
              </button>
              <div
                className="flex overflow-hidden rounded-lg border border-line text-xs"
                data-testid={`dating-app-opener-mode-${app.package_name}`}
              >
                <button
                  type="button"
                  className={`px-2 py-1 ${
                    (app.opener_mode || openerMode) === 'templates'
                      ? 'bg-rose-700'
                      : 'bg-surface'
                  }`}
                  onClick={() => setAppOpenerMode(app.package_name, 'templates')}
                >
                  Templates
                </button>
                <button
                  type="button"
                  className={`px-2 py-1 ${
                    (app.opener_mode || openerMode) === 'ai'
                      ? 'bg-rose-700'
                      : 'bg-surface'
                  }`}
                  onClick={() => setAppOpenerMode(app.package_name, 'ai')}
                >
                  AI
                </button>
              </div>
            </div>
          )
          )}
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer select-none text-mute">AI opener persona</summary>
        <label className="block text-sm">
          Persona / style prompt (AI openers)
          <textarea
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            rows={4}
            className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2 font-mono text-sm"
          />
        </label>
        </details>
        <button
          onClick={saveConfig}
          disabled={loading}
          className="px-4 py-2 bg-accent hover:bg-accent-soft disabled:opacity-50 rounded"
        >
          Save config
        </button>
        </div>
        )}
      </div>
      )}

      {/* r44: rarely-changed settings, collapsed by default */}
      <details className="space-y-4" data-testid="dating-advanced">
        <summary className="cursor-pointer select-none rounded-lg border border-line bg-surface px-4 py-3 text-sm font-medium text-white">
          Advanced settings (openers, persona, date flow)
        </summary>
        <div className="space-y-4 pt-4">
      {/* Global opener mode */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">Openers</h3>
          <span className="text-xs text-mute">
            Slot now (London): {bucketNow} · enabled {enabledCount}/50
          </span>
        </div>
        <p className="text-sm text-mute">
          Templates save tokens on first-contact messages. Replies always use AI.
          Respects caps, humanizer timing, and safety auto-pause.
        </p>
        <div className="flex overflow-hidden rounded-xl border border-line max-w-md">
          <button
            type="button"
            className={`flex-1 px-3 py-2 text-sm ${
              openerMode === 'templates' ? 'bg-rose-600' : 'bg-canvas-elev'
            }`}
            onClick={() => setOpenerMode('templates')}
          >
            Templates
          </button>
          <button
            type="button"
            className={`flex-1 px-3 py-2 text-sm ${
              openerMode === 'ai' ? 'bg-rose-600' : 'bg-canvas-elev'
            }`}
            onClick={() => setOpenerMode('ai')}
          >
            AI
          </button>
        </div>
        <div className="text-xs text-mute flex flex-wrap gap-3">
          {Object.entries(bucketCounts).map(([b, n]) => (
            <span key={b}>
              {b}: {n}
            </span>
          ))}
        </div>
      </div>

      {/* Reply persona + date flow */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-4">
        <h3 className="text-lg font-semibold">Reply persona & date flow</h3>
        <p className="text-xs text-mute">
          AI replies to existing chats. After a warm chat window, one polite
          public-place invite - never stay-over / his home. After she agrees a
          date, ask WhatsApp first (then Snapchat if she declines). Then
          Needs-you handoff. Never auto-message WhatsApp/Snap - you continue
          personally.
        </p>
        {dateFlowStats ? (
          <div className="flex flex-wrap gap-4 text-sm">
            <span>Chats active: {dateFlowStats.chats_active}</span>
            <span>Invites sent: {dateFlowStats.invites_sent}</span>
            <span>Dates booked: {dateFlowStats.dates_booked}</span>
          </div>
        ) : null}
        <label className="block text-sm">
          Conversation style (replies)
          <textarea
            value={replyPersona}
            onChange={(e) => setReplyPersona(e.target.value)}
            rows={5}
            aria-label="Reply persona prompt"
            className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2 font-mono text-sm"
          />
        </label>
        <div className="grid sm:grid-cols-2 gap-3 text-sm">
          <label>
            Invite after (min days)
            <input
              type="number"
              min={1}
              value={inviteDaysMin}
              onChange={(e) => setInviteDaysMin(Number(e.target.value) || 1)}
              aria-label="Invite days minimum"
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
          <label>
            Invite after (max days)
            <input
              type="number"
              min={1}
              value={inviteDaysMax}
              onChange={(e) => setInviteDaysMax(Number(e.target.value) || 1)}
              aria-label="Invite days maximum"
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
          <label>
            Home location
            <input
              value={homeLocation}
              onChange={(e) => setHomeLocation(e.target.value)}
              aria-label="Home location"
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
          <label>
            Radius (miles)
            <input
              type="number"
              min={1}
              value={radiusMiles}
              onChange={(e) => setRadiusMiles(Number(e.target.value) || 1)}
              aria-label="Distance radius miles"
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={inviteEnabled}
              onChange={(e) => setInviteEnabled(e.target.checked)}
            />
            Date invites enabled
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={handoffEnabled}
              onChange={(e) => setHandoffEnabled(e.target.checked)}
            />
            Handoff on agree / logistics
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={calendarOnHandoff}
              onChange={(e) => setCalendarOnHandoff(e.target.checked)}
            />
            Calendar entry on booked date
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={contactAskEnabled}
              onChange={(e) => setContactAskEnabled(e.target.checked)}
              aria-label="Contact ask enabled"
            />
            Contact asks after date agree (WhatsApp → Snap)
          </label>
        </div>
        <label className="block text-sm">
          Ask order
          <select
            value={contactAskOrder.join(',')}
            disabled={!contactAskEnabled}
            aria-label="Contact ask order"
            onChange={(e) => {
              const v = e.target.value;
              if (v === 'snapchat,whatsapp') {
                setContactAskOrder(['snapchat', 'whatsapp']);
              } else if (v === 'whatsapp') {
                setContactAskOrder(['whatsapp']);
              } else if (v === 'snapchat') {
                setContactAskOrder(['snapchat']);
              } else {
                setContactAskOrder(['whatsapp', 'snapchat']);
              }
            }}
            className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2 text-sm disabled:opacity-50"
          >
            <option value="whatsapp,snapchat">WhatsApp first, then Snapchat</option>
            <option value="snapchat,whatsapp">Snapchat first, then WhatsApp</option>
            <option value="whatsapp">WhatsApp only</option>
            <option value="snapchat">Snapchat only</option>
          </select>
        </label>
        <label className="block text-sm">
          WhatsApp ask wording
          <textarea
            value={contactAskWhatsappText}
            onChange={(e) => setContactAskWhatsappText(e.target.value)}
            rows={2}
            disabled={!contactAskEnabled}
            aria-label="WhatsApp ask wording"
            className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2 text-sm disabled:opacity-50"
          />
        </label>
        <label className="block text-sm">
          Snapchat ask wording
          <textarea
            value={contactAskSnapchatText}
            onChange={(e) => setContactAskSnapchatText(e.target.value)}
            rows={2}
            disabled={!contactAskEnabled}
            aria-label="Snapchat ask wording"
            className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2 text-sm disabled:opacity-50"
          />
        </label>
        <p className="text-xs text-mute">
          Beyond {radiusMiles} mi → suggest meeting in {homeLocation} (public).
          Within radius → mutually convenient public place. Never suggest
          staying over. Decline first channel → ask second once; decline again or
          ignore → hand off.
        </p>
        <button
          onClick={saveConfig}
          disabled={loading}
          className="px-4 py-2 bg-accent hover:bg-accent-soft disabled:opacity-50 rounded"
        >
          Save reply & date flow
        </button>
      </div>

      {/* Template library editor */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-4">
        <h3 className="text-lg font-semibold">
          Opener library ({enabledCount} active)
        </h3>
        <p className="text-xs text-mute">
          Pick 2-50 active. Slots use Europe/London time: morning before 12:00,
          afternoon 12:00-17:00, evening after 17:00, plus any-time lines.
          Optional {'{name}'} only when the match name is known.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={newTemplateText}
            onChange={(e) => setNewTemplateText(e.target.value)}
            placeholder="New opener text"
            className="flex-1 bg-canvas-elev border border-line rounded px-3 py-2 text-sm"
          />
          <select
            value={newTemplateBucket}
            onChange={(e) => setNewTemplateBucket(e.target.value)}
            aria-label="New opener slot"
            data-testid="dating-opener-new-slot"
            className="bg-canvas-elev border border-line rounded px-3 py-2 text-sm"
          >
            <option value="morning">slot: morning</option>
            <option value="afternoon">slot: afternoon</option>
            <option value="evening">slot: evening</option>
            <option value="any">slot: any</option>
          </select>
          <button
            type="button"
            onClick={addTemplate}
            disabled={loading || !newTemplateText.trim()}
            className="px-3 py-2 bg-rose-700 hover:bg-rose-600 disabled:opacity-50 rounded text-sm"
          >
            Add
          </button>
        </div>
        <div className="max-h-80 overflow-y-auto space-y-2">
          {templates.map((t, idx) => (
            <div
              key={t.id}
              className="flex flex-col gap-2 rounded-xl border border-line bg-canvas-elev p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
                <span className="font-mono">{t.id}</span>
                <select
                  value={t.bucket}
                  onChange={(e) => {
                    const next = templates.map((x, i) =>
                      i === idx ? { ...x, bucket: e.target.value } : x
                    );
                    setTemplates(next);
                  }}
                  aria-label={`Slot for opener ${t.id}`}
                  data-testid={`dating-opener-slot-${t.id}`}
                  className="bg-surface border border-line rounded px-2 py-1"
                >
                  <option value="morning">slot: morning</option>
                  <option value="afternoon">slot: afternoon</option>
                  <option value="evening">slot: evening</option>
                  <option value="any">slot: any</option>
                </select>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={t.enabled}
                    onChange={(e) => {
                      const next = templates.map((x, i) =>
                        i === idx ? { ...x, enabled: e.target.checked } : x
                      );
                      setTemplates(next);
                    }}
                  />
                  enabled
                </label>
                <button
                  type="button"
                  className="ml-auto text-red-300 hover:text-red-200"
                  onClick={() => {
                    const next = templates.filter((_, i) => i !== idx);
                    void saveTemplates(next);
                  }}
                >
                  Delete
                </button>
              </div>
              <textarea
                value={t.text}
                rows={2}
                onChange={(e) => {
                  const next = templates.map((x, i) =>
                    i === idx ? { ...x, text: e.target.value } : x
                  );
                  setTemplates(next);
                }}
                className="w-full bg-surface border border-line rounded px-3 py-2 text-sm"
              />
            </div>
          ))}
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => saveTemplates(templates)}
          className="px-4 py-2 bg-accent hover:bg-accent-soft disabled:opacity-50 rounded"
        >
          Save library
        </button>
      </div>

        </div>
      </details>
    </div>
  );
}
