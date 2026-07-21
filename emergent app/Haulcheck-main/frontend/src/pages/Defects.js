import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, FileWarning, Sparkles, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { RegFolders, matchesReg } from "@/components/RegFolders";
import { ReportDownload } from "@/components/ReportDownload";

const empty = { vehicle_reg: "", reported_by: "", category: "General", severity: "minor", description: "", odometer: "", defect_date: "", attachments: [] };
const SEVERITY = [["minor", "Minor"], ["major", "Major"], ["safety_critical", "Safety Critical"]];
const CATEGORY = ["General", "Brakes", "Tyres & Wheels", "Lights", "Steering", "Bodywork", "Load Security", "Other"];
const STATUS = [["open", "Open"], ["monitoring", "Monitoring"], ["rectified", "Rectified"]];

export function DefectsPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [regFilter, setRegFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [assets, setAssets] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [rectifyFor, setRectifyFor] = useState(null);
  const [rForm, setRForm] = useState({ rectified_date: new Date().toISOString().slice(0, 10), rectified_by: "", rectification_notes: "" });

  const openNew = () => { setForm({ ...empty, defect_date: new Date().toISOString().slice(0, 10) }); setOpen(true); };

  const load = async () => {
    const [d, v, t, dr] = await Promise.all([api.get("/defects"), api.get("/vehicles"), api.get("/trailers"), api.get("/drivers")]);
    setItems(d.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
    setDrivers(dr.data.map((x) => x.name));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/defects", form);
      toast.success("Defect logged & AI summary generated");
      setForm(empty); setOpen(false); load();
    } catch { toast.error("Could not log defect"); }
    finally { setBusy(false); }
  };
  const setStatus = async (id, status) => {
    if (status === "rectified") { openRectify(id); return; }
    await api.put(`/defects/${id}/status?status=${status}`); load();
  };
  const openRectify = (id) => { setRectifyFor(id); setRForm({ rectified_date: new Date().toISOString().slice(0, 10), rectified_by: "", rectification_notes: "" }); };
  const saveRectify = async () => {
    try {
      await api.put(`/defects/${rectifyFor}/rectify`, rForm);
      toast.success("Defect marked rectified");
      setRectifyFor(null); load();
    } catch { toast.error("Could not save rectification"); }
  };
  const remove = async (id) => { await api.delete(`/defects/${id}`); toast.success("Defect removed"); load(); };

  return (
    <div data-testid="defects-page">
      {!embedded && <Header title="Defect Reports" subtitle="Driver defect reporting with AI safety triage" onAdd={openNew} addTestId="add-defect-button" addLabel="Report Defect" />}
      <div className="flex justify-end gap-2 mb-4">
        <ReportDownload path="/reports/defects" filename="defects-report.pdf" testid="download-defects-pdf" evidence />
        {embedded && <Button data-testid="add-defect-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Report Defect</Button>}
      </div>

      {items.length === 0 ? <Empty icon={FileWarning} text="No defects reported. Drivers can log vehicle defects here." /> : (
        <div className="space-y-4">
          <RegFolders items={items} value={regFilter} onChange={setRegFilter} />
          {items.filter((d) => matchesReg(regFilter, d.vehicle_reg)).map((d) => (
            <div key={d.id} data-testid="defect-card" className="bg-white border border-slate-200 rounded-md p-5 animate-in-up">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-slate-900">{d.vehicle_reg}</span>
                    <StatusBadge status={d.severity} />
                    <StatusBadge status={d.status} />
                    <span className="text-xs text-slate-400">{d.category}</span>
                  </div>
                  <p className="text-slate-700 text-sm mt-2">{d.description}</p>
                  {d.ai_summary && (
                    <div className="mt-3 flex items-start gap-2 bg-slate-50 border border-slate-200 rounded-md p-3">
                      <Sparkles size={15} className="text-slate-900 mt-0.5 shrink-0" />
                      <p data-testid="defect-ai-summary" className="text-sm text-slate-600">{d.ai_summary}</p>
                    </div>
                  )}
                  <AttachmentThumbs attachments={d.attachments} />
                  {d.status === "rectified" && (
                    <div className="mt-3 flex items-start gap-2 bg-green-50 border border-green-200 rounded-md p-3" data-testid="defect-rectification">
                      <Wrench size={15} className="text-green-700 mt-0.5 shrink-0" />
                      <p className="text-sm text-green-800">
                        <span className="font-semibold">Rectified {d.rectified_date || ""}</span>{d.rectified_by ? ` by ${d.rectified_by}` : ""}
                        {d.rectification_notes ? ` — ${d.rectification_notes}` : ""}
                      </p>
                    </div>
                  )}
                  <p className="text-xs text-slate-400 mt-2">{d.reported_by && `Reported by ${d.reported_by} · `}{d.odometer && `${d.odometer} · `}{d.defect_date || new Date(d.created_at).toLocaleDateString()}</p>
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  <Select value={d.status} onValueChange={(v) => setStatus(d.id, v)}>
                    <SelectTrigger data-testid="defect-status-select" className="w-36 h-9 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                  </Select>
                  {d.status !== "rectified" && (
                    <Button data-testid="mark-rectified-button" onClick={() => openRectify(d.id)} variant="outline" className="h-9 text-xs rounded-md gap-1.5 border-green-300 text-green-700 hover:bg-green-50">
                      <Wrench size={14} /> Mark rectified
                    </Button>
                  )}
                  <button data-testid="delete-defect-button" onClick={() => remove(d.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={16} /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">Report a Defect</DialogTitle><DialogDescription className="sr-only">Defect report form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Vehicle *">
                <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                  <SelectTrigger data-testid="defect-reg"><SelectValue placeholder={assets.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
                  <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Reported By">
                <Select value={form.reported_by} onValueChange={(v) => setForm({ ...form, reported_by: v })}>
                  <SelectTrigger data-testid="defect-reporter"><SelectValue placeholder={drivers.length ? "Select driver" : "Add a driver first"} /></SelectTrigger>
                  <SelectContent>{drivers.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Category">
                <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                  <SelectTrigger data-testid="defect-category-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{CATEGORY.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Severity">
                <Select value={form.severity} onValueChange={(v) => setForm({ ...form, severity: v })}>
                  <SelectTrigger data-testid="defect-severity-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{SEVERITY.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Date reported"><Input data-testid="defect-date" type="date" value={form.defect_date} onChange={(e) => setForm({ ...form, defect_date: e.target.value })} /></Field>
              <Field label="Mileage / Odometer"><Input data-testid="defect-odometer" value={form.odometer} onChange={(e) => setForm({ ...form, odometer: e.target.value })} placeholder="e.g. 128,400 mi" /></Field>
            </div>
            <Field label="Description *"><Textarea data-testid="defect-description" required rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Describe the defect in detail…" /></Field>
            <Field label="Photos"><FileUpload testid="defect-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-defect-button" type="submit" disabled={busy} className="bg-black hover:bg-slate-800 gap-2"><Sparkles size={15} /> {busy ? "Analysing…" : "Log & Summarise"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!rectifyFor} onOpenChange={(o) => !o && setRectifyFor(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Mark defect as rectified</DialogTitle>
            <DialogDescription>Record how and when the defect was repaired (required for your maintenance records).</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Date rectified"><Input data-testid="rectify-date" type="date" value={rForm.rectified_date} onChange={(e) => setRForm({ ...rForm, rectified_date: e.target.value })} /></Field>
              <Field label="Rectified by"><Input data-testid="rectify-by" value={rForm.rectified_by} onChange={(e) => setRForm({ ...rForm, rectified_by: e.target.value })} placeholder="Fitter / garage" /></Field>
            </div>
            <Field label="Work carried out"><Textarea data-testid="rectify-notes" rows={3} value={rForm.rectification_notes} onChange={(e) => setRForm({ ...rForm, rectification_notes: e.target.value })} placeholder="Describe the repair / parts replaced…" /></Field>
          </div>
          <DialogFooter><Button data-testid="save-rectify-button" onClick={saveRectify} className="bg-green-700 hover:bg-green-800 gap-2"><Wrench size={15} /> Confirm rectified</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Defects() {
  return <DefectsPanel />;
}
