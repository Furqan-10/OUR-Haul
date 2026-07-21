import { useEffect, useState } from "react";
import api from "@/lib/api";
import { downloadPdf } from "@/lib/download";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Printer, FileDown, Loader2, Layers } from "lucide-react";
import { toast } from "sonner";

const REPORT_KINDS = [
  { value: "audit", label: "Full Fleet Audit (RSA / DVSA)" },
  { value: "vehicles", label: "Vehicles" },
  { value: "trailers", label: "Trailers" },
  { value: "drivers", label: "Drivers" },
  { value: "pmi", label: "PMI Inspections" },
  { value: "defects", label: "Defect Reports" },
  { value: "service", label: "Vehicles Service" },
  { value: "wheel", label: "Wheel Security" },
  { value: "walkaround", label: "Daily Walkaround Checks" },
  { value: "tacho", label: "Tacho Analyses" },
];

const STATUS = {
  valid: { bg: "#DCFCE7", fg: "#15803D" },
  due_soon: { bg: "#FEF9C3", fg: "#854D0E" },
  expired: { bg: "#FEE2E2", fg: "#B91C1C" },
  unknown: { bg: "#F1F5F9", fg: "#64748B" },
};

const pill = (s) => STATUS[s] || STATUS.unknown;

function StatusPill({ status }) {
  const c = pill(status);
  return <span data-testid="report-status-pill" className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: c.bg, color: c.fg }}>{(status || "unknown").replace("_", " ")}</span>;
}

