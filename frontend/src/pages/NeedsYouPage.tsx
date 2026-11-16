import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import axios from 'axios';
import { getAuthToken, getBackendUrl } from '../config';

type Item = {
  id: string;
  source: string;
  app_name: string;
  contact_name: string;
  inbound_preview: string;
  draft_reply: string;
  reasons: string[];
  confidence: number;
  status: string;
  meta?: Record<string, unknown>;
};

export default function NeedsYouPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [badge, setBadge] = useState(0);
  const [loading, setLoading] = useState(false);

  const headers = () => ({ Authorization: `Bearer ${getAuthToken()}` });

  const load = async () => {
    try {
      const res = await axios.get(`${getBackendUrl()}/api/needs-you`, {
        headers: headers(),
      });
      setItems(res.data.items || []);
      setBadge(res.data.badge || 0);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  const isSafety = (item: Item) =>
    item.source === 'safety' ||
    (item.reasons || []).includes('safety_pause') ||
    (item.reasons || []).includes('needs_resume') ||
    item.meta?.kind === 'safety_pause';

  const act = async (
    id: string,
    action: 'approve' | 'reject' | 'edit',
    draft?: string
  ) => {
    setLoading(true);
    try {
      if (action === 'edit') {
        await axios.post(
          `${getBackendUrl()}/api/needs-you/${id}/edit`,
          { draft_reply: draft },
          { headers: headers() }
        );
      } else {
        await axios.post(
          `${getBackendUrl()}/api/needs-you/${id}/${action}`,
          action === 'approve' && draft ? { draft_reply: draft } : {},
          { headers: headers() }
        );
      }
      await load();
    } catch (e) {
      console.error(e);
      alert(`Failed to ${action}`);
    } finally {
      setLoading(false);
    }
  };

  const resumeSafety = async (item: Item) => {
    setLoading(true);
    try {
      await axios.post(
        `${getBackendUrl()}/api/safety/resume`,
        { app: item.app_name, resume_all: false },
        { headers: headers() }
      );
      // Clear the Needs-you card after explicit resume
      await axios.post(
        `${getBackendUrl()}/api/needs-you/${item.id}/approve`,
        { draft_reply: '' },
        { headers: headers() }
      );
      await load();
    } catch (e) {
      console.error(e);
      alert('Failed to resume — handle the phone prompt first, then try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mr-page space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold flex items-center gap-2">
            <AlertTriangle className="text-amber-400" /> Needs you
            {badge > 0 && (
              <span className="ml-2 text-sm bg-amber-600 text-white px-2 py-0.5 rounded-full">
                {badge}
              </span>
            )}
          </h2>
          <p className="text-mute text-sm mt-1">
            Escalated drafts and safety pauses — resume only after you handle the
            phone prompt. Agent never solves captchas or verification.
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="mr-card text-center text-mute">
          Nothing waiting. Auto-send handles the rest (with humanizer pacing).
        </div>
      ) : (
        items.map((item) => (
          <div key={item.id} className="mr-card space-y-3">
            <div className="flex justify-between text-sm">
              <span>
                <span className="mr-2 text-xs uppercase tracking-wide text-amber-300">
                  {item.source}
                </span>
                {item.app_name} · {item.contact_name}
              </span>
              <span className="text-mute">
                conf {(item.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="text-xs text-mute">
              Reasons: {(item.reasons || []).join(', ') || '—'}
            </p>
            {item.inbound_preview && (
              <p className="rounded-xl bg-canvas-elev p-2 text-sm text-mute">
                {isSafety(item) ? 'Alert' : 'Inbound'}: {item.inbound_preview}
              </p>
            )}
            {isSafety(item) ? (
              <div className="flex flex-wrap gap-2">
                <button
                  disabled={loading}
                  onClick={() => resumeSafety(item)}
                  className="mr-btn bg-ok-bg text-ok"
                >
                  Resume agent
                </button>
                <p className="w-full text-xs text-mute">
                  Resume only after you clear the warning / verification on the
                  phone. Mobilerun will not bypass it.
                </p>
              </div>
            ) : (
              <>
                <label
                  htmlFor={`ny-${item.id}`}
                  className="block text-sm text-mute"
                >
                  Draft reply
                </label>
                <textarea
                  id={`ny-${item.id}`}
                  defaultValue={item.draft_reply}
                  rows={3}
                  className="mr-input"
                  aria-label="Draft reply"
                />
                <div className="flex flex-wrap gap-2">
                  <button
                    disabled={loading}
                    onClick={() => {
                      const el = document.getElementById(
                        `ny-${item.id}`
                      ) as HTMLTextAreaElement;
                      act(item.id, 'approve', el?.value);
                    }}
                    className="mr-btn bg-ok-bg text-ok"
                  >
                    Approve & send
                  </button>
                  <button
                    disabled={loading}
                    onClick={() => {
                      const el = document.getElementById(
                        `ny-${item.id}`
                      ) as HTMLTextAreaElement;
                      act(item.id, 'edit', el?.value);
                    }}
                    className="mr-btn-primary"
                  >
                    Save edit
                  </button>
                  <button
                    disabled={loading}
                    onClick={() => act(item.id, 'reject')}
                    className="mr-btn-ghost"
                  >
                    Reject
                  </button>
                </div>
              </>
            )}
          </div>
        ))
      )}
    </div>
  );
}
