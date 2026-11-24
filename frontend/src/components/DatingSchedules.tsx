/** r44: schedule dating runs — one app, or a combo with runs per app. */
import { useEffect, useState } from 'react';
import axios from 'axios';
import { CalendarClock, Pencil, Plus, Trash2 } from 'lucide-react';
import { getBackendUrl } from '../config';
import {
  RUNNABLE_APPS,
  parseCountInput,
  hasRunMode,
  parseRunCount,
  runCountFor,
  runCountHint,
  hasLikeCap,
  runModeFor,
  runModesOf,
  parseLikeCap,
  likeCapHint,
  DEFAULT_LIKES,
} from '../lib/datingRun';
import {
  DAY_LABELS,
  DatingSchedule,
  MAX_RUNS_PER_APP,
  scheduleBody,
  scheduleSummary,
  validTime,
} from '../lib/datingSchedule';

type Props = {
  authHeaders: () => Record<string, string>;
  deviceId: string;
  dryRun: boolean;
  runCounts: Record<string, number>;
  appName: (pkg: string) => string;
};

const blank = (p: Props): DatingSchedule => ({
  enabled: true,
  items: [],
  time: '20:00',
  days: [],
  dry_run: p.dryRun,
  device_id: p.deviceId,
});

export default function DatingSchedules(props: Props) {
  const { authHeaders, appName } = props;
  const [list, setList] = useState<DatingSchedule[]>([]);
  const [edit, setEdit] = useState<DatingSchedule | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // r45: typed Runs / Per-run text, keyed "pkg:runs" / "pkg:count"
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const startEdit = (s: DatingSchedule | null) => {
    setDrafts({});
    setErr(null);
    setEdit(s);
  };
  const url = `${getBackendUrl()}/api/dating/schedules`;

  const load = async () => {
    try {
      const r = await axios.get(url, { headers: authHeaders() });
      setList(r.data.schedules || []);
    } catch {
      /* page shows the main error */
    }
  };
  useEffect(() => {
    load();
  }, []);

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      await load();
      return true;
    } catch (e) {
      setErr(
        axios.isAxiosError(e)
          ? String(e.response?.data?.detail || e.message)
          : 'Could not save schedule'
      );
      return false;
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!edit) return;
    if (!edit.items.length) return setErr('Pick at least one app');
    if (!validTime(edit.time)) return setErr('Time must be HH:MM');
    // r45: validate typed numbers on Save only
    const errs: string[] = [];
    const items = edit.items.map((i) => {
      const name = appName(i.app);
      const rr = parseCountInput(
        drafts[`${i.app}:runs`] ?? String(i.runs),
        MAX_RUNS_PER_APP,
        `${name} runs`
      );
      const rc = parseRunCount(i.app, drafts[`${i.app}:count`] ?? String(i.count), `${name} per run`);
      if (!rr.ok) errs.push(rr.error);
      if (!rc.ok) errs.push(rc.error);
      let likes = i.likes;
      if (hasLikeCap(i.app)) {
        const rl = parseLikeCap(drafts[`${i.app}:likes`] ?? String(i.likes ?? DEFAULT_LIKES));
        if (!rl.ok) errs.push(`${name} ${rl.error}`);
        else likes = rl.n;
      }
      return { ...i, runs: rr.ok ? rr.n : i.runs, count: rc.ok ? rc.n : i.count, likes };
    });
    if (errs.length) return setErr(errs.join(' · '));
    const body = scheduleBody({ ...edit, items, device_id: edit.device_id || props.deviceId });
    const ok = await call(() =>
      edit.id
        ? axios.put(`${url}/${edit.id}`, body, { headers: authHeaders() })
        : axios.post(url, body, { headers: authHeaders() })
    );
    if (ok) startEdit(null);
  };

  const toggleItem = (pkg: string) => {
    if (!edit) return;
    const has = edit.items.some((i) => i.app === pkg);
    setEdit({
      ...edit,
      items: has
        ? edit.items.filter((i) => i.app !== pkg)
        : [...edit.items, { app: pkg, runs: 1, count: runCountFor(pkg, props.runCounts) }],
    });
  };
  const setDraft = (pkg: string, key: 'runs' | 'count' | 'likes', v: string) =>
    setDrafts((prev) => ({ ...prev, [`${pkg}:${key}`]: v }));

  return (
    <div className="bg-surface border border-line rounded-lg p-4 space-y-3" data-testid="dating-schedules">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
          <CalendarClock size={18} /> Schedules
        </h3>
        <button
          type="button"
          disabled={busy}
          onClick={() => startEdit(blank(props))}
          className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1 text-sm text-white hover:bg-rose-500 disabled:opacity-50"
          data-testid="schedule-new"
        >
          <Plus size={14} /> New
        </button>
      </div>
      <p className="text-xs text-mute">
        London time. Apps run one after another, like Start. A schedule is
        skipped if a run is already going or the phone is offline.
      </p>
      {err && <div className="text-sm text-red-300">{err}</div>}

      {list.length === 0 && !edit && (
        <p className="text-sm text-mute">No schedules yet.</p>
      )}
      {list.map((s) => (
        <div
          key={s.id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-canvas-elev px-3 py-2 text-sm"
        >
          <div className="min-w-0">
            <div className="font-medium text-white">{s.name}</div>
            <div className="text-xs text-mute">{scheduleSummary(s, appName)}</div>
            <div className="text-xs text-mute">
              Next: {s.enabled ? s.next_run_label || '—' : 'off'}
              {s.last_result ? ` · Last: ${s.last_result}` : ''}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-xs text-mute">
              <input
                type="checkbox"
                checked={s.enabled}
                disabled={busy}
                onChange={() =>
                  call(() =>
                    axios.put(
                      `${url}/${s.id}`,
                      { enabled: !s.enabled },
                      { headers: authHeaders() }
                    )
                  )
                }
              />
              On
            </label>
            <button type="button" title="Edit" onClick={() => startEdit({ ...s })}>
              <Pencil size={14} />
            </button>
            <button
              type="button"
              title="Delete"
              disabled={busy}
              onClick={() =>
                window.confirm(`Delete schedule "${s.name}"?`) &&
                call(() => axios.delete(`${url}/${s.id}`, { headers: authHeaders() }))
              }
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      ))}

      {edit && (
        <div className="space-y-3 rounded-xl border border-rose-700 bg-canvas-elev p-3 text-sm">
          <input
            className="mr-input w-full text-sm"
            placeholder="Name (optional)"
            value={edit.name || ''}
            onChange={(e) => setEdit({ ...edit, name: e.target.value })}
          />
          <div className="space-y-1">
            <div className="text-xs text-mute">
              Apps — pick one, or several for a combo. Runs = times the app
              runs; per run = swipes/messages each time.
            </div>
            {RUNNABLE_APPS.map((pkg) => {
              const it = edit.items.find((i) => i.app === pkg);
              return (
                <div key={pkg} className="flex flex-wrap items-center gap-2">
                  <label className="flex w-40 items-center gap-2 text-white">
                    <input type="checkbox" checked={!!it} onChange={() => toggleItem(pkg)} />
                    {appName(pkg)}
                  </label>
                  {it && (
                    <>
                      <label className="flex items-center gap-1 text-xs text-mute">
                        Runs
                        <input
                          type="text"
                          inputMode="numeric"
                          value={drafts[`${pkg}:runs`] ?? String(it.runs)}
                          onChange={(e) => setDraft(pkg, 'runs', e.target.value)}
                          className="mr-input w-16 text-sm"
                          title={`Max ${MAX_RUNS_PER_APP} runs`}
                          data-testid={`schedule-runs-${pkg}`}
                        />
                      </label>
                      <label className="flex items-center gap-1 text-xs text-mute">
                        Per run
                        <input
                          type="text"
                          inputMode="numeric"
                          value={drafts[`${pkg}:count`] ?? String(it.count)}
                          onChange={(e) => setDraft(pkg, 'count', e.target.value)}
                          className="mr-input w-20 text-sm"
                          title={runCountHint(pkg)}
                          data-testid={`schedule-count-${pkg}`}
                        />
                      </label>
                      {hasRunMode(pkg) && (
                        <select
                          value={runModeFor(pkg, { [pkg]: it.mode || '' })}
                          onChange={(e) =>
                            setEdit({
                              ...edit,
                              items: edit.items.map((i) =>
                                i.app === pkg
                                  ? { ...i, mode: runModeFor(pkg, { [pkg]: e.target.value }) }
                                  : i
                              ),
                            })
                          }
                          className="mr-input text-xs"
                          data-testid={`schedule-mode-${pkg}`}
                          aria-label={`${appName(pkg)} mode`}
                        >
                          {runModesOf(pkg).map((m) => (
                            <option key={m.value} value={m.value}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      )}
                      {hasLikeCap(pkg) && (
                        <label className="flex items-center gap-1 text-xs text-mute">
                          Max likes
                          <input
                            type="text"
                            inputMode="numeric"
                            value={drafts[`${pkg}:likes`] ?? String(it.likes ?? DEFAULT_LIKES)}
                            onChange={(e) => setDraft(pkg, 'likes', e.target.value)}
                            className="mr-input w-20 text-sm"
                            title={likeCapHint(pkg, runModeFor(pkg, { [pkg]: it.mode || '' }))}
                            data-testid={`schedule-likes-${pkg}`}
                          />
                        </label>
                      )}
                      <span className="text-xs text-mute">
                        runs max {MAX_RUNS_PER_APP} · {runCountHint(pkg)}
                      </span>
                    </>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1 text-xs text-mute">
              Time
              <input
                type="time"
                value={edit.time}
                onChange={(e) => setEdit({ ...edit, time: e.target.value })}
                className="mr-input text-sm"
                data-testid="schedule-time"
              />
            </label>
            <div className="flex flex-wrap gap-1">
              {DAY_LABELS.map((d, i) => {
                const on = edit.days.includes(i);
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() =>
                      setEdit({
                        ...edit,
                        days: on ? edit.days.filter((x) => x !== i) : [...edit.days, i],
                      })
                    }
                    className={`rounded px-2 py-0.5 text-xs ${on ? 'bg-rose-700 text-white' : 'bg-surface text-mute'}`}
                  >
                    {d}
                  </button>
                );
              })}
              <span className="text-xs text-mute self-center">(none = every day)</span>
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs text-mute">
            <input
              type="checkbox"
              checked={edit.dry_run}
              onChange={(e) => setEdit({ ...edit, dry_run: e.target.checked })}
            />
            Dry run (no real likes or messages)
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={save}
              className="rounded bg-rose-600 px-3 py-1 text-white hover:bg-rose-500 disabled:opacity-50"
              data-testid="schedule-save"
            >
              Save schedule
            </button>
            <button type="button" onClick={() => startEdit(null)} className="rounded bg-surface px-3 py-1">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
