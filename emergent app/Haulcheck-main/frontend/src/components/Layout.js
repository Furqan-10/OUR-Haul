import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LayoutDashboard, Truck, Users, LogOut, Menu, X, CalendarDays, Globe, Gauge, Building2, Bell, Wrench, Briefcase, UserPlus, FileText, MailWarning, Eye, ShieldCheck } from "lucide-react";
import { useState, useEffect } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { AuditReportDialog } from "@/components/AuditReportDialog";

/**
 * Persistent, unmissable marker that this is a support session viewing someone
 * else's account.
 *
 * Loud on purpose. The single worst outcome of impersonation is an operator
 * forgetting they are in it and reading another company's compliance data as
 * their own — so this cannot be dismissed, and it states whose account it is.
 * Writes are refused by the backend regardless; this exists so nobody is
 * confused about what they are looking at.
 */
function ImpersonationBanner() {
  const { user } = useAuth();
  if (!user?.impersonated_by) return null;
  let ctx = {};
  try { ctx = JSON.parse(localStorage.getItem("impersonating") || "{}"); } catch { /* ignore */ }

  const exit = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("impersonating");
    window.location.href = "/login";
  };

  return (
    <div data-testid="impersonation-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-sky-900 text-sky-50 px-4 sm:px-8 py-2.5 text-sm border-b border-sky-700">
      <Eye size={16} className="shrink-0" />
      <span className="flex-1 min-w-[200px]">
        <strong>Read-only support session</strong>
        {ctx.email ? <> — viewing <strong>{ctx.email}</strong></> : null}
        {ctx.org ? <> at <strong>{ctx.org}</strong></> : null}
        . Changes are disabled and this session is recorded.
      </span>
      <button data-testid="exit-impersonation" onClick={exit}
        className="font-semibold underline hover:no-underline">
        End session
      </button>
    </div>
  );
}

// Non-blocking prompt to confirm the account's email address. Access is not
// restricted while unverified; this is a reminder, not a gate. Accounts that
// predate email verification are grandfathered as verified server-side, so the
// banner only appears for newly registered users.
function VerifyEmailBanner() {
  const { user, checkAuth } = useAuth();
  const [sending, setSending] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (!user || user.email_verified !== false || dismissed) return null;

  const resend = async () => {
    setSending(true);
    try {
      await api.post("/auth/resend-verification");
      toast.success("Confirmation email sent — check your inbox.");
    } catch {
      toast.error("Could not send the confirmation email just now.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div data-testid="verify-email-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 bg-amber-50 border-b border-amber-200 text-amber-900 px-4 sm:px-8 py-2.5 text-sm">
      <MailWarning size={16} className="shrink-0" />
      <span className="flex-1 min-w-[180px]">
        Confirm your email address to secure your account.
      </span>
      <button data-testid="resend-verification" onClick={resend} disabled={sending}
        className="font-semibold underline hover:no-underline disabled:opacity-50">
        {sending ? "Sending…" : "Resend link"}
      </button>
      <button data-testid="dismiss-verify-banner" onClick={() => { setDismissed(true); checkAuth?.(); }}
        className="text-amber-500 hover:text-amber-800" aria-label="Dismiss">
        <X size={15} />
      </button>
    </div>
  );
}

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, id: "dashboard" },
  { to: "/operator", label: "Operator", icon: Building2, id: "operator" },
  { to: "/calendar", label: "Calendar", icon: CalendarDays, id: "calendar" },
  { to: "/maintenance", label: "Maintenance", icon: Wrench, id: "maintenance" },
  { to: "/vehicles", label: "Fleet", icon: Truck, id: "vehicles" },
  { to: "/drivers", label: "Drivers", icon: Users, id: "drivers" },
  { to: "/tacho", label: "Tacho Portal", icon: Gauge, id: "tacho" },
  { to: "/office", label: "Office", icon: Briefcase, id: "office" },
  { to: "/reminders", label: "Reminders", icon: Bell, id: "reminders" },
  { to: "/organisation", label: "Organisation", icon: Building2, id: "organisation" },
  { to: "/team", label: "Team", icon: UserPlus, id: "team" },
];

