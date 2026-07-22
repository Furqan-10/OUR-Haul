import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Search, Ban, RotateCcw, LogIn, KeyRound, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

const PAGE = 25;

const relTime = (iso) => {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days < 30 ? `${days}d ago` : new Date(iso).toLocaleDateString();
};

export default function AdminUsers() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/admin/users", { params: { q, limit: PAGE, offset } });
      setRows(r.data.users || []);
      setTotal(r.data.total || 0);
    } catch {
      toast.error("Could not load users");
    } finally {
      setLoading(false);
    }
  }, [q, offset]);

  useEffect(() => { load(); }, [load]);

  const act = async (user, path, message) => {
    try {
      await api.post(`/admin/users/${user.user_id}/${path}`);
      toast.success(message);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Action failed");
    }
  };

  /**
   * Start a read-only support session as this user.
   *
   * The impersonation token replaces the stored session token, so the whole app
   * renders the customer's world. The original admin session is deliberately
   * NOT preserved — signing back in is a small price for making it impossible
   * to act with admin rights while impersonating.
   */
  const impersonate = async (user) => {
    if (!window.confirm(
      `Start a read-only support session as ${user.email}?\n\n` +
      `You will see their account exactly as they do and cannot make changes. ` +
      `This is recorded in the audit log. You will need to sign in again afterwards.`
    )) return;
    try {
      const r = await api.post(`/admin/impersonate/${user.user_id}`);
      localStorage.setItem("token", r.data.token);
      localStorage.setItem("impersonating", JSON.stringify({
        email: user.email, org: r.data.organisation?.name || "",
      }));
      toast.success("Read-only session started");
      window.location.href = "/dashboard";
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not start session");
    }
  };

  return (
    <div data-testid="admin-users">
      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500 font-semibold">Platform</p>
      <h1 className="font-heading text-3xl font-black tracking-tight text-white mt-1 mb-5">
        Users <span className="text-slate-600 font-normal text-2xl">({total})</span>
      </h1>

      <div className="relative mb-4 max-w-md">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          data-testid="user-search"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
          placeholder="Search by email or name…"
          className="w-full bg-slate-900 border border-slate-800 rounded-md pl-9 pr-3 py-2 text-sm"
        />
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[860px]">
            <thead className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <tr>
                <th className="px-4 py-2.5 font-semibold">User</th>
                <th className="px-4 py-2.5 font-semibold">Organisation</th>
                <th className="px-4 py-2.5 font-semibold">Last active</th>
                <th className="px-4 py-2.5 font-semibold">Status</th>
                <th className="px-4 py-2.5 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {loading && <tr><td colSpan={5} className="px-4 py-6 text-slate-500">Loading…</td></tr>}
              {!loading && !rows.length && (
                <tr><td colSpan={5} className="px-4 py-6 text-slate-500">No users match.</td></tr>
              )}
              {rows.map((u) => (
                <tr key={u.user_id} data-testid={`user-row-${u.user_id}`} className="hover:bg-slate-800/40">
                  <td className="px-4 py-2.5">
                    <p className="font-semibold text-slate-100 flex items-center gap-1.5">
                      {u.name || u.email}
                      {u.platform_role === "platform_admin" && (
                        <ShieldCheck size={13} className="text-amber-400" title="Platform administrator" />
                      )}
                    </p>
                    <p className="text-xs text-slate-500">{u.email}</p>
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">
                    {u.org_name || <span className="italic text-slate-600">none</span>}
                    {u.org_active === false && <span className="ml-1.5 text-red-400 text-[11px]">(suspended)</span>}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{relTime(u.last_login_at)}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                      u.active === false ? "bg-red-500/15 text-red-300" : "bg-emerald-500/15 text-emerald-300"
                    }`}>
                      {u.active === false ? "Suspended" : "Active"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <button title="Read-only support session" data-testid={`user-impersonate-${u.user_id}`}
                        onClick={() => impersonate(u)} className="p-1.5 text-slate-500 hover:text-amber-300">
                        <LogIn size={15} />
                      </button>
                      <button title="Sign out everywhere" data-testid={`user-revoke-${u.user_id}`}
                        onClick={() => act(u, "revoke-sessions", "Sessions revoked")}
                        className="p-1.5 text-slate-500 hover:text-sky-300">
                        <KeyRound size={15} />
                      </button>
                      {u.active === false ? (
                        <button title="Reactivate" data-testid={`user-reactivate-${u.user_id}`}
                          onClick={() => act(u, "reactivate", "User reactivated")}
                          className="p-1.5 text-slate-500 hover:text-emerald-300">
                          <RotateCcw size={15} />
                        </button>
                      ) : (
                        <button title="Suspend" data-testid={`user-suspend-${u.user_id}`}
                          onClick={() => act(u, "suspend", "User suspended")}
                          className="p-1.5 text-slate-500 hover:text-red-400">
                          <Ban size={15} />
                        </button>
                      )}
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
    </div>
  );
}