export function AuditReportDialog({ open, onOpenChange }) {
  const [kind, setKind] = useState("audit");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const rangeQs = () => {
    const p = [];
    if (from) p.push(`from_date=${from}`);
    if (to) p.push(`to_date=${to}`);
    return p.length ? `&${p.join("&")}` : "";
  };
  const dlQs = () => {
    const p = [];
    if (from) p.push(`from_date=${from}`);
    if (to) p.push(`to_date=${to}`);
    return p.length ? `?${p.join("&")}` : "";
  };

  const fetchReport = async (k) => {
    setLoading(true);
    setReport(null);
    try {
      const { data } = await api.get(`/reports/${k}?format=json${rangeQs()}`);
      setReport(data);
    } catch {
      toast.error("Could not load report");
    }
    setLoading(false);
  };

  useEffect(() => { if (open) fetchReport(kind); /* eslint-disable-next-line */ }, [open, kind, from, to]);

  const printReport = () => {
    if (!report) return;
    const esc = (v) => String(v ?? "—").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const secHtml = report.sections.map((sec) => {
      if (sec.type === "kv") {
        const rows = sec.pairs.map(([k, v]) => `<tr><th style="text-align:left;padding:6px 12px 6px 0;color:#475569;white-space:nowrap;vertical-align:top">${esc(k)}</th><td style="padding:6px 0">${esc(v)}</td></tr>`).join("");
        return `<h3>${esc(sec.heading)}</h3><table class="kv">${rows}</table>`;
      }
      const head = `<tr>${sec.columns.map((c) => `<th>${esc(c)}</th>`).join("")}<th>Status</th></tr>`;
      const body = sec.rows.length
        ? sec.rows.map((r) => `<tr>${r.cells.map((c) => `<td>${esc(c)}</td>`).join("")}<td>${esc((r.status || "unknown").replace("_", " "))}</td></tr>`).join("")
        : `<tr><td colspan="${sec.columns.length + 1}" style="color:#94a3b8">No records.</td></tr>`;
      return `<h3>${esc(sec.heading)}</h3><table class="data"><thead>${head}</thead><tbody>${body}</tbody></table>`;
    }).join("");
    const html = `<!doctype html><html><head><title>${esc(report.title)}</title><style>
      *{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;box-sizing:border-box}
      body{margin:32px;color:#0f172a}
      .hd{border-bottom:2px solid #0f172a;padding-bottom:12px;margin-bottom:20px}
      .hd h1{margin:0;font-size:22px}.hd p{margin:4px 0 0;color:#64748b;font-size:13px}
      .badge{display:inline-block;margin-top:6px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;background:#0f172a;color:#fff;padding:3px 8px;border-radius:99px}
      h3{margin:22px 0 8px;font-size:15px}
      table{width:100%;border-collapse:collapse;font-size:12px}
      table.data th,table.data td{border:1px solid #e2e8f0;padding:6px 8px;text-align:left}
      table.data thead th{background:#f1f5f9}
      @media print{body{margin:12mm}}
    </style></head><body>
      <div class="hd"><h1>${esc(report.title)}</h1><p>${esc(report.subtitle)}${report.operator ? " · " + esc(report.operator) : ""}</p><span class="badge">${esc(report.authority)}</span></div>
      ${secHtml}
      <script>window.onload=function(){window.print();}</script>
    </body></html>`;
    const w = window.open("", "_blank");
    if (!w) { toast.error("Allow pop-ups to print"); return; }
    w.document.write(html);
    w.document.close();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-heading flex items-center gap-2"><Layers size={18} /> Fleet Audit Report</DialogTitle>
          <DialogDescription>A detailed, on-screen list of your whole operation — vehicles, trailers, drivers, PMI inspections, defects, service, tacho and daily checks. Print it, download the PDF, or bundle all evidence for a DVSA/RSA visit.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-slate-100">
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger data-testid="audit-report-select" className="w-56"><SelectValue /></SelectTrigger>
            <SelectContent>{REPORT_KINDS.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}</SelectContent>
          </Select>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span>From</span>
            <input data-testid="audit-from-date" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className="border border-slate-300 rounded-md px-2 py-1.5 text-sm text-slate-700" />
            <span>to</span>
            <input data-testid="audit-to-date" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="border border-slate-300 rounded-md px-2 py-1.5 text-sm text-slate-700" />
            {(from || to) && <button data-testid="audit-clear-range" onClick={() => { setFrom(""); setTo(""); }} className="text-slate-400 hover:text-slate-900 underline">clear</button>}
          </div>
          <div className="flex-1" />
          <Button data-testid="audit-print-button" variant="outline" className="border-slate-300 rounded-md gap-2" onClick={printReport} disabled={!report}><Printer size={16} /> Print</Button>
          <Button data-testid="audit-download-button" variant="outline" className="border-slate-300 rounded-md gap-2" onClick={() => downloadPdf(`/reports/${kind}${dlQs()}`, `${kind}-report.pdf`)}><FileDown size={16} /> PDF</Button>
          {kind === "audit" && report?.has_files && (
            <Button data-testid="audit-download-evidence-button" className="bg-black hover:bg-slate-800 rounded-md gap-2" onClick={() => downloadPdf(`/reports/${kind}${dlQs()}${dlQs() ? "&" : "?"}include_files=true`, `${kind}-pack.pdf`)}><FileDown size={16} /> PDF + evidence</Button>
          )}
        </div>

        <div className="overflow-y-auto pr-1 -mr-1" data-testid="audit-report-body">
          {loading && <div className="flex items-center gap-2 text-slate-400 py-16 justify-center"><Loader2 size={18} className="animate-spin" /> Loading report…</div>}
          {!loading && report && (
            <div className="py-4">
              <div className="border-b-2 border-slate-900 pb-3 mb-5">
                <h2 className="font-heading font-black text-2xl text-slate-900">{report.title}</h2>
                <p className="text-sm text-slate-500 mt-1">{report.subtitle}{report.operator && ` · ${report.operator}`}</p>
                <span className="inline-block mt-2 text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full bg-slate-900 text-white">{report.authority}</span>
              </div>
              {report.sections.map((sec, si) => (
                <div key={si} className="mb-6">
                  <h3 className="font-heading font-bold text-base text-slate-900 mb-2">{sec.heading}</h3>
                  {sec.type === "kv" ? (
                    <table className="w-full text-sm"><tbody>
                      {sec.pairs.map(([k, v], i) => (
                        <tr key={i} className="border-b border-slate-50 last:border-0">
                          <th className="text-left py-1.5 pr-4 text-slate-500 font-medium align-top whitespace-nowrap w-48">{k}</th>
                          <td className="py-1.5 text-slate-800">{String(v ?? "—")}</td>
                        </tr>
                      ))}
                    </tbody></table>
                  ) : sec.rows.length === 0 ? (
                    <p className="text-sm text-slate-400">No records.</p>
                  ) : (
                    <div className="overflow-x-auto border border-slate-200 rounded-md">
                      <table className="w-full text-sm">
                        <thead className="bg-slate-50"><tr>
                          {sec.columns.map((c, i) => <th key={i} className="text-left px-3 py-2 font-semibold text-slate-600 whitespace-nowrap">{c}</th>)}
                          <th className="text-left px-3 py-2 font-semibold text-slate-600">Status</th>
                        </tr></thead>
                        <tbody>
                          {sec.rows.map((r, ri) => (
                            <tr key={ri} className="border-t border-slate-100">
                              {r.cells.map((c, ci) => <td key={ci} className="px-3 py-2 text-slate-700 align-top">{String(c ?? "—")}</td>)}
                              <td className="px-3 py-2"><StatusPill status={r.status} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
