import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { ScrollText, Filter, ShieldCheck, Eye } from "lucide-react";
import { toast } from "sonner";

const PAGE = 50;

// Human labels for the action codes written by backend/audit.py.
const ACTIONS = {
  "": "All actions",
  "admin.org.suspend": "Tenant suspended",
  "admin.org.reactivate": "Tenant reactivated",
  "admin.org.delete": "Tenant deleted",
  "admin.user.suspend": "User suspended",
  "admin.user.reactivate": "User reactivated",
  "admin.user.revoke_sessions": "Sessions revoked",
  "admin.impersonate.start": "Impersonation started",
  "admin.tenant.view": "Tenant viewed",
};

const TONE = {
  "admin.org.delete": "text-red-300",
  "admin.org.suspend": "text-amber-300",
  "admin.user.suspend": "text-amber-300",
  "admin.impersonate.start": "text-sky-300",
};

export default function AdminAudit() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/admin/audit-log", {
        params: { action, actor, limit: PAGE, offset },
      });
      setEntries(r.data.entries || []);
      setTotal(r.data.total || 0);
    } catch {
      toast.error("Could not load the audit log");
    } finally {
      setLoading(false);
    }
  }, [action, actor, offset]);

  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="admin-audit">
      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500 font-semibold">Platform</p>
      <h1 className="font-heading text-3xl font-black tracking-tight text-white mt-1">Audit log</h1>
      <p className="text-slate-500 text-sm mt-1 mb-5 flex items-center gap-1.5">
        <ShieldCheck size={14} /> Append-only. Entries cannot be edited or deleted through the application.
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-md px-3">
          <Filter size={14} className="text-slate-500" />
          <select
            data-testid="audit-action-filter"
            value={action}
            onChange={(e) => { setAction(e.target.value); setOffset(0); }}
            className="bg-transparent py-2 text-sm outline-none"
          >
            {Object.entries(ACTIONS).map(([v, label]) => (
              <option key={v} value={v} className="bg-slate-900">{label}</option>
            ))}
          </select>
        </div>
        <input
          data-testid="audit-actor-filter"
          value={actor}
          onChange={(e) => { setActor(e.target.value); setOffset(0); }}
          placeholder="Filter by actor email…"
          className="bg-slate-900 border border-slate-800 rounded-md px-3 py-2 text-sm flex-1 min-w-[200px] max-w-xs"
        />
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <tr>
                <th className="px-4 py-2.5 font-semibold">When</th>
                <th className="px-4 py-2.5 font-semibold">Action</th>
                <th className="px-4 py-2.5 font-semibold">Actor</th>
                <th className="px-4 py-2.5 font-semibold">Target</th>
                <th className="px-4 py-2.5 font-semibold">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {loading && <tr><td colSpan={5} className="px-4 py-6 text-slate-500">Loading…</td></tr>}
              {!loading && !entries.length && (
                <tr><td colSpan={5} className="px-4 py-6 text-slate-500">No entries match.</td></tr>
              )}
              {entries.map((e, i) => (
                <tr key={`${e.at}-${i}`} data-testid="audit-entry" className="hover:bg-slate-800/40 align-top">
                  <td className="px-4 py-2.5 text-slate-400 whitespace-nowrap">
                    {new Date(e.at).toLocaleString()}
                  </td>
                  <td className={`px-4 py-2.5 font-semibold whitespace-nowrap ${TONE[e.action] || "text-slate-200"}`}>
                    {ACTIONS[e.action] || e.action}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">
                    <span className="flex items-center gap-1.5">
                      {e.actor_is_admin && <ShieldCheck size={12} className="text-amber-400 shrink-0" />}
                      {e.actor_email || "—"}
                    </span>
                    {e.impersonated_by && (
                      <span className="text-[11px] text-sky-400 flex items-center gap-1">
                        <Eye size={10} /> impersonated
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">
                    {e.target_org_name || e.target_user_email || e.target_org_id || e.target_user_id || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 max-w-[280px]">
                    {e.detail || (e.before || e.after
                      ? <code className="text-[11px]">{JSON.stringify(e.after ?? e.before).slice(0, 90)}</code>
                      : "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {total > PAGE && (
        <div className="flex items-center justify-between mt-3 text-sm text-slate-400">
          <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
              className="px-3 py-1.5 rounded-md border border-slate-700 disabled:opacity-40">Previous</button>
            <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}
              className="px-3 py-1.5 rounded-md border border-slate-700 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