export default function Layout({ children }) {
  const { user, logout, updateRegion, isPlatformAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [auditOpen, setAuditOpen] = useState(false);

  const AuditButton = () => (
    <div className="px-3 pb-3">
      <button
        data-testid="fleet-audit-button"
        onClick={() => { setAuditOpen(true); setOpen(false); }}
        className="w-full flex items-center justify-center gap-2 bg-white text-slate-900 hover:bg-slate-100 font-semibold text-sm rounded-md py-2.5 transition-colors"
      >
        <FileText size={16} /> Fleet Audit Report
      </button>
    </div>
  );

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const { data } = await api.get("/alerts/unread-count");
        if (active) setUnread(data.count || 0);
      } catch { /* ignore */ }
    };
    poll();
    const t = setInterval(poll, 60000);
    return () => { active = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    document.title = unread > 0 ? `(${unread}) HaulCheck — Defect alerts` : "HaulCheck";
  }, [unread]);

  const RegionSwitcher = () => (
    <div className="px-4 pb-3" data-testid="region-switcher">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500 font-semibold mb-2 flex items-center gap-1.5"><Globe size={12} /> Jurisdiction</p>
      <div className="flex gap-1 bg-slate-800 rounded-md p-1">
        {[{ c: "UK", l: "UK · DVSA" }, { c: "IE", l: "IE · RSA" }].map((r) => (
          <button
            key={r.c}
            data-testid={`region-${r.c}`}
            onClick={async () => { try { await updateRegion(r.c); toast.success(`Switched to ${r.c === "UK" ? "United Kingdom (DVSA)" : "Ireland (RSA)"}`); } catch { toast.error("Could not switch region"); } }}
            className={cn(
              "flex-1 py-1.5 text-xs font-semibold rounded transition-all",
              (user?.region || "UK") === r.c ? "bg-white text-slate-900" : "text-slate-400 hover:text-white"
            )}
          >{r.l}</button>
        ))}
      </div>
    </div>
  );

  const NavItems = () => (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          data-testid={`nav-${item.id}`}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 px-4 py-3 text-sm font-semibold transition-all duration-200 border-l-2",
              isActive
                ? "bg-slate-800 text-white border-white"
                : "text-slate-400 border-transparent hover:text-white hover:bg-slate-800/60"
            )
          }
        >
          <item.icon size={20} />
          {item.label}
          {item.id === "dashboard" && unread > 0 && (
            <span data-testid="nav-alert-badge" className="ml-auto bg-red-600 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">{unread}</span>
          )}
        </NavLink>
      ))}
      {/* Only platform administrators see a way into the console; the backend
          answers 404 for everyone else regardless. */}
      {isPlatformAdmin && (
        <NavLink
          to="/admin"
          data-testid="nav-platform-admin"
          onClick={() => setOpen(false)}
          className="flex items-center gap-3 px-4 py-3 text-sm font-semibold text-amber-400 border-l-2 border-transparent hover:bg-slate-800/60 mt-2 border-t border-slate-800 pt-4"
        >
          <ShieldCheck size={20} />
          Platform Admin
        </NavLink>
      )}
    </nav>
  );

  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-52 flex-col bg-slate-900 text-white sticky top-0 h-screen">
        <div className="px-6 py-6 flex items-center gap-2 border-b border-slate-800">
          <Truck size={26} className="text-white" />
          <div>
            <p className="font-heading font-black text-lg leading-none tracking-tight">HAULCHECK</p>
            <p className="text-[10px] tracking-[0.25em] text-slate-400 uppercase mt-1">Compliance</p>
          </div>
        </div>
        <div className="flex-1 py-4 overflow-y-auto"><NavItems /></div>
        <AuditButton />
        <div className="border-t border-slate-800 pt-3">
          <RegionSwitcher />
        </div>
        <div className="border-t border-slate-800 p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-full bg-slate-700 flex items-center justify-center text-sm font-bold">
              {user?.name?.[0]?.toUpperCase() || "U"}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate">{user?.name}</p>
              <p className="text-xs text-slate-400 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            data-testid="logout-button"
            onClick={logout}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors w-full px-2 py-2"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>

      {/* Mobile header */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="md:hidden flex items-center justify-between bg-slate-900 text-white px-4 py-3 sticky top-0 z-30">
          <div className="flex items-center gap-2">
            <Truck size={22} />
            <span className="font-heading font-black tracking-tight">HAULCHECK</span>
          </div>
          <button data-testid="mobile-menu-toggle" onClick={() => setOpen(!open)}>
            {open ? <X size={24} /> : <Menu size={24} />}
          </button>
        </header>
        {open && (
          <div className="md:hidden bg-slate-900 text-white pb-4">
            <NavItems />
            <div className="mt-2"><AuditButton /></div>
            <div className="border-t border-slate-800 mt-2 pt-3"><RegionSwitcher /></div>
            <button
              data-testid="mobile-logout-button"
              onClick={logout}
              className="flex items-center gap-2 text-sm text-slate-400 px-4 py-3"
            >
              <LogOut size={16} /> Sign out
            </button>
          </div>
        )}

        <ImpersonationBanner />
        <VerifyEmailBanner />
        <main className="flex-1 p-6 sm:p-8 md:p-10 max-w-[1680px] w-full mx-auto">
          {/* Reads org_role, not role: a viewer is a member of the organisation
              with a read-only role, so `role` is "manager" for them like everyone
              else. Without this banner the app silently rejects every save. */}
          {user?.org_role === "viewer" && (
            <div data-testid="viewer-banner" className="mb-6 flex items-center gap-2 rounded-md border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-800">
              <Globe size={15} className="shrink-0" />
              <span><span className="font-semibold">Read-only access.</span> You can view everything but changes are disabled.</span>
            </div>
          )}
          {children}
        </main>
      </div>
      <AuditReportDialog open={auditOpen} onOpenChange={setAuditOpen} />
    </div>
  );
}
