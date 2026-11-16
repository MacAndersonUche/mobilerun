import { cn } from '../lib/cn';

const PALETTE = [
  '#3B82F6',
  '#F43F5E',
  '#22C55E',
  '#A855F7',
  '#F59E0B',
  '#06B6D4',
  '#EC4899',
  '#84CC16',
];

/** Simple deterministic pixel-art style avatar (no external brand assets). */
export function PixelAvatar({
  name,
  color,
  size = 48,
  className,
}: {
  name: string;
  color?: string;
  size?: number;
  className?: string;
}) {
  const seed = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  const bg = color || PALETTE[seed % PALETTE.length];
  const cells = 8;
  const cell = size / cells;
  const squares: { x: number; y: number }[] = [];
  for (let y = 1; y < cells - 1; y++) {
    for (let x = 1; x < cells / 2; x++) {
      // Bias toward denser faces so short names still look pixel-art
      const bit = (seed * (x + 1) * (y + 3) + x * 11) % 5 > 1;
      if (bit) {
        squares.push({ x, y });
        squares.push({ x: cells - 1 - x, y });
      }
    }
  }
  // Eyes
  squares.push({ x: 2, y: 3 }, { x: cells - 3, y: 3 });
  return (
    <div
      className={cn('shrink-0 overflow-hidden rounded-2xl', className)}
      style={{ width: size, height: size, background: bg }}
      aria-hidden
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {squares.map((s, i) => (
          <rect
            key={i}
            x={s.x * cell}
            y={s.y * cell}
            width={cell}
            height={cell}
            fill="rgba(255,255,255,0.85)"
          />
        ))}
      </svg>
    </div>
  );
}

export { PALETTE };
