import { useEffect, useState } from 'react';
import axios from 'axios';
import { getAuthToken, getBackendUrl } from '../config';

type DailyRow = {
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  requests: number;
};

type UsagePayload = {
  timezone: string;
  days: number;
  from: string;
  to: string;
  totals: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    requests: number;
  };
  by_provider: Record<
    string,
    {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      requests: number;
    }
  >;
  daily: DailyRow[];
};

function fmt(n: number): string {
  return new Intl.NumberFormat('en-GB').format(n || 0);
}

export default function UsagePage() {
  const [data, setData] = useState<UsagePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await axios.get(`${getBackendUrl()}/api/usage/tokens`, {
          params: { days: 30 },
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (!alive) return;
        setData(res.data);
        setError(null);
      } catch (e: unknown) {
        if (!alive) return;
        const msg = axios.isAxiosError(e)
          ? String(e.response?.data?.detail || e.message)
          : 'Failed to load usage';
        setError(msg);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const maxDay = Math.max(1, ...(data?.daily.map((d) => d.total_tokens) || [1]));

  return (
    <div className="mr-page space-y-6" data-testid="usage-page">
      <div>
        <h1 className="text-2xl font-semibold">Usage</h1>
        <p className="text-sm text-mute">
          AI API tokens over the last 30 days ({data?.timezone || 'Europe/London'}).
        </p>
      </div>

      {loading && <p className="text-sm text-mute">Loading…</p>}
      {error && (
        <p className="text-sm text-red-300" role="alert">
          {error}
        </p>
      )}

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            {(
              [
                ['Total tokens', data.totals.total_tokens],
                ['Prompt', data.totals.prompt_tokens],
                ['Completion', data.totals.completion_tokens],
                ['Requests', data.totals.requests],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                className="rounded-xl border border-line bg-surface px-4 py-3"
              >
                <p className="text-xs uppercase tracking-wide text-mute">{label}</p>
                <p className="mt-1 text-xl font-semibold tabular-nums">{fmt(value)}</p>
              </div>
            ))}
          </div>

          {Object.keys(data.by_provider).length > 0 && (
            <div className="rounded-xl border border-line bg-surface p-4 space-y-2">
              <h2 className="text-sm font-medium text-white">By provider</h2>
              {Object.entries(data.by_provider).map(([name, row]) => (
                <div
                  key={name}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="capitalize text-mute">{name}</span>
                  <span className="tabular-nums text-white">
                    {fmt(row.total_tokens)} tokens · {fmt(row.requests)} req
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="rounded-xl border border-line bg-surface p-4 space-y-3">
            <h2 className="text-sm font-medium text-white">Daily</h2>
            <div className="space-y-2" data-testid="usage-daily">
              {data.daily.map((row) => (
                <div key={row.date} className="space-y-1">
                  <div className="flex justify-between text-xs text-mute">
                    <span>{row.date}</span>
                    <span className="tabular-nums">
                      {fmt(row.total_tokens)} · {fmt(row.requests)} req
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded bg-canvas-elev">
                    <div
                      className="h-full bg-accent/80"
                      style={{
                        width: `${Math.round((row.total_tokens / maxDay) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
