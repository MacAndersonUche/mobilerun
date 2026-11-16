import { useEffect, useState } from 'react';
import axios from 'axios';
import { getAuthToken, getBackendUrl } from '../config';

type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';

interface Props {
  mode: Mode;
  speed: Speed;
  onModeChange?: (mode: Mode) => void;
  onSpeedChange: (speed: Speed) => void;
  /** Hide mode toggles when the page is mode-specific (e.g. Dating page). */
  hideMode?: boolean;
  /** Show advanced humanizer knobs (jitter, shuffle, session window). */
  showAdvanced?: boolean;
}

const SPEEDS: { id: Speed; label: string; hint: string }[] = [
  { id: 'fast', label: 'Fast', hint: '~0.3–1.8s' },
  { id: 'balanced', label: 'Balanced', hint: '~0.6–3.5s' },
  { id: 'careful', label: 'Careful', hint: '~1.2–7s' },
];

type HumanizerOverrides = {
  delay_sigma?: number;
  tap_jitter_frac?: number;
  session_start_jitter_max?: number;
  session_end_early_max?: number;
  shuffle_apps?: boolean;
  shuffle_conversations?: boolean;
  enabled?: boolean;
};

export default function ModeSpeedPicker({
  mode,
  speed,
  onModeChange,
  onSpeedChange,
  hideMode = false,
  showAdvanced = true,
}: Props) {
  const [open, setOpen] = useState(false);
  const [overrides, setOverrides] = useState<HumanizerOverrides>({});
  const [saving, setSaving] = useState(false);

  const headers = () => ({ Authorization: `Bearer ${getAuthToken()}` });

  useEffect(() => {
    if (!showAdvanced) return;
    axios
      .get(`${getBackendUrl()}/api/humanizer`, { headers: headers() })
      .then((res) => {
        setOverrides(res.data.overrides || {});
      })
      .catch(() => {
        /* optional */
      });
  }, [showAdvanced, speed]);

  const saveOverrides = async (patch: HumanizerOverrides) => {
    const next = { ...overrides, ...patch };
    setOverrides(next);
    setSaving(true);
    try {
      await axios.post(
        `${getBackendUrl()}/api/humanizer`,
        { ...next, speed_preset: speed },
        { headers: headers() }
      );
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
      {!hideMode && onModeChange && (
        <div>
          <label className="mb-2 block text-sm text-mute">Mode</label>
          <div className="flex overflow-hidden rounded-xl border border-line">
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'normal' ? 'bg-accent' : 'bg-canvas-elev'
              }`}
              onClick={() => onModeChange('normal')}
            >
              Normal
              <span className="block text-[11px] font-normal opacity-80">
                Any phone task
              </span>
            </button>
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'dating' ? 'bg-rose-600' : 'bg-canvas-elev'
              }`}
              onClick={() => onModeChange('dating')}
            >
              Dating
              <span className="block text-[11px] font-normal opacity-80">
                Openers · replies
              </span>
            </button>
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'social' ? 'bg-emerald-600' : 'bg-canvas-elev'
              }`}
              onClick={() => onModeChange('social')}
            >
              Social
              <span className="block text-[11px] font-normal opacity-80">
                Chats · unread
              </span>
            </button>
          </div>
        </div>
      )}
      <div>
        <label className="mb-2 block text-sm text-mute">Speed preset</label>
        <div className="grid grid-cols-3 gap-2">
          {SPEEDS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onSpeedChange(s.id)}
              className={`rounded-xl border px-2 py-2 text-sm ${
                speed === s.id
                  ? 'border-accent bg-accent/20 text-white'
                  : 'border-line bg-canvas-elev text-mute hover:border-mute'
              }`}
            >
              {s.label}
              <span className="block text-[11px] font-normal text-mute">
                {s.hint}
              </span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-mute">
          Log-normal delays, micro-pauses, rare longer breaks, per-message typing
          speed, shuffled apps/chats — never fixed intervals. Caps still apply.
        </p>
      </div>

      {showAdvanced && (
        <div className="border-t border-line pt-3">
          <button
            type="button"
            className="text-sm text-mute underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? 'Hide' : 'Humanizer'} timing options
            {saving ? '…' : ''}
          </button>
          {open && (
            <div className="mt-3 space-y-3 text-sm">
              <label className="flex items-center justify-between gap-2">
                <span className="text-mute">Enabled</span>
                <input
                  type="checkbox"
                  checked={overrides.enabled !== false}
                  onChange={(e) => saveOverrides({ enabled: e.target.checked })}
                />
              </label>
              <label className="flex items-center justify-between gap-2">
                <span className="text-mute">Shuffle apps</span>
                <input
                  type="checkbox"
                  checked={overrides.shuffle_apps !== false}
                  onChange={(e) =>
                    saveOverrides({ shuffle_apps: e.target.checked })
                  }
                />
              </label>
              <label className="flex items-center justify-between gap-2">
                <span className="text-mute">Shuffle conversations</span>
                <input
                  type="checkbox"
                  checked={overrides.shuffle_conversations !== false}
                  onChange={(e) =>
                    saveOverrides({ shuffle_conversations: e.target.checked })
                  }
                />
              </label>
              <label className="block text-mute">
                Delay variance (σ)
                <input
                  type="range"
                  min={0.2}
                  max={1.2}
                  step={0.05}
                  value={overrides.delay_sigma ?? 0.55}
                  className="mt-1 w-full"
                  onChange={(e) =>
                    saveOverrides({ delay_sigma: Number(e.target.value) })
                  }
                />
              </label>
              <label className="block text-mute">
                Tap jitter
                <input
                  type="range"
                  min={0.05}
                  max={0.4}
                  step={0.01}
                  value={overrides.tap_jitter_frac ?? 0.22}
                  className="mt-1 w-full"
                  onChange={(e) =>
                    saveOverrides({ tap_jitter_frac: Number(e.target.value) })
                  }
                />
              </label>
              <label className="block text-mute">
                Session start jitter (max min)
                <input
                  type="number"
                  min={0}
                  max={120}
                  className="mt-1 w-full rounded-lg border border-line bg-canvas-elev px-2 py-1"
                  value={overrides.session_start_jitter_max ?? 45}
                  onChange={(e) =>
                    saveOverrides({
                      session_start_jitter_max: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="block text-mute">
                End early jitter (max min)
                <input
                  type="number"
                  min={0}
                  max={120}
                  className="mt-1 w-full rounded-lg border border-line bg-canvas-elev px-2 py-1"
                  value={overrides.session_end_early_max ?? 35}
                  onChange={(e) =>
                    saveOverrides({
                      session_end_early_max: Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
