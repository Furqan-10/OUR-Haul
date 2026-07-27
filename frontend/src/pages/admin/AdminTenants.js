import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import {
  Search, Ban, RotateCcw, Trash2, ChevronRight, Building2, Eye, ShieldAlert, X,
} from "lucide-react";
import { toast } from "sonner";

const PAGE = 25;

const StatusPill = ({ active }) => (
  <span
    data-testid={`tenant-status-${active ? "active" : "suspended"}`}
    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${
      active ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
    }`}
  >
    {active ? "Active" : "Suspended"}
  </span>
);

/** Confirmation that requires typing the tenant's name — deletion destroys
 *  statutory compliance evidence, so a stray click must not be enough. */
function DeleteDialog({ org, onClose, onDeleted }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const matches = typed.trim() === (org.name || "").trim();

  const remove = async () => {
    setBusy(true);
    try {
      const r = await api.delete(
        `/admin/organisations/${org.org_id}?confirm_name=${encodeURIComponent(typed.trim())}`
      );
      toast.success(`Deleted — ${Object.values(r.data.deleted || {}).reduce((a, b) => a + b, 0)} records removed`);
      onDeleted();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not delete");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50" data-testid="delete-tenant-dialog">
      <div className="bg-slate-900 border border-red-900/60 rounded-md p-5 w-full max-w-md">
        <div className="flex items-start gap-3">
          <ShieldAlert className="text-red-400 shrink-0 mt-0.5" size={20} />
          <div className="flex-1">
            <h3 className="font-heading text-lg font-bold text-white">Delete this tenant?</h3>
            <p className="text-sm text-slate-400 mt-1.5">
              This permanently removes every record belonging to{" "}
              <strong className="text-slate-200">{org.name || org.org_id}</strong> — inspection
              sheets, defect history and tacho records an operator may be legally required to
              retain. It cannot be undone.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={16} /></button>
        </div>
        <label className="block text-xs font-semibold text-slate-400 mt-4 mb-1.5">
          Type <span className="text-slate-200">{org.name || "(unnamed)"}</span> to confirm
        </label>
        <input
          data-testid="delete-confirm-input"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm"
          autoFocus
        />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-3 py-2 text-sm text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            data-testid="delete-confirm-button"
            disabled={!matches || busy}
            onClick={remove}
            className="px-3 py-2 text-sm font-semibold rounded-md bg-red-600 text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? "Deleting…" : "Delete permanently"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminTenants() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(`/admin/organisations`, { params: { q, limit: PAGE, offset } });
      setRows(r.data.organisations || []);
      setTotal(r.data.total || 0);
    } catch {
      toast.error("Could not load tenants");
    } finally {
      setLoading(false);
    }
  }, [q, offset]);

  useEffect(() => { load(); }, [load]);

  const setSuspended = async (org, suspend) => {
    try {
      const path = suspend ? "suspend" : "reactivate";
      await api.post(`/admin/organisations/${org.org_id}/${path}`,
        suspend ? { reason: window.prompt("Reason (recorded in the audit log):") || "" } : {});
      toast.success(suspend ? "Tenant suspended" : "Tenant reactivated");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not update tenant");
    }
  };

  const openDetail = async (org) => {
    try {
      const r = await api.get(`/admin/organisations/${org.org_id}`);
      setDetail(r.data);
    } catch {
      toast.error("Could not load tenant detail");
    }
  };

  return (
    <div data-testid="admin-tenants">
      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500 font-semibold">Platform</p>
      <h1 className="font-heading text-3xl font-black tracking-tight text-white mt-1 mb-5">
        Tenants <span className="text-slate-600 font-normal text-2xl">({total})</span>
      </h1>

      <div className="relative mb-4 max-w-md">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          data-testid="tenant-search"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
          placeholder="Search by organisation or owner email…"
          className="w-full bg-slate-900 border border-slate-800 rounded-md pl-9 pr-3 py-2 text-sm"
        />
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Organisation</th>
                <th className="px-4 py-2.5 font-semibold">Owner</th>
                <th className="px-4 py-2.5 font-semibold">Members</th>
                <th className="px-4 py-2.5 font-semibold">Fleet</th>
                <th className="px-4 py-2.5 font-semibold">Status</th>
                <th className="px-4 py-2.5 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {loading && (
                <tr><td colSpan={6} className="px-4 py-6 text-slate-500">Loading…</td></tr>
              )}
              {!loading && !rows.length && (
                <tr><td colSpan={6} className="px-4 py-6 text-slate-500">No tenants match.</td></tr>
              )}
              {rows.map((o) => (
                <tr key={o.org_id} data-testid={`tenant-row-${o.org_id}`} className="hover:bg-slate-800/40">
                  <td className="px-4 py-2.5">
                    <button onClick={() => openDetail(o)} className="font-semibold text-slate-100 hover:text-amber-300 flex items-center gap-1.5">
                      <Building2 size={14} className="text-slate-500" />
                      {o.name || <span className="italic text-slate-500">unnamed</span>}
                    </button>
                    <p className="text-[11px] text-slate-600 font-mono">{o.org_id}</p>
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{o.owner_email || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-300">{o.member_count}</td>
                  <td className="px-4 py-2.5 text-slate-300">
                    {o.vehicle_count} veh · {o.driver_count} drv
                  </td>
                  <td className="px-4 py-2.5"><StatusPill active={o.active !== false} /></td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <button title="View" data-testid={`tenant-view-${o.org_id}`}
                        onClick={() => openDetail(o)} className="p-1.5 text-slate-500 hover:text-white">
                        <Eye size={15} />
                      </button>
                      {o.active !== false ? (
                        <button title="Suspend" data-testid={`tenant-suspend-${o.org_id}`}
                          onClick={() => setSuspended(o, true)} className="p-1.5 text-slate-500 hover:text-amber-300">
                          <Ban size={15} />
                        </button>
                      ) : (
                        <button title="Reactivate" data-testid={`tenant-reactivate-${o.org_id}`}
                          onClick={() => setSuspended(o, false)} className="p-1.5 text-slate-500 hover:text-emerald-300">
                          <RotateCcw size={15} />
                        </button>
                      )}
                      <button title="Delete" data-testid={`tenant-delete-${o.org_id}`}
                        onClick={() => setDeleting(o)} className="p-1.5 text-slate-500 hover:text-red-400">
                        <Trash2 size={15} />
                      </button>
                    </div>
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

      {detail && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-40" onClick={() => setDetail(null)}>
          <div className="bg-slate-900 border border-slate-800 rounded-md p-5 w-full max-w-lg max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()} data-testid="tenant-detail">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-heading text-xl font-bold text-white">{detail.name || "Unnamed"}</h3>
                <p className="text-[11px] font-mono text-slate-500">{detail.org_id}</p>
              </div>
              <button onClick={() => setDetail(null)} className="text-slate-500 hover:text-white"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-3 gap-3 my-4 text-center">
              {[["Region", detail.region], ["Plan", detail.plan], ["Records", detail.total_records]].map(([k, v]) => (
                <div key={k} className="bg-slate-950 rounded-md py-2">
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">{k}</p>
                  <p className="font-semibold text-slate-200">{v ?? "—"}</p>
                </div>
              ))}
            </div>
            <h4 className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Members</h4>
            <div className="divide-y divide-slate-800/70 mb-4">
              {(detail.members || []).map((m) => (
                <div key={m.user_id} className="py-1.5 flex justify-between text-sm">
                  <span className="text-slate-300">{m.email}</span>
                  <span className="text-slate-500">{m.role}</span>
                </div>
              ))}
            </div>
            <h4 className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Records</h4>
            <div className="grid grid-cols-2 gap-x-4 text-sm">
              {Object.entries(detail.record_counts || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-slate-800/60 py-1">
                  <span className="text-slate-400">{k.replace(/_/g, " ")}</span>
                  <span className="text-slate-200">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {deleting && (
        <DeleteDialog org={deleting} onClose={() => setDeleting(null)}
          onDeleted={() => { setDeleting(null); load(); }} />
      )}
    </div>
  );
}
