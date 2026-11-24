import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Heart, Play, Pause, Square, RefreshCw } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import ModeSpeedPicker from '../components/ModeSpeedPicker';
import LiveActivityFeed, {
  ActivityPayload,
} from '../components/LiveActivityFeed';
import {
  canRunApp,
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

function ProgressBar({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-mute">
        <span>{label}</span>
        <span>
          {value}/{max || '—'} ({pct}%)
        </span>
      </div>
      <div className="h-2 bg-surface-elev rounded overflow-hidden">
        <div
          className="h-full bg-rose-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function omitKey<T>(o: Record<string, T>, k: string): Record<string, T> {
  const out = { ...o };
  delete out[k];
  return out;
}

export default function DatingPage() {
  const [status, setStatus] = useState<DatingStatus | null>(null);
  const [apps, setApps] = useState<AppStats[]>([]);
  const [configApps, setConfigApps] = useState<AppConfig[]>([]);
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
    'Would it be easier to chat on WhatsApp? Totally optional — no pressure either way.'
  );
  const [contactAskSnapchatText, setContactAskSnapchatText] = useState(
    'No worries — would Snapchat be easier instead? Totally optional, only if you like.'
  );
  const [dateFlowStats, setDateFlowStats] = useState<{
    chats_active: number;
    invites_sent: number;
    dates_booked: number;
    by_app?: Record<string, { chats_active: number; invites_sent: number; dates_booked: number }>;
  } | null>(null);
  const [globalMin, setGlobalMin] = useState(100);
  const [globalMax, setGlobalMax] = useState(500);
  const [todayMessages, setTodayMessages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  const [dryRun, setDryRun] = useState(true);
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
  const [contactScope, setContactScope] = useState<'new' | 'existing' | 'both'>(
    'both'
  );
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
  const [selectorApps, setSelectorApps] = useState<
    {
      package_name: string;
      version_code: string;
      total_llm_calls: number;
      last_discovered_at?: string | null;
      max_layout_variants?: number;
      roles: {
        role: string;
        source: string;
        llm_calls: number;
        discovered_at: string;
        variant_count?: number;
        nav_path?: { kind?: string; direction?: string; count?: number }[];
        variants?: {
          id?: string;
          label?: string;
          hits?: number;
          misses?: number;
          success_rate?: number;
          source?: string;
          selector?: { resource_id?: string; text?: string; hint?: string };
        }[];
      }[];
    }[]
  >([]);

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
      // Core dating endpoints must succeed; queue/selectors are soft so a
      // missing Lambda module never blanks the whole page as "not connected".
      const [statusRes, statsRes, configRes, openersRes] = await Promise.all([
        axios.get(`${getBackendUrl()}/api/dating/status`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/stats`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/config`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/openers`, {
          headers: authHeaders(),
        }),
      ]);
      type SelectorApp = (typeof selectorApps)[number];
      const selData = await soft<{ apps?: SelectorApp[] }>(
        '/api/selectors/status',
        { apps: [] }
      );
      const rc = await soft<{
        counts?: Record<string, number>;
        modes?: Record<string, string>;
        like_caps?: Record<string, number>;
      }>('/api/dating/run-counts', { counts: {}, modes: {}, like_caps: {} });
      setRunCounts(rc.counts || {});
      setRunModes(rc.modes || {});
      setLikeCaps(rc.like_caps || {});
      setStatus(statusRes.data);
      setApps(statsRes.data.apps || []);
      setTodayMessages(statsRes.data.today?.messages || 0);
      setConfigApps(configRes.data.apps || []);
      setPersona(configRes.data.persona_prompt || '');
      const df = configRes.data.date_flow || {};
      setReplyPersona(
        df.reply_persona_prompt || configRes.data.reply_persona_prompt || ''
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
      setDateFlowStats(configRes.data.date_flow_stats || null);
      setGlobalMin(configRes.data.min_total_messages_per_day ?? 100);
      setGlobalMax(configRes.data.max_total_messages_per_day ?? 500);
      if (['fast', 'balanced', 'careful'].includes(configRes.data.speed_preset)) {
        setSpeed(configRes.data.speed_preset);
      }
      if (
        configRes.data.opener_mode === 'templates' ||
        configRes.data.opener_mode === 'ai'
      ) {
        setOpenerMode(configRes.data.opener_mode);
      }
      setTemplates(openersRes.data.library?.templates || []);
      setBucketNow(openersRes.data.bucket_now || 'morning');
      setBucketCounts(openersRes.data.bucket_counts || {});
      setSelectorApps(selData.apps || []);
      setActivity(statusRes.data.activity || null);
      setError(null);
    } catch (e: unknown) {
      console.error(e);
      setError('Failed to load dating mode. Is the backend running and authenticated?');
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
    action: 'start' | 'stop' | 'pause',
    onlyApp?: string
  ) => {
    setLoading(true);
    try {
      if (action === 'start') {
        // Clear stale "running" from a stopped job so Start is never stuck
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
              dryRun,
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
          min_total_messages_per_day: globalMin,
          max_total_messages_per_day: globalMax,
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
      alert('Keep 2–50 templates enabled');
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
            <Heart className="text-rose-400 shrink-0" /> Run
          </h1>
          <p className="text-mute mt-1 text-sm sm:text-base">
            MacMobileRun · app selection, dry-run, openers, start/stop, activity
          </p>
          <p className="text-mute mt-1 text-sm">
            Covers new contacts, existing chats, or both — dating here,{' '}
            <Link to="/social" className="text-accent underline underline-offset-2">
              Social
            </Link>{' '}
            for unread chat follow-ups.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={`min-h-[44px] inline-flex items-center px-3 py-2 rounded text-sm ${
              status?.running && !status.paused
                ? 'bg-green-900 text-green-300'
                : status?.paused
                  ? 'bg-yellow-900 text-yellow-300'
                  : 'bg-surface-elev text-mute'
            }`}
          >
            {statusLabel}
            {status?.current_app ? ` · ${status.current_app}` : ''}
          </span>
          <button
            onClick={() => loadAll()}
            className="tap-target rounded-xl bg-surface-elev hover:bg-gray-600"
            title="Refresh"
            aria-label="Refresh"
          >
            <RefreshCw size={18} />
          </button>
        </div>
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

      {/* Controls — stack on phone for one-handed use */}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
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
            disabled={loading || !status?.running}
            onClick={() => control('pause')}
            className="tap-target flex items-center justify-center gap-2 rounded-xl bg-yellow-700 px-3 text-sm font-medium hover:bg-yellow-600 disabled:opacity-50"
          >
            <Pause size={16} /> {status?.paused ? 'Resume' : 'Pause'}
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
        <label className="tap-target flex items-center gap-2 text-sm text-mute">
          <input
            type="checkbox"
            className="h-5 w-5 accent-rose-500"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            data-testid="dating-dry-run"
          />
          Dry-run (no real likes/messages)
        </label>
        <label className="flex w-full flex-col gap-1 text-sm text-mute sm:w-auto sm:flex-row sm:items-center sm:gap-2">
          Contacts
          <select
            className="mr-input text-sm sm:min-w-[12rem]"
            value={contactScope}
            onChange={(e) =>
              setContactScope(e.target.value as 'new' | 'existing' | 'both')
            }
            data-testid="dating-contact-scope"
            aria-label="Contact scope"
          >
            <option value="new">New (openers / first message)</option>
            <option value="existing">Existing chats</option>
            <option value="both">Both</option>
          </select>
        </label>
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
      />

      {/* Global progress */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="text-lg font-semibold">Today · All Apps</h3>
        <ProgressBar
          value={todayMessages}
          max={globalMax}
          label={`Auto messages (openers + replies) · target range ${globalMin}–${globalMax}`}
        />
      </div>

      {/* Per-app stats */}
      <div className="grid md:grid-cols-2 gap-4">
        {cardsForDatingApps(apps, configApps)
          .filter((app) => !isSocialPackage(app.package))
          .map((app) => (
          <div
            key={app.package}
            className="bg-surface border border-line rounded-lg p-4 space-y-3"
          >
            <div className="flex justify-between items-start">
              <div>
                <h4 className="font-semibold text-lg text-white">{app.name}</h4>
              </div>
              <div className="flex flex-col items-end gap-1 text-right text-sm text-mute">
                <div>{app.inbox.unread} unread</div>
                {canRunApp(app.package) && (
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => control('start', app.package)}
                    className="flex items-center gap-1 rounded-lg bg-rose-600 px-2 py-1 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                    data-testid={`dating-run-${app.package}`}
                    title={`Run only ${app.name}`}
                  >
                    <Play size={12} /> Run
                  </button>
                )}
              </div>
            </div>
            {canRunApp(app.package) && showsCount(app.package, runModes) && (
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
                  title="Used by Start and by this app's Run button. Saved for this app."
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
            {canRunApp(app.package) && showsCount(app.package, runModes) && (
              <div
                className={`-mt-1 px-3 text-xs ${countErrors[app.package] ? 'text-red-300' : 'text-mute'}`}
                data-testid={`dating-run-count-hint-${app.package}`}
              >
                {countErrors[app.package] || runCountHint(app.package)}
              </div>
            )}
            <details className="text-sm text-mute">
              <summary className="cursor-pointer select-none">
                Today: {app.today.swipes} swipes · {app.today.openers} openers ·{' '}
                {app.today.replies} replies
              </summary>
              <div className="pt-2">
                <ProgressBar
                  value={app.targets.opener_progress}
                  max={app.targets.opener_target || 75}
                  label="Openers vs daily target"
                />
              </div>
            </details>
          </div>
        ))}
      </div>

      {/* r44: schedule per-app / combo runs */}
      <DatingSchedules
        authHeaders={authHeaders}
        deviceId={deviceId}
        dryRun={dryRun}
        runCounts={runCounts}
        appName={(pkg) => datingAppDisplayName(pkg)}
      />

      {/* App toggles + persona */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-4">
        <h3 className="text-lg font-semibold">Apps for Start</h3>
        <p className="text-xs text-mute">Tap an app to include it in Start. Templates/AI = how first messages are written.</p>
        <div className="space-y-2">
          {sortDatingApps(configApps, (a) => a.package_name)
            .filter((app) => !isSocialPackage(app.package_name))
            .map((app) => (
            <div
              key={app.package_name}
              className="flex flex-wrap items-center gap-2 justify-between rounded-xl border border-line bg-canvas-elev px-3 py-2"
            >
              <button
                onClick={() => toggleApp(app.package_name)}
                className={`px-3 py-1 rounded text-sm border ${
                  app.enabled
                    ? 'bg-rose-900/50 border-rose-600 text-rose-200'
                    : 'bg-surface border-line text-white'
                }`}
              >
                {datingAppDisplayName(app.package_name, app.name)}
              </button>
              <div className="flex overflow-hidden rounded-lg border border-line text-xs">
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
          ))}
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

      {/* r44: rarely-changed settings, collapsed by default */}
      <details className="space-y-4" data-testid="dating-advanced">
        <summary className="cursor-pointer select-none rounded-lg border border-line bg-surface px-4 py-3 text-sm font-medium text-white">
          Advanced settings (daily limits, openers, persona, date flow, selector cache)
        </summary>
        <div className="space-y-4 pt-4">
      {/* Global daily limits */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="text-lg font-semibold">Daily message limits</h3>
        <div className="grid grid-cols-2 gap-4">
          <label className="text-sm">
            Global min/day
            <input
              type="number"
              value={globalMin}
              onChange={(e) => setGlobalMin(Number(e.target.value))}
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Global max/day
            <input
              type="number"
              value={globalMax}
              onChange={(e) => setGlobalMax(Number(e.target.value))}
              className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
            />
          </label>
        </div>
        <p className="text-xs text-mute">Saved with “Save config” under Apps.</p>
      </div>

      {/* Global opener mode */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold">Openers</h3>
          <span className="text-xs text-mute">
            Bucket now: {bucketNow} · enabled {enabledCount}/50
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
          public-place invite — never stay-over / his home. After she agrees a
          date, ask WhatsApp first (then Snapchat if she declines). Then
          Needs-you handoff. Never auto-message WhatsApp/Snap — you continue
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
          Pick 2–50 active. Morning / afternoon / evening buckets + time-neutral.
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
            aria-label="New opener bucket"
            className="bg-canvas-elev border border-line rounded px-3 py-2 text-sm"
          >
            <option value="morning">morning</option>
            <option value="afternoon">afternoon</option>
            <option value="evening">evening</option>
            <option value="any">any</option>
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
                  aria-label={`Bucket for opener ${t.id}`}
                  className="bg-surface border border-line rounded px-2 py-1"
                >
                  <option value="morning">morning</option>
                  <option value="afternoon">afternoon</option>
                  <option value="evening">evening</option>
                  <option value="any">any</option>
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

      {/* Selector cache status */}
      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="text-lg font-semibold">Selector cache</h3>
        <p className="text-xs text-mute">
          Multiple layout variants per app version (default up to{' '}
          {selectorApps[0]?.max_layout_variants ?? 4}, min 2). Tried by success
          rate — no LLM when any variant matches. Off-screen targets use scroll
          explore; failures escalate to Needs you.
        </p>
        {selectorApps.length === 0 ? (
          <p className="text-sm text-mute">No cached apps yet.</p>
        ) : (
          selectorApps.map((app) => (
            <div
              key={`${app.package_name}@${app.version_code}`}
              className="rounded-xl border border-line bg-canvas-elev p-3 text-sm space-y-2"
            >
              <div className="flex flex-wrap justify-between gap-2">
                <span className="font-medium">
                  {app.package_name}{' '}
                  <span className="text-mute">v{app.version_code}</span>
                </span>
                <span className="text-mute">
                  LLM calls: {app.total_llm_calls} · cap{' '}
                  {app.max_layout_variants ?? 4} variants · last{' '}
                  {app.last_discovered_at
                    ? new Date(app.last_discovered_at).toLocaleString()
                    : '—'}
                </span>
              </div>
              <ul className="text-xs text-mute space-y-2">
                {(app.roles || []).map((r) => (
                  <li key={r.role} className="space-y-1">
                    <div>
                      {r.role}: {r.source} · {r.variant_count ?? 1} variant
                      {(r.variant_count ?? 1) === 1 ? '' : 's'} (llm {r.llm_calls})
                    </div>
                    {(r.variants || []).length > 0 ? (
                      <ul className="pl-3 space-y-0.5 border-l border-line">
                        {r.variants!.map((v, i) => (
                          <li key={v.id || i}>
                            {v.label || v.selector?.resource_id?.split('/').pop() || v.id || `variant ${i + 1}`}
                            : hits {v.hits ?? 0} / misses {v.misses ?? 0}
                            {typeof v.success_rate === 'number'
                              ? ` (${Math.round(v.success_rate * 100)}%)`
                              : ''}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </div>
        </div>
      </details>
    </div>
  );
}
