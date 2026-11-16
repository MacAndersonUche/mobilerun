type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';

interface Props {
  mode: Mode;
  speed: Speed;
  onModeChange?: (mode: Mode) => void;
  onSpeedChange: (speed: Speed) => void;
  /** Hide mode toggles when the page is mode-specific (e.g. Dating page). */
  hideMode?: boolean;
}

const SPEEDS: { id: Speed; label: string; hint: string }[] = [
  { id: 'fast', label: 'Fast', hint: '~0.4–1.2s' },
  { id: 'balanced', label: 'Balanced', hint: '~0.8–2.5s' },
  { id: 'careful', label: 'Careful', hint: '~1.5–5s' },
];

export default function ModeSpeedPicker({
  mode,
  speed,
  onModeChange,
  onSpeedChange,
  hideMode = false,
}: Props) {
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
          Randomized delays, jittered taps, curved swipes — Balanced is default.
        </p>
      </div>
    </div>
  );
}
