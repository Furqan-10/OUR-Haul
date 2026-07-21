import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { useNavigate } from "react-router-dom";
import { Bell, AlertTriangle, X, Check, ChevronRight } from "lucide-react";
import { toast } from "sonner";

const SEV = {
  safety_critical: "bg-red-100 text-red-700 border-red-200",
  major: "bg-orange-100 text-orange-700 border-orange-200",
  minor: "bg-yellow-100 text-yellow-800 border-yellow-200",
};

export function DefectAlerts() {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);

  const load = useCallback(async () => {
    try { setAlerts((await api.get("/alerts")).data); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const unread = alerts.filter((a) => !a.read).length;
  const markRead = async (id) => { await api.patch(`/alerts/${id}/read`); load(); };
  const remove = async (id) => { await api.delete(`/alerts/${id}`); load(); };
  const markAll = async () => { await api.post("/alerts/read-all"); toast.success("All alerts marked read"); load(); };

  if (alerts.length === 0) return null;

  return (
    <div data-testid="defect-alerts-panel" className="bg-white border border-slate-200 rounded-md p-5 animate-in-up">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Bell size={18} className="text-slate-900" />
            {unread > 0 && <span data-testid="alerts-unread-badge" className="absolute -top-1.5 -right-1.5 bg-red-600 text-white text-[9px] font-bold rounded-full min-w-[15px] h-[15px] flex items-center justify-center px-1">{unread}</span>}
          </div>
          <h3 className="font-heading font-bold text-base tracking-tight">Defect Alerts</h3>
        </div>
        {unread > 0 && <button data-testid="alerts-mark-all" onClick={markAll} className="text-xs font-semibold text-slate-500 hover:text-slate-900">Mark all read</button>}
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {alerts.slice(0, 20).map((a) => (
          <div key={a.id} data-testid="defect-alert-item" className={`flex items-start gap-3 rounded-md border p-3 ${a.read ? "border-slate-100 opacity-60" : "border-slate-200"}`}>
            <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${a.severity === "safety_critical" ? "text-red-600" : a.severity === "major" ? "text-orange-500" : "text-yellow-500"}`} />
            <button onClick={() => { markRead(a.id); if (a.link) navigate(a.link); }} className="min-w-0 flex-1 text-left">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-slate-900">{a.title}</span>
                <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full border ${SEV[a.severity] || SEV.minor}`}>{a.severity.replace("_", " ")}</span>
                {!a.read && <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />}
              </div>
              {a.message && <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{a.message}</p>}
              <p className="text-[11px] text-slate-400 mt-1">{a.driver_name ? `${a.driver_name} · ` : ""}{new Date(a.created_at).toLocaleString()} <ChevronRight size={11} className="inline" /></p>
            </button>
            <div className="flex items-center gap-1 shrink-0">
              {!a.read && <button data-testid="alert-mark-read" onClick={() => markRead(a.id)} title="Mark read" className="text-slate-300 hover:text-green-600"><Check size={15} /></button>}
              <button data-testid="alert-delete" onClick={() => remove(a.id)} title="Dismiss" className="text-slate-300 hover:text-red-600"><X size={15} /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
