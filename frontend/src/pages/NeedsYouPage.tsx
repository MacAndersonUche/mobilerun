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

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold flex items-center gap-2">
            <AlertTriangle className="text-amber-400" /> Needs you
            {badge > 0 && (
              <span className="ml-2 text-sm bg-amber-600 text-white px-2 py-0.5 rounded-full">
                {badge}
              </span>
            )}
          </h2>
          <p className="text-gray-400 text-sm mt-1">
            Escalated Social + Dating drafts — approve, edit, or reject before send.
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-8 text-center text-gray-400">
          Nothing waiting. Auto-send handles the rest (with humanizer pacing).
        </div>
      ) : (
        items.map((item) => (
          <div
            key={item.id}
            className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3"
          >
            <div className="flex justify-between text-sm">
              <span>
                <span className="uppercase text-xs tracking-wide text-amber-300 mr-2">
                  {item.source}
                </span>
                {item.app_name} · {item.contact_name}
              </span>
              <span className="text-gray-500">
                conf {(item.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Reasons: {(item.reasons || []).join(', ') || '—'}
            </p>
            {item.inbound_preview && (
              <p className="text-sm text-gray-300 bg-gray-900 rounded p-2">
                Inbound: {item.inbound_preview}
              </p>
            )}
            <textarea
              id={`ny-${item.id}`}
              defaultValue={item.draft_reply}
              rows={3}
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm"
            />
            <div className="flex gap-2">
              <button
                disabled={loading}
                onClick={() => {
                  const el = document.getElementById(
                    `ny-${item.id}`
                  ) as HTMLTextAreaElement;
                  act(item.id, 'approve', el?.value);
                }}
                className="px-3 py-1.5 bg-green-700 hover:bg-green-600 rounded text-sm"
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
                className="px-3 py-1.5 bg-blue-700 hover:bg-blue-600 rounded text-sm"
              >
                Save edit
              </button>
              <button
                disabled={loading}
                onClick={() => act(item.id, 'reject')}
                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm"
              >
                Reject
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
