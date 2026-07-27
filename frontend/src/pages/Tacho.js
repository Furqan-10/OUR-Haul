import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Trash2, Pencil, Gauge, Download, AlertTriangle, CreditCard, Cpu, Loader2, Sparkles, ScanSearch, FileDown, FileSignature, ShieldAlert, Users } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { downloadPdf } from "@/lib/download";

const FREQ = { "Driver Card": 28, "Vehicle Unit": 90 };
const today = () => new Date().toISOString().slice(0, 10);
const empty = { source_type: "Driver Card", reference: "", frequency_days: 28, last_download: "", infringements: 0, notes: "", attachments: [] };
const sevPill = { very_serious: "bg-red-100 text-red-700", serious: "bg-orange-100 text-orange-700", minor: "bg-yellow-100 text-yellow-800" };

export default function Tacho() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [reading, setReading] = useState(false);
  const [analyses, setAnalyses] = useState([]);
  const [driverSummary, setDriverSummary] = useState(null);
  const [driverDetail, setDriverDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [anOpen, setAnOpen] = useState(false);

  const openDriver = async (nameKey) => {
    setDetailOpen(true);
    setDriverDetail(null);
    try {
      const res = await api.get("/tacho/driver-detail", { params: { name: nameKey } });
      setDriverDetail(res.data);
    } catch { toast.error("Could not load driver detail"); }
  };
  const [anForm, setAnForm] = useState({ driver_name: "", attachments: [] });
  const [analysing, setAnalysing] = useState(false);

  const load = async () => {
    setItems((await api.get("/tacho")).data);
    setDrivers((await api.get("/drivers")).data);
    setVehicles((await api.get("/vehicles")).data);
    setAnalyses((await api.get("/tacho/analyses")).data);
    setDriverSummary((await api.get("/tacho/driver-summary")).data);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openAnalyse = () => { setAnForm({ driver_name: "", attachments: [] }); setAnOpen(true); };
  const runAnalyse = async () => {
    const att = anForm.attachments[anForm.attachments.length - 1];
    if (!att) { toast.error("Upload a tacho printout first"); return; }
    setAnalysing(true);
    try {
      await api.post("/tacho/analyse", { file_id: att.file_id, driver_name: anForm.driver_name });
      toast.success("Analysis complete");
      setAnOpen(false);
      setAnalyses((await api.get("/tacho/analyses")).data);
      setDriverSummary((await api.get("/tacho/driver-summary")).data);
    } catch { toast.error("Could not analyse the file"); }
    finally { setAnalysing(false); }
  };
  const deleteAnalysis = async (id) => { await api.delete(`/tacho/analyses/${id}`); toast.success("Analysis removed"); setAnalyses((await api.get("/tacho/analyses")).data); setDriverSummary((await api.get("/tacho/driver-summary")).data); };
  const createInfringementLetter = (a) => {
    const lines = (a.infringements || []).map((i) => `• ${i.type || "Infringement"}${i.datetime ? ` (${i.datetime})` : ""} — ${i.rule || ""}${i.detail ? `: ${i.detail}` : ""}`).join("\n");
    const points = `Tachograph analysis for ${a.driver_name || "the driver"}${a.period ? ` covering ${a.period}` : ""}.\n${a.total_infringements || 0} infringement(s) identified:\n${lines}\n\nSummary: ${a.summary || ""}`;
    sessionStorage.setItem("tacho_infringement_draft", JSON.stringify({ recipient_name: a.driver_name || "", points }));
    navigate("/office?tab=documents");
  };

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (t) => { setForm({ ...empty, ...t, last_download: t.last_download || "", attachments: t.attachments || [] }); setEditId(t.id); setOpen(true); };

  const setType = (v) => setForm({ ...form, source_type: v, frequency_days: FREQ[v] || form.frequency_days, reference: "" });

  const refOptions = form.source_type === "Vehicle Unit"
    ? vehicles.map((v) => v.registration).filter(Boolean)
    : drivers.map((d) => d.name).filter(Boolean);

  const save = async (e) => {
    e.preventDefault();
    if (!form.reference) { toast.error(form.source_type === "Vehicle Unit" ? "Select a vehicle" : "Select a driver"); return; }
    const payload = { ...form, frequency_days: Number(form.frequency_days), infringements: Number(form.infringements) || 0, last_download: form.last_download || null };
    try {
      if (editId) await api.put(`/tacho/${editId}`, payload);
      else await api.post("/tacho", payload);
      toast.success(editId ? "Record updated" : "Tacho record added");
      setOpen(false); load();
    } catch { toast.error("Could not save record"); }
  };
  const remove = async (id) => { await api.delete(`/tacho/${id}`); toast.success("Record removed"); load(); };
  const logDownload = async (t) => {
    try {
      await api.post(`/tacho/${t.id}/download`, { download_date: today() });
      toast.success("Download logged · next due rescheduled");
      load();
    } catch { toast.error("Could not log download"); }
  };

  const autoRead = async () => {
    const att = form.attachments[form.attachments.length - 1];
    if (!att) { toast.error("Upload a tacho file first"); return; }
    setReading(true);
    try {
      const res = await api.post("/tacho/parse", { file_id: att.file_id });
      const upd = {};
      if (res.data.last_download) upd.last_download = res.data.last_download;
      if (res.data.infringements != null) upd.infringements = res.data.infringements;
      setForm((f) => ({ ...f, ...upd }));
      toast.success(res.data.last_download ? `Read last download: ${res.data.last_download}` : "No date found in file — please enter manually");
    } catch {
      toast.error("Could not read the file");
    } finally {
      setReading(false);
    }
  };

  const grouped = (sourceType) => {
    const list = items.filter((i) => i.source_type === sourceType);
    const map = {};
    list.forEach((i) => { (map[i.reference || "—"] = map[i.reference || "—"] || []).push(i); });
    return Object.entries(map).map(([ref, recs]) => {
      recs.sort((a, b) => (b.last_download || b.next_due || "").localeCompare(a.last_download || a.next_due || ""));
      return { ref, latest: recs[0], history: recs.slice(1) };
    });
  };

  const renderGroups = (sourceType, emptyText) => {
    const groups = grouped(sourceType);
    const Icon = sourceType === "Vehicle Unit" ? Cpu : CreditCard;
    if (groups.length === 0) return <Empty icon={Gauge} text={emptyText} />;
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {groups.map(({ ref, latest: t, history }) => (
          <div key={sourceType + ref} data-testid="tacho-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold flex items-center gap-1"><Icon size={12} /> {t.source_type}</p>
                <h3 className="font-heading font-bold text-lg text-slate-900 truncate">{ref}</h3>
                <p className="text-xs text-slate-500 mt-0.5">Every {t.frequency_days} days · last {t.last_download || "—"}</p>
              </div>
              <div className="flex gap-1 shrink-0">
                <button data-testid="edit-tacho-button" onClick={() => openEdit(t)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                <button data-testid="delete-tacho-button" onClick={() => remove(t.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <div>
                <p className="text-xs text-slate-400">Next download due</p>
                <p className="text-sm font-semibold text-slate-700">{t.next_due || "—"}{t.days_left != null && <span className="text-slate-400 font-normal"> · {t.days_left < 0 ? `${Math.abs(t.days_left)}d overdue` : `${t.days_left}d`}</span>}</p>
              </div>
              <StatusBadge status={t.status} />
            </div>
            {t.infringements > 0 && (
              <div className="mt-3 flex items-center gap-1.5 text-xs font-semibold text-red-700 bg-red-50 rounded-md px-2.5 py-1.5">
                <AlertTriangle size={13} /> {t.infringements} infringement{t.infringements > 1 ? "s" : ""} logged
              </div>
            )}
            <AttachmentThumbs attachments={t.attachments} />
            {history.length > 0 && (
              <details className="mt-3">
                <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-700">{history.length} earlier download{history.length > 1 ? "s" : ""}</summary>
                <div className="mt-2 space-y-1">
                  {history.map((h) => (
                    <div key={h.id} className="flex items-center justify-between text-xs text-slate-500 border-t border-slate-100 pt-1">
                      <span>{h.last_download || "—"}</span>
                      <button onClick={() => remove(h.id)} className="text-slate-300 hover:text-red-600"><Trash2 size={12} /></button>
                    </div>
                  ))}
                </div>
              </details>
            )}
            <Button data-testid="log-download-button" onClick={() => logDownload(t)} variant="outline" className="w-full mt-4 gap-2 border-slate-300">
              <Download size={15} /> Log Download Today
            </Button>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div data-testid="tacho-page">
      <Header title="Tacho Portal" subtitle="Driver card (28d) & vehicle unit (90d) download tracking" onAdd={openNew} addTestId="add-tacho-button" addLabel="Add Record" />

      <Tabs defaultValue="Driver Card">
        <TabsList className="mb-6">
          <TabsTrigger value="Driver Card" data-testid="tacho-tab-drivers"><CreditCard size={15} className="mr-1.5" /> Driver Cards</TabsTrigger>
          <TabsTrigger value="Vehicle Unit" data-testid="tacho-tab-vehicles"><Cpu size={15} className="mr-1.5" /> Vehicle Units</TabsTrigger>
          <TabsTrigger value="Analyser" data-testid="tacho-tab-analyser"><ScanSearch size={15} className="mr-1.5" /> Infringement Analyser</TabsTrigger>
          <TabsTrigger value="ByDriver" data-testid="tacho-tab-bydriver"><Users size={15} className="mr-1.5" /> By Driver</TabsTrigger>
        </TabsList>
        <TabsContent value="Driver Card">{renderGroups("Driver Card", "No driver card downloads yet. Add a record to start tracking.")}</TabsContent>
        <TabsContent value="Vehicle Unit">{renderGroups("Vehicle Unit", "No vehicle unit downloads yet. Add a record to start tracking.")}</TabsContent>
        <TabsContent value="Analyser">
          <div className="flex items-center justify-between gap-3 mb-4">
            <p className="text-sm text-slate-500 max-w-2xl">Upload a driver-card / vehicle-unit printout or a tacho analysis report (image or PDF) and let AI flag suspected drivers' hours infringements. Best results with clear printouts or analysis PDFs.</p>
            <Button data-testid="analyse-tacho-button" onClick={openAnalyse} className="bg-black hover:bg-slate-800 rounded-md gap-2 shrink-0"><ScanSearch size={16} /> Analyse printout</Button>
          </div>
          {analyses.length === 0 ? (
            <Empty icon={ScanSearch} text="No analyses yet. Upload a tacho printout to run an AI infringement check." />
          ) : (
            <div className="space-y-4" data-testid="tacho-analyses">
              {analyses.map((a) => (
                <div key={a.id} data-testid="tacho-analysis-card" className="bg-white border border-slate-200 rounded-md p-5 animate-in-up">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <ShieldAlert size={16} className={a.total_infringements > 0 ? "text-red-600" : "text-green-600"} />
                        <h3 className="font-heading font-bold text-lg text-slate-900">{a.driver_name || "Tacho analysis"}</h3>
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${a.total_infringements > 0 ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>{a.total_infringements} infringement{a.total_infringements !== 1 ? "s" : ""}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">{a.period || ""}{a.period && " · "}Analysed {new Date(a.created_at).toLocaleDateString()} · AI confidence {Math.round((a.confidence || 0) * 100)}%</p>
                      {a.summary && <p className="text-sm text-slate-600 mt-2">{a.summary}</p>}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button data-testid="analysis-pdf-button" onClick={() => downloadPdf(`/tacho/analyses/${a.id}/report`, `tacho-analysis-${(a.driver_name || "driver").replace(/ /g, "_")}.pdf`)} title="Download PDF" className="text-slate-400 hover:text-slate-900 p-1.5"><FileDown size={16} /></button>
                      <button data-testid="delete-analysis-button" onClick={() => deleteAnalysis(a.id)} title="Delete" className="text-slate-400 hover:text-red-600 p-1.5"><Trash2 size={16} /></button>
                    </div>
                  </div>
                  {(a.infringements || []).length > 0 && (
                    <div className="mt-4 space-y-2">
                      {a.infringements.map((i, idx) => (
                        <div key={idx} data-testid="analysis-infringement" className="border border-slate-100 rounded-md p-3">
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <span className="text-sm font-semibold text-slate-900">{i.type || "Infringement"}</span>
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${sevPill[i.severity] || sevPill.minor}`}>{(i.severity || "minor").replace("_", " ")}</span>
                          </div>
                          {i.datetime && <p className="text-xs text-slate-400 mt-0.5">{i.datetime}</p>}
                          {i.rule && <p className="text-xs text-slate-500 mt-1"><span className="font-semibold">Rule:</span> {i.rule}</p>}
                          {i.detail && <p className="text-xs text-slate-600 mt-1">{i.detail}</p>}
                          {i.action && <p className="text-xs text-slate-600 mt-1"><span className="font-semibold">Action:</span> {i.action}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                  <Button data-testid="create-infringement-letter-button" onClick={() => createInfringementLetter(a)} variant="outline" className="mt-4 gap-2 border-slate-300"><FileSignature size={15} /> Create Driver Infringement letter</Button>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="ByDriver">
          {!driverSummary || driverSummary.drivers.length === 0 ? (
            <Empty icon={Users} text="No driver infringement data yet. Run some tacho analyses to build the per-driver view." />
          ) : (
            <div data-testid="tacho-by-driver">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                {[["Drivers", driverSummary.totals.drivers, "text-slate-900"], ["Total infringements", driverSummary.totals.infringements, "text-slate-900"], ["Very serious", driverSummary.totals.very_serious, "text-red-600"], ["Serious", driverSummary.totals.serious, "text-orange-600"]].map(([l, v, c]) => (
                  <div key={l} className="bg-white border border-slate-200 rounded-md p-4">
                    <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">{l}</p>
                    <p className={`text-3xl font-heading font-black mt-1 ${c}`}>{v}</p>
                  </div>
                ))}
              </div>
              <div className="bg-white border border-slate-200 rounded-md overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
                  <ShieldAlert size={16} className="text-slate-700" />
                  <h3 className="font-heading font-bold text-base">Repeat offenders — ranked by total infringements</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="by-driver-table">
                    <thead className="bg-slate-50">
                      <tr className="text-left text-slate-500">
                        <th className="px-5 py-2.5 font-semibold">#</th>
                        <th className="px-3 py-2.5 font-semibold">Driver</th>
                        <th className="px-3 py-2.5 font-semibold text-center">Total</th>
                        <th className="px-3 py-2.5 font-semibold text-center">V. serious</th>
                        <th className="px-3 py-2.5 font-semibold text-center">Serious</th>
                        <th className="px-3 py-2.5 font-semibold text-center">Minor</th>
                        <th className="px-3 py-2.5 font-semibold text-center">Analyses</th>
                        <th className="px-3 py-2.5 font-semibold">Last analysed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {driverSummary.drivers.map((d, idx) => (
                        <tr key={d.driver_name} data-testid="by-driver-row" onClick={() => openDriver(d.driver_name)} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer">
                          <td className="px-5 py-3 text-slate-400 font-semibold">{idx + 1}</td>
                          <td className="px-3 py-3 font-semibold text-slate-900">
                            {d.driver_name}
                            {idx === 0 && d.total_infringements > 0 && <span className="ml-2 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-red-100 text-red-700">Top offender</span>}
                          </td>
                          <td className="px-3 py-3 text-center"><span className={`inline-flex items-center justify-center min-w-[28px] font-bold rounded-full px-2 py-0.5 ${d.total_infringements > 0 ? "bg-slate-900 text-white" : "bg-green-100 text-green-700"}`}>{d.total_infringements}</span></td>
                          <td className="px-3 py-3 text-center">{d.very_serious ? <span className="font-semibold text-red-600">{d.very_serious}</span> : <span className="text-slate-300">—</span>}</td>
                          <td className="px-3 py-3 text-center">{d.serious ? <span className="font-semibold text-orange-600">{d.serious}</span> : <span className="text-slate-300">—</span>}</td>
                          <td className="px-3 py-3 text-center">{d.minor ? <span className="text-yellow-700">{d.minor}</span> : <span className="text-slate-300">—</span>}</td>
                          <td className="px-3 py-3 text-center text-slate-500">{d.analyses}</td>
                          <td className="px-3 py-3 text-slate-500">{d.last_analysed ? new Date(d.last_analysed).toLocaleDateString() : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="driver-detail-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2"><ShieldAlert size={18} /> {driverDetail?.driver_name || "Driver"} — Infringement History</DialogTitle>
            <DialogDescription>Every infringement recorded for this driver across all tacho analyses.</DialogDescription>
          </DialogHeader>
          {!driverDetail ? (
            <div className="py-10 text-center text-slate-400 text-sm">Loading…</div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-full bg-slate-900 text-white font-semibold">{driverDetail.total} total</span>
                <span className="px-2.5 py-1 rounded-full bg-red-100 text-red-700 font-semibold">{driverDetail.counts.very_serious} very serious</span>
                <span className="px-2.5 py-1 rounded-full bg-orange-100 text-orange-700 font-semibold">{driverDetail.counts.serious} serious</span>
                <span className="px-2.5 py-1 rounded-full bg-yellow-100 text-yellow-800 font-semibold">{driverDetail.counts.minor} minor</span>
                <span className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 font-semibold">{driverDetail.analyses.length} analyses</span>
              </div>
              <Button data-testid="generate-letter-button" onClick={() => downloadPdf(`/tacho/driver-letter?name=${encodeURIComponent(driverDetail.driver_name)}`, `infringement-letter-${(driverDetail.driver_name || "driver").replace(/ /g, "_")}.pdf`)} disabled={!driverDetail.total} className="bg-black hover:bg-slate-800 gap-2 w-full">
                <FileSignature size={16} /> Generate Infringement Letter (PDF)
              </Button>
              <div className="border border-slate-200 rounded-md divide-y divide-slate-100 max-h-[45vh] overflow-y-auto">
                {driverDetail.infringements.length === 0 ? (
                  <p className="p-6 text-center text-sm text-slate-400">No infringements — this driver is clean. 👍</p>
                ) : driverDetail.infringements.map((i, k) => (
                  <div key={k} data-testid="driver-infr-row" className="p-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{i.type}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{i.datetime}</p>
                      </div>
                      <span className={`shrink-0 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${i.severity === "very_serious" ? "bg-red-100 text-red-700" : i.severity === "serious" ? "bg-orange-100 text-orange-700" : "bg-yellow-100 text-yellow-800"}`}>{(i.severity || "").replace(/_/g, " ")}</span>
                    </div>
                    {i.detail && <p className="text-xs text-slate-600 mt-1.5">{i.detail}</p>}
                    {i.rule && <p className="text-[11px] text-slate-400 mt-1">{i.rule}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Tacho Record" : "Add Tacho Record"}</DialogTitle><DialogDescription className="sr-only">Tachograph download record form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Source Type">
                <Select value={form.source_type} onValueChange={setType}>
                  <SelectTrigger data-testid="tacho-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Driver Card">Driver Card</SelectItem>
                    <SelectItem value="Vehicle Unit">Vehicle Unit</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Frequency (days)"><Input data-testid="tacho-frequency" type="number" min="1" value={form.frequency_days} onChange={(e) => setForm({ ...form, frequency_days: e.target.value })} /></Field>
            </div>
            <Field label={form.source_type === "Vehicle Unit" ? "Vehicle Registration *" : "Driver *"}>
              <Select value={form.reference || undefined} onValueChange={(v) => setForm({ ...form, reference: v })}>
                <SelectTrigger data-testid="tacho-reference"><SelectValue placeholder={form.source_type === "Vehicle Unit" ? "Select vehicle" : "Select driver"} /></SelectTrigger>
                <SelectContent>
                  {[...new Set([...(form.reference ? [form.reference] : []), ...refOptions])].map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                  {refOptions.length === 0 && !form.reference && (
                    <div className="px-3 py-2 text-xs text-slate-400">{form.source_type === "Vehicle Unit" ? "No vehicles — add one in Fleet first" : "No drivers — add one in Drivers first"}</div>
                  )}
                </SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Last Download"><Input data-testid="tacho-last" type="date" value={form.last_download} onChange={(e) => setForm({ ...form, last_download: e.target.value })} /></Field>
              <Field label="Infringements"><Input data-testid="tacho-infringements" type="number" min="0" value={form.infringements} onChange={(e) => setForm({ ...form, infringements: e.target.value })} /></Field>
            </div>
            <Field label="Upload Tacho Data (download files)"><FileUpload testid="tacho-upload" label="Upload tacho files (.ddd / .tgd / .c1b / .v1b / image / PDF)" accept="image/*,application/pdf,.ddd,.tgd,.c1b,.v1b,.dtc,.esm,.tgz" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            {form.attachments.length > 0 && (
              <Button type="button" data-testid="tacho-autoread-button" onClick={autoRead} disabled={reading} variant="outline" className="w-full gap-2 border-slate-300">
                {reading ? <><Loader2 size={15} className="animate-spin" /> Reading file…</> : <><Sparkles size={15} /> Auto-read dates from file</>}
              </Button>
            )}
            <Field label="Notes"><Textarea data-testid="tacho-notes" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Infringement details, analysis notes…" /></Field>
            <DialogFooter><Button data-testid="save-tacho-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Record"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={anOpen} onOpenChange={setAnOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading flex items-center gap-2"><ScanSearch size={18} /> Analyse Tacho Data</DialogTitle><DialogDescription>Upload a digital tachograph download (.ddd) — decoded directly for drivers' hours infringements — or a driver-card / vehicle-unit printout (image / PDF) for AI analysis.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <Field label="Driver (optional)">
              <Select value={anForm.driver_name || undefined} onValueChange={(v) => setAnForm({ ...anForm, driver_name: v })}>
                <SelectTrigger data-testid="analyse-driver-select"><SelectValue placeholder="Attach to a driver" /></SelectTrigger>
                <SelectContent>{drivers.map((d) => <SelectItem key={d.id} value={d.name}>{d.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Tacho file / printout *"><FileUpload testid="analyse-upload" label="Upload a .ddd download, or a printout / report (image or PDF)" accept="image/*,application/pdf,.ddd,.tgd,.c1b,.v1b,.dtc,.esm,.dtg" attachments={anForm.attachments} onChange={(a) => setAnForm({ ...anForm, attachments: a })} /></Field>
            <DialogFooter>
              <Button data-testid="run-analyse-button" onClick={runAnalyse} disabled={analysing || anForm.attachments.length === 0} className="bg-black hover:bg-slate-800 gap-2">
                {analysing ? <><Loader2 size={16} className="animate-spin" /> Analysing…</> : <><Sparkles size={16} /> Run AI Analysis</>}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
