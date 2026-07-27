import { useEffect, useState } from "react";
import api from "@/lib/api";
import { downloadPdf } from "@/lib/download";
import { RegionToggle } from "@/components/RegionToggle";
import { Truck, Users, FolderCheck, FileWarning, AlertTriangle, Sparkles, ShieldCheck, ClipboardCheck, FileDown, Layers, UsersRound } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { AuditReportDialog } from "@/components/AuditReportDialog";
import { DefectAlerts } from "@/components/DefectAlerts";
import { RecallCard } from "@/components/RecallCard";
import { RetentionCard } from "@/components/RetentionCard";
import { ComplianceTrend } from "@/components/ComplianceTrend";
import { useAuth } from "@/context/AuthContext";
import { getTerms } from "@/lib/terms";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// Render inline markdown: **bold** and numbered/bulleted points, preserving line breaks.
function renderBriefing(text) {
  const boldify = (line, keyPrefix) =>
    line.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((seg, i) =>
      seg.startsWith("**") && seg.endsWith("**")
        ? <strong key={`${keyPrefix}-${i}`} className="font-semibold text-slate-900">{seg.slice(2, -2)}</strong>
        : <span key={`${keyPrefix}-${i}`}>{seg}</span>
    );
  return text.split(/\n+/).filter((l) => l.trim()).map((line, i) => (
    <p key={i} className="mb-2 last:mb-0">{boldify(line.trim(), i)}</p>
  ));
}

const scoreColor = (s) => (s >= 85 ? "text-green-600" : s >= 60 ? "text-yellow-600" : "text-red-600");
const scoreRing = (s) => (s >= 85 ? "#16A34A" : s >= 60 ? "#EAB308" : "#DC2626");

