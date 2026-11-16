import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, Pencil, Trash2, RefreshCw } from 'lucide-react';
import axios from 'axios';
import { getAuthToken, getBackendUrl } from '../config';

type MatchRow = {
  match_id: string;
  name: string;
  app: string;
  package_name: string;
  date_agreed: string;
  distance_miles?: number | null;
  whatsapp: string;
  snapchat: string;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
};

type SortKey =
  | 'name'
  | 'app'
  | 'date_agreed'
  | 'whatsapp'
  | 'snapchat'
  | 'status'
  | 'updated_at'
  | 'distance_miles';

const STATUS_LABEL: Record<string, string> = {
  chatting: 'Chatting',
  invited: 'Invited',
  booked: 'Booked',
  handed_off: 'Handed off',
};

export default function MatchesPage() {
  const [rows, setRows] = useState<MatchRow[]>([]);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<SortKey>('updated_at');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<MatchRow | null>(null);

  const authHeaders = useCallback(
    () => ({ Authorization: `Bearer ${getAuthToken()}` }),
    []
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${getBackendUrl()}/api/dating/matches`, {
        headers: authHeaders(),
        params: { q, sort, order },
      });
      setRows(res.data.matches || []);
      setError(null);
    } catch (e: unknown) {
      console.error(e);
      setError('Failed to load matches (auth required).');
    } finally {
      setLoading(false);
    }
  }, [authHeaders, q, sort, order]);

  useEffect(() => {
    load();
  }, [load]);

  const toggleSort = (key: SortKey) => {
    if (sort === key) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSort(key);
      setOrder(key === 'name' || key === 'app' ? 'asc' : 'desc');
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    setLoading(true);
    try {
      await axios.put(
        `${getBackendUrl()}/api/dating/matches/${encodeURIComponent(editing.match_id)}`,
        {
          name: editing.name,
          app: editing.app,
          package_name: editing.package_name,
          date_agreed: editing.date_agreed,
          distance_miles: editing.distance_miles,
          whatsapp: editing.whatsapp,
          snapchat: editing.snapchat,
          status: editing.status,
          notes: editing.notes,
        },
        {
          headers: authHeaders(),
          params: { package_name: editing.package_name || '' },
        }
      );
      setEditing(null);
      await load();
    } catch (e) {
      console.error(e);
      alert('Failed to save match');
    } finally {
      setLoading(false);
    }
  };

  const remove = async (row: MatchRow) => {
    if (!confirm(`Delete match ${row.name || row.match_id}?`)) return;
    setLoading(true);
    try {
      await axios.delete(
        `${getBackendUrl()}/api/dating/matches/${encodeURIComponent(row.match_id)}`,
        {
          headers: authHeaders(),
          params: { package_name: row.package_name || '' },
        }
      );
      await load();
    } catch (e) {
      console.error(e);
      alert('Failed to delete match');
    } finally {
      setLoading(false);
    }
  };

  const exportCsv = async () => {
    try {
      const res = await axios.get(
        `${getBackendUrl()}/api/dating/matches/export.csv`,
        {
          headers: authHeaders(),
          params: { q, sort, order },
          responseType: 'blob',
        }
      );
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'matches.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      alert('Export failed');
    }
  };

  const sortMark = useMemo(() => (order === 'asc' ? ' ↑' : ' ↓'), [order]);

  const th = (key: SortKey, label: string) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-mute cursor-pointer select-none whitespace-nowrap"
      onClick={() => toggleSort(key)}
    >
      {label}
      {sort === key ? sortMark : ''}
    </th>
  );

  return (
    <div className="p-4 md:p-6 space-y-4 pb-24 md:pb-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Matches</h1>
          <p className="text-sm text-mute mt-1">
            Private to your account — WhatsApp / Snap never auto-messaged. Contacts
            are not written to plaintext logs.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded border border-line bg-surface text-sm"
          >
            <RefreshCw size={14} /> Refresh
          </button>
          <button
            type="button"
            onClick={exportCsv}
            className="inline-flex items-center gap-2 px-3 py-2 rounded bg-accent hover:bg-accent-soft text-sm"
          >
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      <label className="block text-sm max-w-md">
        Search
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Name, WhatsApp, Snap, app, notes…"
          aria-label="Search matches"
          className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
        />
      </label>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <div className="overflow-x-auto border border-line rounded-lg bg-surface">
        <table className="min-w-full text-sm">
          <thead className="border-b border-line bg-canvas-elev/60">
            <tr>
              {th('name', 'Name')}
              {th('app', 'App')}
              {th('date_agreed', 'Date agreed')}
              {th('distance_miles', 'Distance')}
              {th('whatsapp', 'WhatsApp')}
              {th('snapchat', 'Snapchat')}
              {th('status', 'Status')}
              {th('updated_at', 'Updated')}
              <th className="px-3 py-2 text-left text-xs text-mute">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-mute">
                  {loading ? 'Loading…' : 'No matches yet.'}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={`${r.package_name}:${r.match_id}`} className="border-t border-line">
                  <td className="px-3 py-2 font-medium">{r.name || '—'}</td>
                  <td className="px-3 py-2 text-mute">{r.app || r.package_name || '—'}</td>
                  <td className="px-3 py-2 max-w-[14rem] truncate" title={r.date_agreed}>
                    {r.date_agreed || '—'}
                  </td>
                  <td className="px-3 py-2">
                    {r.distance_miles != null ? `${r.distance_miles} mi` : '—'}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{r.whatsapp || '—'}</td>
                  <td className="px-3 py-2 font-mono text-xs">{r.snapchat || '—'}</td>
                  <td className="px-3 py-2">
                    {STATUS_LABEL[r.status] || r.status || '—'}
                  </td>
                  <td className="px-3 py-2 text-mute text-xs whitespace-nowrap">
                    {(r.updated_at || '').slice(0, 19).replace('T', ' ') || '—'}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        aria-label={`Edit ${r.name || r.match_id}`}
                        onClick={() => setEditing({ ...r })}
                        className="p-1.5 rounded border border-line hover:bg-surface-elev"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete ${r.name || r.match_id}`}
                        onClick={() => remove(r)}
                        className="p-1.5 rounded border border-line hover:bg-rose-500/20"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg bg-surface border border-line rounded-lg p-4 space-y-3">
            <h2 className="text-lg font-semibold">Edit match</h2>
            {(
              [
                ['name', 'Name'],
                ['app', 'App'],
                ['date_agreed', 'Date agreed (day/time/place)'],
                ['whatsapp', 'WhatsApp'],
                ['snapchat', 'Snapchat'],
                ['notes', 'Notes'],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block text-sm">
                {label}
                <input
                  value={String(editing[key] || '')}
                  onChange={(e) =>
                    setEditing({ ...editing, [key]: e.target.value })
                  }
                  className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
                />
              </label>
            ))}
            <label className="block text-sm">
              Distance (miles)
              <input
                type="number"
                value={editing.distance_miles ?? ''}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    distance_miles:
                      e.target.value === '' ? null : Number(e.target.value),
                  })
                }
                className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              Status
              <select
                value={editing.status || 'chatting'}
                onChange={(e) => setEditing({ ...editing, status: e.target.value })}
                className="mt-1 w-full bg-canvas-elev border border-line rounded px-3 py-2"
              >
                {Object.entries(STATUS_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="px-3 py-2 rounded border border-line text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveEdit}
                disabled={loading}
                className="px-3 py-2 rounded bg-accent text-sm"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
