/** Plain-language formatting for live task / mode activity steps. */

export type RawStep = {
  n: number;
  action: string;
  reason?: string | null;
  ok?: boolean | null;
  package?: string | null;
  screen?: string | null;
  screenshot_url?: string | null;
  verify?: string | null;
  ts?: number | null;
  dry_run?: boolean | null;
};

const APP_ALIASES: Record<string, string> = {
  settings: 'Settings',
  chrome: 'Chrome',
  whatsapp: 'WhatsApp',
  messages: 'Messages',
  'com.android.settings': 'Settings',
  'com.android.chrome': 'Chrome',
  'com.google.android.apps.messaging': 'Messages',
  'com.whatsapp': 'WhatsApp',
  'ai.mobilerun.mockdating': 'MockDating',
  'com.mockdating.mockdating': 'MockDating',
};

function prettyApp(raw: string): string {
  const s = (raw || '').trim();
  if (!s) return 'app';
  const lower = s.toLowerCase();
  if (APP_ALIASES[lower]) return APP_ALIASES[lower];
  if (APP_ALIASES[s]) return APP_ALIASES[s];
  // package → last segment
  if (s.includes('.')) {
    const last = s.split('.').pop() || s;
    return last.charAt(0).toUpperCase() + last.slice(1);
  }
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function stripQuotes(s: string): string {
  return s.replace(/^['"]|['"]$/g, '');
}

/** One-line human headline, e.g. "Opened WhatsApp". */
export function formatStepHeadline(step: RawStep): string {
  const action = String(step.action || '').trim();
  const dry =
    step.dry_run === true ||
    /\bdry[_\s-]?run\b/i.test(action) ||
    /\bdry[_\s-]?run\b/i.test(String(step.reason || ''));

  // Already human (from newer backend summaries)
  if (/^(Opened|Tapped|Typed|Swiped|Went|Sent|Composed|Scanned|Prepared|Finished|Failed|Idle)\b/i.test(action)) {
    return dry && !/\(dry run\)/i.test(action) ? `${action} (dry run)` : action;
  }

  let open = action.match(/^open_app\(([^)\]]+)\)(?:\[([^\]]+)\])?/i);
  if (open) {
    return `Opened ${prettyApp(open[1] || open[2] || '')}`;
  }
  if (/^opener$/i.test(action)) {
    return dry ? 'Composed opener (dry run)' : 'Sent opener';
  }
  if (/^reply$/i.test(action)) {
    return dry ? 'Composed reply (dry run)' : 'Sent reply';
  }
  if (/^swipe$/i.test(action)) {
    return dry ? 'Swiped card (dry run)' : 'Swiped card';
  }
  if (/^open_app$/i.test(action)) {
    return `Opened ${prettyApp(String(step.package || step.screen || 'app'))}`;
  }
  if (/^scan_unread$/i.test(action)) {
    return dry ? 'Scanned unread threads (dry run)' : 'Scanned unread threads';
  }
  if (/^draft_preview$/i.test(action)) {
    return dry ? 'Prepared draft reply (dry run)' : 'Prepared draft reply';
  }
  if (/^idle$/i.test(action)) {
    return 'Waiting (humanizer pause)';
  }
  if (/^done$/i.test(action)) {
    return 'Finished';
  }

  const tap = action.match(/^tap\((\d+),(\d+)\)$/i);
  if (tap) {
    const why = String(step.reason || '').trim();
    if (why) {
      // Prefer short label from reason if it looks like a UI target
      const m = why.match(/tap(?:ped)?\s+["']?([^"'—\-]+)/i);
      if (m) return `Tapped "${m[1].trim()}"`;
      return 'Tapped on screen';
    }
    return 'Tapped on screen';
  }

  const typed = action.match(/^type\((.+)\)$/i);
  if (typed) {
    const text = stripQuotes(typed[1]).slice(0, 48);
    const base = text ? `Typed "${text}"` : 'Typed text';
    return dry ? `${base} (dry run)` : base;
  }

  if (/^swipe\(/i.test(action)) return 'Swiped';
  if (/^back$/i.test(action)) return 'Went back';
  if (/^home$/i.test(action)) return 'Went home';

  // Fallback: clean underscores
  const cleaned = action.replace(/_/g, ' ');
  return dry && !/\(dry run\)/i.test(cleaned) ? `${cleaned} (dry run)` : cleaned;
}

/** Supporting clause after an em dash, e.g. "to find the conversation". */
export function formatStepWhy(step: RawStep): string {
  const reason = String(step.reason || '').trim();
  if (!reason) return '';
  // Drop technical dry_run boilerplate already reflected in headline
  let r = reason
    .replace(/^dry_run\s*[—\-·:]\s*/i, '')
    .replace(/\bdry[_\s-]?run\b/gi, '')
    .replace(/\bno real\s+(send|like|likes|messages?|sends?)[^.·|]*/gi, '')
    .replace(/\s*[·|]\s*source=\w+/gi, '')
    .replace(/\s*[·|]\s*msg=.*/gi, '')
    .replace(/^[—\-·:\s]+/, '')
    .trim();
  // dating opener noise
  r = r.replace(/^dating\s+(opener|reply|swipe)\s*[·|]?\s*/i, '').trim();
  if (!r || /^(dry_run|ok|—|-)$/i.test(r)) return '';
  // Avoid duplicating the headline
  const head = formatStepHeadline(step).toLowerCase();
  if (head.includes(r.toLowerCase().slice(0, 24))) return '';
  return r;
}

/** Full line: "Step 2: Opened WhatsApp — to check unread". */
export function formatStepLine(step: RawStep): string {
  const head = formatStepHeadline(step);
  const why = formatStepWhy(step);
  const body = why ? `${head} — ${why}` : head;
  return `Step ${step.n}: ${body}`;
}

export function formatStepTime(ts?: number | null): string {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toLocaleTimeString();
  } catch {
    return '';
  }
}

export function stepStatusLabel(
  step: RawStep,
  opts?: { isLatest?: boolean; taskStatus?: string }
): 'done' | 'failed' | 'running' {
  if (step.ok === false) return 'failed';
  const terminal = ['completed', 'failed', 'stopped', 'cancelled'].includes(
    String(opts?.taskStatus || '').toLowerCase()
  );
  if (opts?.isLatest && !terminal) return 'running';
  return 'done';
}
