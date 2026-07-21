import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UserPlus, Mail, Copy, Trash2, CheckCircle2, Clock, Ban, RotateCcw, ShieldCheck, Users } from "lucide-react";
import { toast } from "sonner";

const StatusPill = ({ inv }) => {
  let cfg;
  if (inv.status === "accepted" && inv.active === false) cfg = { label: "Suspended", cls: "bg-red-100 text-red-700", Icon: Ban };
  else if (inv.status === "accepted") cfg = { label: "Active", cls: "bg-emerald-100 text-emerald-800", Icon: CheckCircle2 };
  else cfg = { label: "Pending", cls: "bg-amber-100 text-amber-800", Icon: Clock };
  const { label, cls, Icon } = cfg;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      <Icon size={12} /> {label}
    </span>
  );
};

const relTime = (iso) => {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
};

export default function Team() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const r = await api.get("/invitations");
      setInvites(r.data || []);
    } catch { toast.error("Could not load invitations"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const invite = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.post("/invitations", { email: email.trim(), base_url: window.location.origin });
      if (res.data?.email_sent) {
        toast.success("Invitation email sent");
      } else {
        toast.warning("Invite created, but the email could not be sent — link copied instead. Share it directly with the operator.");
      }
      if (res.data?.invite_link) {
        try { await navigator.clipboard.writeText(res.data.invite_link); toast.message("Invite link copied to clipboard"); } catch { /* ignore */ }
      }
      setEmail("");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not send invitation");
    } finally { setBusy(false); }
  };

  const copyLink = (token) => {
    const link = `${window.location.origin}/accept-invite?token=${token}`;
    navigator.clipboard.writeText(link).then(() => toast.success("Invite link copied")).catch(() => toast.error("Could not copy"));
  };

  const revoke = async (id) => {
    try { await api.delete(`/invitations/${id}`); toast.success("Invitation removed"); load(); }
    catch { toast.error("Could not remove invitation"); }
  };

  const setMemberStatus = async (id, active) => {
    try {
      await api.put(`/invitations/${id}/member-status`, { active });
      toast.success(active ? "Member reactivated" : "Member deactivated");
      load();
    } catch (err) { toast.error(err.response?.data?.detail || "Could not update member"); }
  };

  const activeCount = invites.filter((i) => i.status === "accepted" && i.active !== false).length;
  const pendingCount = invites.filter((i) => i.status === "pending").length;
  const suspendedCount = invites.filter((i) => i.status === "accepted" && i.active === false).length;

  return (
    <div data-testid="team-page">
      <div className="mb-8">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Account</p>
        <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Team &amp; Users</h1>
        <p className="text-slate-500 text-sm mt-1">Invite other operators to set up their own isolated compliance account, pre-seeded with your links &amp; reminder template.</p>
      </div>

      {/* At-a-glance summary */}
      <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-6" data-testid="team-summary">
        <div className="bg-white border border-slate-200 rounded-md p-4 animate-in-up" data-testid="summary-active">
          <div className="flex items-center gap-2 text-emerald-700">
            <Users size={16} />
            <span className="text-xs font-semibold uppercase tracking-wider">Active</span>
          </div>
          <p className="font-heading text-2xl sm:text-3xl font-black text-slate-900 mt-1">{activeCount}</p>
          <p className="text-xs text-slate-400 mt-0.5">on their own records</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-md p-4 animate-in-up" data-testid="summary-pending">
          <div className="flex items-center gap-2 text-amber-700">
            <Clock size={16} />
            <span className="text-xs font-semibold uppercase tracking-wider">Pending</span>
          </div>
          <p className="font-heading text-2xl sm:text-3xl font-black text-slate-900 mt-1">{pendingCount}</p>
          <p className="text-xs text-slate-400 mt-0.5">not yet accepted</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-md p-4 animate-in-up" data-testid="summary-suspended">
          <div className="flex items-center gap-2 text-red-700">
            <Ban size={16} />
            <span className="text-xs font-semibold uppercase tracking-wider">Suspended</span>
          </div>
          <p className="font-heading text-2xl sm:text-3xl font-black text-slate-900 mt-1">{suspendedCount}</p>
          <p className="text-xs text-slate-400 mt-0.5">access revoked</p>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Invite form */}
        <div className="bg-white border border-slate-200 rounded-md p-6 animate-in-up">
          <div className="flex items-center gap-2 mb-5">
            <UserPlus size={18} className="text-slate-900" />
            <h3 className="font-heading font-bold text-lg tracking-tight">Invite an operator</h3>
          </div>
          <form onSubmit={invite} className="space-y-4">
            <div>
              <Label htmlFor="invite-email">Email address</Label>
              <Input data-testid="invite-email-input" id="invite-email" type="email" required value={email}
                onChange={(e) => setEmail(e.target.value)} placeholder="operator@company.co.uk" className="mt-1.5" />
            </div>
            <Button data-testid="send-invite-button" type="submit" disabled={busy}
              className="w-full bg-black hover:bg-slate-800 rounded-md gap-2">
              <Mail size={16} /> {busy ? "Sending…" : "Send invitation"}
            </Button>
            <p className="text-xs text-slate-400 leading-relaxed">The invitee receives an email with a secure link to choose a password. Their account is completely separate from yours — they can only view and edit their own records.</p>
          </form>
        </div>

        {/* Invites list */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-md p-6 animate-in-up">
          <h3 className="font-heading font-bold text-lg tracking-tight mb-5">Sent invitations</h3>
          {loading ? (
            <p className="text-sm text-slate-400">Loading…</p>
          ) : invites.length === 0 ? (
            <p className="text-sm text-slate-400" data-testid="no-invites">No invitations sent yet.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {invites.map((inv) => (
                <div key={inv.id} data-testid={`invite-row-${inv.id}`} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900 truncate">{inv.member_name || inv.email}</p>
                    <p className="text-xs text-slate-400 truncate">
                      {inv.member_name ? `${inv.email} · ` : ""}
                      {inv.status === "accepted"
                        ? `Activated ${inv.accepted_at ? new Date(inv.accepted_at).toLocaleDateString() : "—"} · last active ${relTime(inv.last_login_at)}`
                        : `Invited ${new Date(inv.created_at).toLocaleDateString()}`}
                    </p>
                    {inv.status === "accepted" && (
                      <span data-testid={`isolated-badge-${inv.id}`} className="inline-flex items-center gap-1 mt-1 text-[11px] font-medium text-slate-500">
                        <ShieldCheck size={12} className="text-emerald-600" /> Own isolated records
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <StatusPill inv={inv} />
                    {inv.status === "pending" && (
                      <>
                        <Button data-testid={`copy-invite-${inv.id}`} variant="outline" size="sm" className="rounded-md gap-1.5 h-8"
                          onClick={() => copyLink(inv.token)} title="Copy invite link">
                          <Copy size={14} />
                        </Button>
                        <Button data-testid={`revoke-invite-${inv.id}`} variant="outline" size="sm" className="rounded-md h-8 text-red-600 hover:text-red-700 hover:bg-red-50"
                          onClick={() => revoke(inv.id)} title="Revoke">
                          <Trash2 size={14} />
                        </Button>
                      </>
                    )}
                    {inv.status === "accepted" && inv.active !== false && (
                      <Button data-testid={`deactivate-member-${inv.id}`} variant="outline" size="sm" className="rounded-md gap-1.5 h-8 text-red-600 hover:text-red-700 hover:bg-red-50"
                        onClick={() => setMemberStatus(inv.id, false)} title="Deactivate account">
                        <Ban size={14} /> Deactivate
                      </Button>
                    )}
                    {inv.status === "accepted" && inv.active === false && (
                      <Button data-testid={`reactivate-member-${inv.id}`} variant="outline" size="sm" className="rounded-md gap-1.5 h-8 text-emerald-700 hover:text-emerald-800 hover:bg-emerald-50"
                        onClick={() => setMemberStatus(inv.id, true)} title="Reactivate account">
                        <RotateCcw size={14} /> Reactivate
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
