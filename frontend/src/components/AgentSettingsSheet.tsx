import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Button, Input, Textarea } from './ui';
import { PixelAvatar, PALETTE } from './PixelAvatar';
import ModeSpeedPicker from './ModeSpeedPicker';
import { cn } from '../lib/cn';

type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';
type ModelTier = 'best' | 'balanced' | 'saver';

const MODEL_TIERS: {
  id: ModelTier;
  label: string;
  hint: string;
  map: string;
}[] = [
  { id: 'best', label: 'Best', hint: 'Highest quality', map: 'Claude · Gemini Pro · GPT-4o · Grok' },
  { id: 'balanced', label: 'Balanced', hint: 'Good default', map: 'Gemini Flash · GPT-4o-mini · Grok' },
  { id: 'saver', label: 'Saver', hint: 'Lowest cost', map: 'Flash-Lite · mini models' },
];

export default function AgentSettingsSheet({
  open,
  onClose,
  name,
  onNameChange,
  focus,
  onFocusChange,
  color,
  onColorChange,
  mode,
  speed,
  onModeChange,
  onSpeedChange,
  modelTier,
  onModelTier,
  target,
  onTarget,
  devices,
  deviceId,
  onDeviceId,
}: {
  open: boolean;
  onClose: () => void;
  name: string;
  onNameChange: (v: string) => void;
  focus: string;
  onFocusChange: (v: string) => void;
  color: string;
  onColorChange: (v: string) => void;
  mode: Mode;
  speed: Speed;
  onModeChange: (m: Mode) => void;
  onSpeedChange: (s: Speed) => void;
  modelTier: ModelTier;
  onModelTier: (t: ModelTier) => void;
  target: 'pc' | 'hosted';
  onTarget: (t: 'pc' | 'hosted') => void;
  devices: { device_id: string; name?: string; connected?: boolean; latency_ms?: number }[];
  deviceId: string;
  onDeviceId: (id: string) => void;
}) {
  const [tab, setTab] = useState<'devices' | 'routines' | 'agent'>('agent');

  return (
    <Sheet open={open} onClose={onClose} title={`${name} · Settings`}>
      <div className="mb-4 flex gap-1 rounded-xl bg-canvas-elev p-1">
        {(['devices', 'routines', 'agent'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              'flex-1 rounded-lg py-2 text-sm capitalize',
              tab === t ? 'bg-surface-elev text-white' : 'text-mute'
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'devices' && (
        <div className="space-y-3">
          <p className="text-sm text-mute">
            Linked phones for this agent. Permission status lives here.
          </p>
          <select
            className="mr-input"
            value={deviceId}
            onChange={(e) => onDeviceId(e.target.value)}
          >
            <option value="">No device</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {(d.name || d.device_id) + (d.connected ? ' · Ready' : ' · Offline')}
              </option>
            ))}
          </select>
          <div className="flex flex-wrap gap-2">
            <Link to="/devices" className="mr-btn-primary text-sm" onClick={onClose}>
              Manage devices
            </Link>
          </div>
          {devices.length === 0 && (
            <p className="text-xs text-mute">
              Online / Busy / Offline counts appear on Home after the APK links.
            </p>
          )}
        </div>
      )}

      {tab === 'routines' && (
        <div className="rounded-2xl border border-line bg-canvas-elev p-4 text-sm text-mute">
          No routine planned yet — Build one with {name}.
        </div>
      )}

      {tab === 'agent' && (
        <div className="space-y-5">
          <div className="flex items-start gap-4">
            <PixelAvatar name={name} color={color} size={64} />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap gap-2">
                {PALETTE.map((c) => (
                  <button
                    key={c}
                    type="button"
                    aria-label={`Color ${c}`}
                    className={cn(
                      'h-7 w-7 rounded-full border-2',
                      color === c ? 'border-white' : 'border-transparent'
                    )}
                    style={{ background: c }}
                    onClick={() => onColorChange(c)}
                  />
                ))}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 text-xs"
                  onClick={() =>
                    onColorChange(PALETTE[Math.floor(Math.random() * PALETTE.length)])
                  }
                >
                  Shuffle
                </Button>
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 text-xs"
                  onClick={() => onColorChange(PALETTE[0])}
                >
                  Reset
                </Button>
              </div>
            </div>
          </div>

          <label className="block text-sm text-mute">
            Name
            <Input className="mt-1" value={name} onChange={(e) => onNameChange(e.target.value)} />
          </label>

          <label className="block text-sm text-mute">
            What {name || 'agent'} focuses on
            <Textarea
              className="mt-1"
              maxLength={1500}
              value={focus}
              onChange={(e) => onFocusChange(e.target.value)}
            />
            <span className="mt-1 block text-right text-xs">{focus.length}/1500</span>
          </label>

          <div>
            <p className="mb-2 text-sm text-mute">Model</p>
            <div className="space-y-2">
              {MODEL_TIERS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => onModelTier(t.id)}
                  className={cn(
                    'w-full rounded-2xl border p-3 text-left',
                    modelTier === t.id
                      ? 'border-accent bg-accent/10'
                      : 'border-line bg-canvas-elev'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{t.label}</span>
                    <span className="text-xs text-mute">{t.hint}</span>
                  </div>
                  <p className="mt-1 text-xs text-mute">{t.map}</p>
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 text-sm text-mute">Run on</p>
            <div className="flex gap-2">
              {(['hosted', 'pc'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => onTarget(t)}
                  className={cn(
                    'flex-1 rounded-xl border px-3 py-2 text-sm',
                    target === t ? 'border-accent bg-accent/15' : 'border-line'
                  )}
                >
                  {t === 'hosted' ? 'Hosted server' : 'My PC'}
                </button>
              ))}
            </div>
          </div>

          <ModeSpeedPicker
            mode={mode}
            speed={speed}
            onModeChange={onModeChange}
            onSpeedChange={onSpeedChange}
          />

          <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line text-sm">
            {['Skills', 'Files'].map((row) => (
              <div key={row} className="bg-canvas-elev px-3 py-3 text-mute">
                {row}
              </div>
            ))}
          </div>

          <Button variant="danger" className="w-full">
            Force stop
          </Button>
        </div>
      )}
    </Sheet>
  );
}