function Kpi({ icon: Icon, label, value, tone, testid, delay }) {
  return (
    <div data-testid={testid} className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-[0.15em] text-slate-500 font-semibold">{label}</p>
        <Icon size={18} className="text-slate-400" />
      </div>
      <p className={cn("font-heading text-4xl font-black mt-3 tracking-tight", tone)}>{value}</p>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const [data, setData] = useState(null);
  const [insight, setInsight] = useState("");
  const [checklist, setChecklist] = useState([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [emailMsg, setEmailMsg] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  const sendPack = async () => {
    const to = emailTo.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
    if (!to.length) { toast.error("Enter at least one email address"); return; }
    setEmailBusy(true);
    try {
      const { data } = await api.post("/export/account/email", { to, message: emailMsg });
      toast.success(`Audit pack emailed (${data.filename})`);
      setEmailOpen(false); setEmailTo(""); setEmailMsg("");
    } catch { toast.error("Could not send audit pack"); }
    setEmailBusy(false);
  };

  const load = async () => {
    const res = await api.get("/dashboard");
    setData(res.data);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const runAi = async () => {
    setAiBusy(true);
    try {
      const res = await api.post("/ai/risk-insight");
      setInsight(res.data.insight);
      setChecklist(res.data.checklist || []);
    } finally {
      setAiBusy(false);
    }
  };

  if (!data) return <div className="text-slate-400">Loading dashboard…</div>;
  const { counts, alerts, risk_score, risk_band, registered_users } = data;
  const circumference = 2 * Math.PI * 52;
  const offset = circumference - (risk_score / 100) * circumference;

  return (
    <div data-testid="dashboard-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance Control Room</p>
          <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Fleet Overview</h1>
        </div>
        <div className="flex gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button data-testid="export-report-button" variant="outline" className="border-slate-300 rounded-md gap-2">
                <FileDown size={16} /> Export PDF
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem data-testid="export-summary" onClick={() => downloadPdf("/export/account", "fleet-compliance-report.pdf")}>
                Compliance report (summary)
              </DropdownMenuItem>
              <DropdownMenuItem data-testid="export-with-files" onClick={() => downloadPdf("/export/account?include_files=true", null)}>
                Audit Pack (report + all evidence, dated)
              </DropdownMenuItem>
              <DropdownMenuItem data-testid="email-audit-pack" onClick={() => setEmailOpen(true)}>
                Email Audit Pack…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button data-testid="ai-insight-button" onClick={runAi} disabled={aiBusy} className="bg-black hover:bg-slate-800 rounded-md gap-2">
            <Sparkles size={16} /> {aiBusy ? "Analysing…" : "AI Risk Briefing"}
          </Button>
          <RegionToggle />
        </div>
      </div>

      <div data-testid="registered-users-counter" className="flex items-center justify-between gap-4 bg-gradient-to-r from-slate-900 to-slate-800 text-white rounded-md px-6 py-4 mb-6 animate-in-up">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-white/10 flex items-center justify-center"><UsersRound size={22} /></div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400 font-semibold">Registered Users</p>
            <p className="text-sm text-slate-300">People using HaulCheck</p>
          </div>
        </div>
        <span data-testid="registered-users-value" className="font-heading text-4xl font-black tabular-nums">{registered_users ?? 0}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Risk score */}
        <div className="bg-slate-900 text-white rounded-md p-6 flex items-center gap-6 animate-in-up">
          <div className="relative w-32 h-32 shrink-0">
            <svg className="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="52" fill="none" stroke="#334155" strokeWidth="10" />
              <circle cx="60" cy="60" r="52" fill="none" stroke={scoreRing(risk_score)} strokeWidth="10"
                strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" style={{ transition: "stroke-dashoffset 1s ease-out" }} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span data-testid="risk-score-value" className="font-heading text-4xl font-black">{risk_score}</span>
              <span className="text-[10px] text-slate-400 uppercase tracking-widest">Score</span>
            </div>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400 font-semibold">Compliance Health</p>
            <p className="font-heading text-2xl font-bold mt-1">{risk_band}</p>
            <p className="text-sm text-slate-400 mt-2">{counts.expired} expired · {counts.due_soon} due soon</p>
          </div>
        </div>

        {/* AI insight */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-md p-6 animate-in-up" style={{ animationDelay: "80ms" }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2">
              <Sparkles size={18} className="text-slate-900" />
              <h3 className="font-heading font-bold text-lg tracking-tight">AI Compliance Briefing</h3>
            </div>
            <span data-testid="ai-authority-badge" title={`Applying ${terms.authority} (${terms.label}) rules`} className="text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full bg-slate-900 text-white shrink-0">{terms.authority}</span>
          </div>
          {insight ? (
            <div data-testid="ai-insight-text" className="text-slate-700 text-sm leading-relaxed">{renderBriefing(insight)}</div>
          ) : (
            <p className="text-slate-400 text-sm">Click <strong>AI Risk Briefing</strong> to generate a prioritised action plan and a live audit checklist of any missing mandatory records for your operator licence.</p>
          )}
          {checklist.length > 0 && (
            <div className="mt-4" data-testid="ai-checklist">
              <p className="text-xs uppercase tracking-[0.15em] text-slate-500 font-semibold mb-2">AI Audit Checklist — {checklist.length} item{checklist.length !== 1 && "s"}</p>
              <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                {checklist.map((g, i) => (
                  <div key={i} data-testid="checklist-item" className="flex items-center gap-2 text-sm border border-slate-100 rounded-md px-3 py-2">
                    <span className={cn("text-[10px] font-bold uppercase px-1.5 py-0.5 rounded shrink-0",
                      g.priority === "high" ? "bg-red-100 text-red-700" : g.priority === "medium" ? "bg-yellow-100 text-yellow-800" : "bg-slate-100 text-slate-500")}>{g.priority}</span>
                    <span className="text-slate-400 text-[10px] uppercase tracking-wider w-20 shrink-0">{g.area}</span>
                    <span className="text-slate-700 min-w-0">{g.item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        <Kpi testid="kpi-vehicles" icon={Truck} label="Vehicles" value={counts.vehicles} tone="text-slate-900" delay={0} />
        <Kpi testid="kpi-drivers" icon={Users} label="Drivers" value={counts.drivers} tone="text-slate-900" delay={60} />
        <Kpi testid="kpi-pmi" icon={ClipboardCheck} label="PMI Schedules" value={counts.pmi ?? 0} tone="text-slate-900" delay={120} />
        <button data-testid="kpi-audit-reports" onClick={() => setAuditOpen(true)} className="text-left bg-slate-900 text-white rounded-md p-5 hover:-translate-y-1 hover:shadow-md transition-all duration-200 animate-in-up" style={{ animationDelay: "180ms" }}>
          <div className="flex items-center justify-between">
            <p className="text-xs uppercase tracking-[0.15em] text-slate-300 font-semibold">Audit Reports</p>
            <Layers size={18} className="text-slate-400" />
          </div>
          <p className="font-heading text-lg font-bold mt-3 tracking-tight leading-tight">View · Print · PDF</p>
          <p className="text-[11px] text-slate-400 mt-1">Whole fleet or by section</p>
        </button>
        <Kpi testid="kpi-documents" icon={FolderCheck} label="Documents" value={counts.documents} tone="text-slate-900" delay={240} />
        <Kpi testid="kpi-defects" icon={FileWarning} label="Open Defects" value={counts.open_defects} tone={counts.open_defects ? "text-red-600" : "text-slate-900"} delay={300} />
      </div>

      <ComplianceTrend />

      <RecallCard />

      <RetentionCard />

      <DefectAlerts />

      {/* Alerts feed */}
      <div className="bg-white border border-slate-200 rounded-md overflow-hidden animate-in-up">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center gap-2">
          <AlertTriangle size={18} className="text-slate-900" />
          <h3 className="font-heading font-bold tracking-tight">Compliance Alerts</h3>
        </div>
        {alerts.length === 0 ? (
          <div className="p-10 text-center text-slate-500 flex flex-col items-center gap-2">
            <ShieldCheck size={32} className="text-green-500" />
            <p className="font-semibold text-slate-700">All clear</p>
            <p className="text-sm">No expired or upcoming compliance items.</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {alerts.map((a, i) => (
              <div key={`${a.type}-${a.name}-${a.item}-${i}`} data-testid="alert-row" className="flex items-center justify-between px-5 py-3.5 hover:bg-slate-50 transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold w-20 shrink-0">{a.type}</span>
                  <div className="min-w-0">
                    <p className="font-semibold text-slate-900 text-sm truncate">{a.name}</p>
                    <p className="text-xs text-slate-500">{a.item}{a.days != null && ` · ${a.days < 0 ? `${Math.abs(a.days)}d overdue` : `${a.days}d left`}`}</p>
                  </div>
                </div>
                <StatusBadge status={a.status} />
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={emailOpen} onOpenChange={setEmailOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">Email Audit Pack</DialogTitle>
            <DialogDescription>Sends the full compliance report + all evidence as a single branded PDF attachment.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">Recipient email(s)</label>
              <Input data-testid="email-pack-to" value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="auditor@dvsa.gov.uk, me@company.com" />
              <p className="text-xs text-slate-400 mt-1">Separate multiple addresses with commas.</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">Message (optional)</label>
              <Textarea data-testid="email-pack-message" rows={3} value={emailMsg} onChange={(e) => setEmailMsg(e.target.value)} placeholder="Please find our compliance audit pack attached." />
            </div>
            <DialogFooter>
              <Button data-testid="send-audit-pack-button" onClick={sendPack} disabled={emailBusy} className="bg-black hover:bg-slate-800">{emailBusy ? "Sending…" : "Send Audit Pack"}</Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <AuditReportDialog open={auditOpen} onOpenChange={setAuditOpen} />
    </div>
  );
}
