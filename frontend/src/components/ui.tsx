import { cn } from '../lib/cn';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';

export function Button({
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'danger' | 'outline';
}) {
  const variants = {
    primary: 'mr-btn-primary',
    ghost: 'mr-btn-ghost',
    danger: 'mr-btn-danger',
    outline: 'mr-btn border border-line bg-transparent hover:bg-surface-elev',
  };
  return <button className={cn(variants[variant], className)} {...props} />;
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn('mr-input', className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn('mr-input min-h-[96px]', className)} {...props} />;
}

export function Card({
  className,
  elev,
  children,
}: {
  className?: string;
  elev?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn(elev ? 'mr-card-elev' : 'mr-card', className)}>{children}</div>
  );
}

export function Badge({
  children,
  tone = 'mute',
}: {
  children: ReactNode;
  tone?: 'ok' | 'mute' | 'accent' | 'warn';
}) {
  const tones = {
    ok: 'mr-badge-ok',
    mute: 'mr-badge bg-surface-elev text-mute',
    accent: 'mr-badge bg-accent/20 text-accent',
    warn: 'mr-badge bg-amber-950 text-amber-300',
  };
  return <span className={tones[tone]}>{children}</span>;
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <Card className="text-center py-10">
      <p className="text-base font-medium">{title}</p>
      {hint && <p className="mt-1 text-sm text-mute">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </Card>
  );
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <Card className="animate-pulse text-mute text-sm">{label}</Card>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
      {message}
    </div>
  );
}

export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center md:items-center">
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
      />
      <div className="relative z-10 w-full max-w-content max-h-[88vh] overflow-y-auto rounded-t-3xl border border-line bg-surface p-4 shadow-sheet md:rounded-3xl md:max-h-[80vh]">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line md:hidden" />
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-sm text-mute hover:bg-surface-elev"
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
