import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LayoutDashboard, Truck, Users, LogOut, Menu, X, CalendarDays, Globe, Gauge, Building2, Bell, Wrench, Briefcase, UserPlus, FileText } from "lucide-react";
import { useState, useEffect } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { AuditReportDialog } from "@/components/AuditReportDialog";

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
  { to: "/team", label: "Team", icon: UserPlus, id: "team" },
];

export default function Layout({ children }) {
  const { user, logout, updateRegion } = useAuth();
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

        <main className="flex-1 p-6 sm:p-8 md:p-10 max-w-[1680px] w-full mx-auto">{children}</main>
      </div>
      <AuditReportDialog open={auditOpen} onOpenChange={setAuditOpen} />
    </div>
  );
}
