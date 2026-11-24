/** r44: schedule dating runs — one app, or a combo with runs per app. */
import { useEffect, useState } from 'react';
import axios from 'axios';
import { CalendarClock, Pencil, Plus, Trash2 } from 'lucide-react';
import { getBackendUrl } from '../config';
import { RUNNABLE_APPS, runCountFor, runCountCap } from '../lib/datingRun';
import {
  DAY_LABELS,
  DatingSchedule,
  MAX_RUNS_PER_APP,
  clampRuns,
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
    const body = scheduleBody({ ...edit, device_id: edit.device_id || props.deviceId });
    const ok = await call(() =>
      edit.id
        ? axios.put(`${url}/${edit.id}`, body, { headers: authHeaders() })
        : axios.post(url, body, { headers: authHeaders() })
    );
    if (ok) setEdit(null);
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
  const setItem = (pkg: string, key: 'runs' | 'count', v: number) =>
    edit &&
    setEdit({
      ...edit,
      items: edit.items.map((i) => (i.app === pkg ? { ...i, [key]: v } : i)),
    });

  return (
    <div className="bg-surface border border-line rounded-lg p-4 space-y-3" data-testid="dating-schedules">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
          <CalendarClock size={18} /> Schedules
        </h3>
        <button
          type="button"
          disabled={busy}
          onClick={() => setEdit(blank(props))}
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
            <button type="button" title="Edit" onClick={() => setEdit({ ...s })}>
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
                          type="number"
                          min={1}
                          max={MAX_RUNS_PER_APP}
                          value={it.runs}
                          onChange={(e) => setItem(pkg, 'runs', clampRuns(e.target.value))}
                          className="mr-input w-16 text-sm"
                        />
                      </label>
                      <label className="flex items-center gap-1 text-xs text-mute">
                        Per run
                        <input
                          type="number"
                          min={1}
                          max={runCountCap(pkg)}
                          value={it.count}
                          onChange={(e) =>
                            setItem(pkg, 'count', Math.max(1, Math.min(runCountCap(pkg), Number(e.target.value) || 1)))
                          }
                          className="mr-input w-20 text-sm"
                        />
                      </label>
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
            <button type="button" onClick={() => setEdit(null)} className="rounded bg-surface px-3 py-1">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
