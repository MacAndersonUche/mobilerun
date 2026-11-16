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
    <div className="space-y-3 bg-surface border border-line rounded-lg p-4">
      {!hideMode && onModeChange && (
        <div>
          <label className="block text-sm font-medium mb-2">Mode</label>
          <div className="flex rounded-lg overflow-hidden border border-line">
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'normal' ? 'bg-accent' : 'bg-surface-elev'
              }`}
              onClick={() => onModeChange('normal')}
            >
              Normal
              <span className="block text-[11px] opacity-80 font-normal">
                Any phone task
              </span>
            </button>
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'dating' ? 'bg-rose-600' : 'bg-surface-elev'
              }`}
              onClick={() => onModeChange('dating')}
            >
              Dating
              <span className="block text-[11px] opacity-80 font-normal">
                Openers · replies
              </span>
            </button>
            <button
              type="button"
              className={`flex-1 px-2 py-2 text-sm ${
                mode === 'social' ? 'bg-emerald-600' : 'bg-surface-elev'
              }`}
              onClick={() => onModeChange('social')}
            >
              Social
              <span className="block text-[11px] opacity-80 font-normal">
                Chats · unread
              </span>
            </button>
          </div>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium mb-2">
          Humanizer pacing
        </label>
        <div className="grid grid-cols-3 gap-2">
          {SPEEDS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onSpeedChange(s.id)}
              className={`px-2 py-2 rounded border text-sm ${
                speed === s.id
                  ? 'border-accent bg-accent/20 text-white'
                  : 'border-line bg-canvas-elev text-mute hover:border-gray-500'
              }`}
            >
              {s.label}
              <span className="block text-[11px] text-mute font-normal">
                {s.hint}
              </span>
            </button>
          ))}
        </div>
        <p className="text-xs text-mute mt-2">
          Randomized delays, jittered taps, curved swipes — Balanced is default.
        </p>
      </div>
    </div>
  );
}
