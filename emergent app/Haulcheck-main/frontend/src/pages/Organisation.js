import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RegionToggle } from "@/components/RegionToggle";
import {
  Building2, Users, Shield, Eye, Wrench, Crown, Trash2, Save, UserPlus, Copy,
} from "lucide-react";
import { toast } from "sonner";

const ROLES = [
  {
    value: "owner",
    label: "Owner",
    Icon: Crown,
    blurb: "Full control, including members, roles and organisation settings.",
  },
  {
    value: "manager",
    label: "Manager",
    Icon: Wrench,
    blurb: "Can add and edit every compliance record. Cannot manage members.",
  },
  {
    value: "viewer",
    label: "Viewer",
    Icon: Eye,
    blurb: "Read-only. Useful for auditors, insurers and accountants.",
  },
];

const RolePill = ({ role }) => {
  const cfg = ROLES.find((r) => r.value === role) || ROLES[1];
  const tone =
    role === "owner"
      ? "bg-slate-900 text-white"
      : role === "viewer"
      ? "bg-slate-100 text-slate-600"
      : "bg-emerald-100 text-emerald-800";
  return (
    <span
      data-testid={`member-role-${role}`}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${tone}`}
    >
      <cfg.Icon size={12} /> {cfg.label}
    </span>
  );
};

const relTime = (iso) => {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
};

export default function Organisation() {
  const { user, isOwner, checkAuth } = useAuth();
  const [org, setOrg] = useState(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("manager");
  const [inviting, setInviting] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/organisation");
      setOrg(r.data);
      setName(r.data?.name || "");
    } catch {
      toast.error("Could not load your organisation");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const saveName = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.put("/organisation", { name: name.trim() });
      toast.success("Organisation name updated");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not save");
    } finally {
      setSaving(false);
    }
  };

  const invite = async (e) => {
    e.preventDefault();
    setInviting(true);
    try {
      const r = await api.post("/invitations", {
        email: inviteEmail.trim(),
        kind: "org",
        role: inviteRole,
        base_url: window.location.origin,
      });
      if (r.data?.email_sent) toast.success("Invitation sent");
      else toast.warning("Invite created, but the email could not be sent — copy the link instead.");
      if (r.data?.invite_link) {
        try {
          await navigator.clipboard.writeText(r.data.invite_link);
          toast.message("Invite link copied to clipboard");
        } catch {
          /* clipboard unavailable */
        }
      }
      setInviteEmail("");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not send invitation");
    } finally {
      setInviting(false);
    }
  };

  const changeRole = async (memberId, role) => {
    try {
      await api.put(`/organisation/members/${memberId}/role`, { role });
      toast.success("Role updated");
      load();
      if (memberId === user?.user_id) checkAuth();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not change role");
    }
  };

  const removeMember = async (memberId, memberName) => {
    if (
      !window.confirm(
        `Remove ${memberName} from this organisation?\n\nTheir compliance records stay with the organisation — nothing is deleted.`
      )
    )
      return;
    try {
      await api.delete(`/organisation/members/${memberId}`);
      toast.success("Member removed");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not remove member");
    }
  };

  if (loading) {
    return (
      <div data-testid="organisation-loading" className="text-sm text-slate-400">
        Loading organisation…
      </div>
    );
  }

  const members = org?.members || [];

  return (
    <div data-testid="organisation-page">
      <div className="mb-8">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Account</p>
        <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">
          Organisation
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Everyone here shares the same fleet, drivers and compliance records.
        </p>
      </div>

      {/* Details */}
      <section
        className="bg-white border border-slate-200 rounded-md p-5 mb-6"
        data-testid="organisation-details"
      >
        <div className="flex items-center gap-2 mb-4">
          <Building2 size={16} className="text-slate-400" />
          <h2 className="font-heading text-lg font-bold text-slate-900">Details</h2>
        </div>
        <form onSubmit={saveName} className="flex flex-col sm:flex-row sm:items-end gap-3">
          <div className="flex-1">
            <Label htmlFor="org-name" className="text-xs font-semibold text-slate-600">
              Organisation name
            </Label>
            <Input
              id="org-name"
              data-testid="organisation-name-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!isOwner}
              placeholder="e.g. Acme Haulage Ltd"
              className="mt-1"
            />
          </div>
          {isOwner && (
            <Button type="submit" disabled={saving} data-testid="organisation-save-button">
              <Save size={15} className="mr-1.5" />
              {saving ? "Saving…" : "Save"}
            </Button>
          )}
        </form>
        <div className="mt-5 pt-4 border-t border-slate-100">
          <Label className="text-xs font-semibold text-slate-600">Operating region</Label>
          <p className="text-xs text-slate-400 mb-2">
            Sets the rules and terminology for every member — DVSA/MOT in the UK, RSA/CVRT in Ireland.
          </p>
          <RegionToggle />
        </div>
      </section>

      {/* Invite */}
      {isOwner && (
        <section
          className="bg-white border border-slate-200 rounded-md p-5 mb-6"
          data-testid="organisation-invite"
        >
          <div className="flex items-center gap-2 mb-1">
            <UserPlus size={16} className="text-slate-400" />
            <h2 className="font-heading text-lg font-bold text-slate-900">Invite a colleague</h2>
          </div>
          <p className="text-xs text-slate-500 mb-4">
            They join <strong>this</strong> organisation and see the same records. To invite another
            operator to run their own separate account, use the{" "}
            <a href="/team" className="underline">
              Team
            </a>{" "}
            page instead.
          </p>
          <form onSubmit={invite} className="flex flex-col sm:flex-row sm:items-end gap-3">
            <div className="flex-1">
              <Label htmlFor="invite-email" className="text-xs font-semibold text-slate-600">
                Email address
              </Label>
              <Input
                id="invite-email"
                data-testid="organisation-invite-email"
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="colleague@yourcompany.co.uk"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="invite-role" className="text-xs font-semibold text-slate-600">
                Role
              </Label>
              <select
                id="invite-role"
                data-testid="organisation-invite-role"
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="mt-1 block w-full sm:w-40 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              >
                {ROLES.filter((r) => r.value !== "owner").map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit" disabled={inviting} data-testid="organisation-invite-button">
              <Copy size={15} className="mr-1.5" />
              {inviting ? "Sending…" : "Send invite"}
            </Button>
          </form>
          <p className="text-xs text-slate-400 mt-3">
            {ROLES.find((r) => r.value === inviteRole)?.blurb}
          </p>
        </section>
      )}

      {/* Members */}
      <section
        className="bg-white border border-slate-200 rounded-md p-5"
        data-testid="organisation-members"
      >
        <div className="flex items-center gap-2 mb-4">
          <Users size={16} className="text-slate-400" />
          <h2 className="font-heading text-lg font-bold text-slate-900">
            Members <span className="text-slate-400 font-normal">({members.length})</span>
          </h2>
        </div>
        <div className="divide-y divide-slate-100">
          {members.map((m) => (
            <div
              key={m.user_id}
              data-testid={`member-row-${m.user_id}`}
              className="py-3 flex flex-wrap items-center gap-3"
            >
              <div className="flex-1 min-w-[200px]">
                <p className="font-semibold text-sm text-slate-900">
                  {m.name || m.email}
                  {m.user_id === user?.user_id && (
                    <span className="ml-2 text-xs font-normal text-slate-400">you</span>
                  )}
                </p>
                <p className="text-xs text-slate-500">{m.email}</p>
              </div>
              <div className="text-xs text-slate-400 w-28">last active {relTime(m.last_login_at)}</div>
              {isOwner && m.user_id !== user?.user_id ? (
                <select
                  data-testid={`member-role-select-${m.user_id}`}
                  value={m.role}
                  onChange={(e) => changeRole(m.user_id, e.target.value)}
                  className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold"
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              ) : (
                <RolePill role={m.role} />
              )}
              {isOwner && m.user_id !== user?.user_id && (
                <button
                  data-testid={`member-remove-${m.user_id}`}
                  onClick={() => removeMember(m.user_id, m.name || m.email)}
                  className="text-slate-400 hover:text-red-600 transition-colors"
                  title="Remove from organisation"
                >
                  <Trash2 size={15} />
                </button>
              )}
            </div>
          ))}
        </div>
        {!isOwner && (
          <p className="text-xs text-slate-400 mt-4 flex items-center gap-1.5">
            <Shield size={12} /> Only an owner can invite, change roles or remove members.
          </p>
        )}
      </section>
    </div>
  );
}
