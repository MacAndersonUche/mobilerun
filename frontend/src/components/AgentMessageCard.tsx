import { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Smartphone } from 'lucide-react';
import { Badge, Card } from './ui';
import { cn } from '../lib/cn';

export type AgentStep = {
  title: string;
  subtext?: string;
  duration?: string;
  done?: boolean;
  /** Optional explicit status for live/expanding chat steps */
  status?: 'done' | 'running' | 'failed';
};

export type AgentPayload = {
  deviceLabel?: string;
  ready?: boolean;
  latencyMs?: number | null;
  thoughts?: string;
  steps?: AgentStep[];
  answer: string;
  suggestions?: string[];
};

/** Parse plain assistant text into a structured card when meta is absent. */
export function parseAgentContent(
  content: string,
  device?: { name?: string; connected?: boolean; latency_ms?: number }
): AgentPayload {
  const lines = content.split('\n').map((l) => l.trim()).filter(Boolean);
  const steps: AgentStep[] = [];
  const thoughts: string[] = [];
  const answerLines: string[] = [];
  for (const line of lines) {
    if (/^thought/i.test(line) || line.startsWith('>')) {
      thoughts.push(line.replace(/^thoughts?:?\s*/i, '').replace(/^>\s*/, ''));
    } else if (/^(✓|✔|done:|step:|[-*]\s)/i.test(line)) {
      steps.push({
        title: line.replace(/^(✓|✔|done:|step:|[-*]\s)+/i, '').trim(),
        done: true,
        duration: undefined,
      });
    } else {
      answerLines.push(line);
    }
  }
  return {
    deviceLabel: device?.name || 'Phone',
    ready: device?.connected ?? true,
    latencyMs: device?.latency_ms ?? null,
    thoughts: thoughts.length ? thoughts.join(' ') : undefined,
    steps: steps.length ? steps : undefined,
    answer: answerLines.join('\n') || content,
    suggestions: ['device info', 'needs you', 'open Settings'],
  };
}

export default function AgentMessageCard({
  payload,
  onSuggest,
}: {
  payload: AgentPayload;
  onSuggest?: (s: string) => void;
}) {
  const [openThoughts, setOpenThoughts] = useState(false);

  return (
    <div className="mr-auto w-full max-w-[92%] space-y-2">
      <Card className="space-y-3 !p-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-canvas-elev">
            <Smartphone size={16} className="text-mute" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {payload.deviceLabel || 'Device'}
            </p>
          </div>
          <Badge tone={payload.ready ? 'ok' : 'mute'}>
            {payload.ready ? 'Ready' : 'Offline'}
          </Badge>
          {payload.latencyMs != null && (
            <span className="text-xs text-mute">{Math.round(payload.latencyMs)} ms</span>
          )}
        </div>

        {payload.thoughts && (
          <div className="rounded-xl bg-canvas-elev">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-mute"
              onClick={() => setOpenThoughts((v) => !v)}
            >
              {openThoughts ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Thoughts
            </button>
            {openThoughts && (
              <p className="border-t border-line px-3 py-2 text-xs text-mute whitespace-pre-wrap">
                {payload.thoughts}
              </p>
            )}
          </div>
        )}

        {payload.steps?.map((s, i) => {
          const status =
            s.status ||
            (s.done === false ? 'failed' : s.done === true ? 'done' : 'running');
          return (
            <div
              key={i}
              className="flex items-start gap-2 rounded-xl border border-line bg-canvas-elev px-3 py-2"
            >
              <div
                className={cn(
                  'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                  status === 'done'
                    ? 'bg-ok-bg text-ok'
                    : status === 'failed'
                      ? 'bg-red-950 text-red-300'
                      : 'bg-surface-elev text-mute'
                )}
              >
                <Check size={12} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium">{s.title}</p>
                  <Badge
                    tone={
                      status === 'done' ? 'ok' : status === 'failed' ? 'warn' : 'mute'
                    }
                  >
                    {status === 'done'
                      ? 'Done'
                      : status === 'failed'
                        ? 'Failed'
                        : 'Running'}
                  </Badge>
                  {s.duration && (
                    <span className="text-xs text-mute">{s.duration}</span>
                  )}
                </div>
                {s.subtext && (
                  <p className="mt-0.5 text-xs text-mute">{s.subtext}</p>
                )}
              </div>
            </div>
          );
        })}

        <p className="whitespace-pre-wrap text-sm leading-relaxed">{payload.answer}</p>
      </Card>

      {payload.suggestions && payload.suggestions.length > 0 && onSuggest && (
        <div className="no-scrollbar flex gap-2 overflow-x-auto pb-1">
          {payload.suggestions.map((s) => (
            <button
              key={s}
              type="button"
              className="shrink-0 rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-mute"
              onClick={() => onSuggest(s)}
            >
              {s} →
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
