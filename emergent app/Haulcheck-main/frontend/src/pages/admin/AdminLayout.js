import { NavLink, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  ShieldCheck, Building2, Users, ScrollText, BarChart3, ArrowLeft, Truck, LogOut,
} from "lucide-react";

const NAV = [
  { to: "/admin", label: "Overview", icon: BarChart3, end: true, id: "overview" },
  { to: "/admin/organisations", label: "Tenants", icon: Building2, id: "tenants" },
  { to: "/admin/users", label: "Users", icon: Users, id: "users" },
  { to: "/admin/audit", label: "Audit log", icon: ScrollText, id: "audit" },
];

/**
 * Shell for the platform console.
 *
 * Deliberately does NOT reuse the tenant Layout. The console operates across
 * every customer, and a visually distinct chrome (dark, badged "PLATFORM") is
 * what stops an operator mistaking someone else's fleet for their own.
 */
export default function AdminLayout({ children }) {
  const { user, loading, isPlatformAdmin, logout } = useAuth();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 text-slate-400">
        <ShieldCheck className="animate-pulse" size={36} />
        <p className="text-sm tracking-widest uppercase">Loading…</p>
      </div>
    );
  }
  // Mirrors the backend, which answers 404 rather than 403 so the console does
  // not confirm it exists to someone who cannot use it.
  if (!user || !isPlatformAdmin) return <Navigate to="/dashboard" replace />;

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100" data-testid="admin-layout">
      <aside className="w-60 shrink-0 hidden md:flex flex-col border-r border-slate-800">
        <div className="px-5 py-5 border-b border-slate-800">
          <div className="flex items-center gap-2 text-amber-400">
            <ShieldCheck size={20} />
            <span className="font-heading font-black tracking-tight">PLATFORM</span>
          </div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500 mt-1">
            Administration
          </p>
        </div>

        <nav className="flex-1 py-4">
          {NAV.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              end={item.end}
              data-testid={`admin-nav-${item.id}`}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm font-semibold transition-colors ${
                  isActive
                    ? "bg-slate-800 text-white border-l-2 border-amber-400"
                    : "text-slate-400 hover:text-white border-l-2 border-transparent"
                }`
              }
            >
              <item.icon size={17} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-800 py-3">
          <button
            data-testid="admin-back-to-app"
            onClick={() => navigate("/dashboard")}
            className="w-full flex items-center gap-3 px-5 py-2.5 text-sm text-slate-400 hover:text-white"
          >
            <ArrowLeft size={16} /> Back to my fleet
          </button>
          <button
            data-testid="admin-logout"
            onClick={logout}
            className="w-full flex items-center gap-3 px-5 py-2.5 text-sm text-slate-400 hover:text-white"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="md:hidden flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-amber-400">
            <ShieldCheck size={18} />
            <span className="font-heading font-black">PLATFORM</span>
          </div>
          <button onClick={() => navigate("/dashboard")} className="text-slate-400">
            <Truck size={18} />
          </button>
        </header>
        <main className="flex-1 p-6 sm:p-8 max-w-[1500px] w-full">{children}</main>
      </div>
    </div>
  );
}
