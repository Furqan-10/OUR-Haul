import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, ClipboardCheck, Wrench, CheckCircle2, Check, X } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { RegFolders, matchesReg } from "@/components/RegFolders";
import { ReportDownload } from "@/components/ReportDownload";

export const CHECKLIST = [
  { section: "Internal Checks", items: ["Mirrors and glass", "Windscreen wipers and washers", "Front view", "Warning lamps", "Steering", "Horn", "Brakes and air build-up", "Height marker", "Seatbelts"] },
  { section: "External Checks", items: ["Lights and indicators", "Fuel/oil leaks", "Battery security and condition", "Diesel exhaust fluid (AdBlue)", "Excessive engine exhaust smoke", "Security of body/wings", "Spray suppression", "Tyres and wheel fixing", "Brake line", "Electrical connections", "Coupling security", "Security of load", "Number plate", "Reflectors and lights", "Markers"] },
];
export const buildChecklist = () => CHECKLIST.flatMap((s) => s.items.map((item) => ({ section: s.section, item, ok: true, note: "" })));

const today = () => new Date().toISOString().slice(0, 10);
const empty = { vehicle_reg: "", driver_name: "", check_date: today(), result: "nil_defect", mileage: "", defects_noted: "", checklist: buildChecklist(), attachments: [] };

export function WalkaroundPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [regFilter, setRegFilter] = useState("");
  const [assets, setAssets] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [rectFor, setRectFor] = useState(null);
  const [rectForm, setRectForm] = useState({ rectified_date: today(), rectified_notes: "" });

  const load = async () => {
    const [w, v, t, dr] = await Promise.all([api.get("/walkarounds"), api.get("/vehicles"), api.get("/trailers"), api.get("/drivers")]);
    setItems(w.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
    setDrivers(dr.data.map((x) => x.name));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => { setForm({ ...empty, checklist: buildChecklist() }); setOpen(true); };
  const setItem = (idx, patch) => setForm((f) => ({ ...f, checklist: f.checklist.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }));

  const save = async () => {
    if (!form.vehicle_reg) return toast.error("Select a vehicle");
    const failed = (form.checklist || []).filter((c) => !c.ok);
    const compiled = failed.map((c) => `${c.item}${c.note ? `: ${c.note}` : ""}`).join("; ");
    const defects_noted = [compiled, form.defects_noted].filter(Boolean).join(" — ");
    const result = failed.length ? "defects_found" : "nil_defect";
    try {
      await api.post("/walkarounds", { ...form, result, defects_noted, check_date: form.check_date || null });
      toast.success(failed.length ? `Check logged — ${failed.length} defect(s) found` : "Nil-defect check logged");
      setOpen(false); setForm(empty); load();
    } catch { toast.error("Could not save check"); }
  };
  const remove = async (id) => { await api.delete(`/walkarounds/${id}`); load(); };
  const openRectify = (a) => { setRectFor(a); setRectForm({ rectified_date: today(), rectified_notes: "" }); };
  const saveRectify = async () => {
    try {
      await api.put(`/walkarounds/${rectFor.id}/rectify`, rectForm);
      toast.success("Defect marked as rectified"); setRectFor(null); load();
    } catch { toast.error("Could not update"); }
  };

  return (
    <div data-testid="walkaround-page">
      <div className="flex justify-end gap-2 mb-4">
        <ReportDownload path="/reports/walkaround" filename="daily-checks-report.pdf" testid="download-walkaround-pdf" evidence />
        <Button data-testid="add-walkaround-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Log Daily Check</Button>
      </div>
      {items.length === 0 ? <Empty icon={ClipboardCheck} text="No daily walkaround checks yet. Log driver first-use nil-defect / defect checks here." /> : (
        <div>
          <RegFolders items={items} value={regFilter} onChange={setRegFilter} />
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.filter((a) => matchesReg(regFilter, a.vehicle_reg)).map((a) => (
            <div key={a.id} className="bg-white border border-slate-200 rounded-md p-5" data-testid="walkaround-card">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-heading font-bold text-lg tracking-tight">{a.vehicle_reg}</h3>
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${a.result === "nil_defect" ? "text-green-700 bg-green-50" : "text-amber-700 bg-amber-50"}`}>{a.result === "nil_defect" ? "Nil defect" : "Defects found"}</span>
                    {a.result === "defects_found" && a.rectified && <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full text-green-700 bg-green-50 flex items-center gap-1"><CheckCircle2 size={11} /> Rectified</span>}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{a.check_date || "—"}{a.driver_name ? ` · ${a.driver_name}` : ""}{a.mileage ? ` · ${a.mileage} mi` : ""}</p>
                </div>
                <button data-testid="delete-walkaround-button" onClick={() => remove(a.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
              </div>
              {a.defects_noted && <p className="text-sm text-slate-500 mt-1">{a.defects_noted}</p>}
              {a.checklist?.length > 0 && (
                <p data-testid="walkaround-check-count" className="text-xs text-slate-400 mt-1.5">
                  {a.checklist.filter((c) => c.ok).length}/{a.checklist.length} checks passed
                </p>
              )}
              {a.result === "defects_found" && a.rectified && (
                <div data-testid="walkaround-rectified-banner" className="mt-3 rounded-md bg-green-50 border border-green-100 px-3 py-2 text-xs text-green-800">
                  <span className="font-semibold">Rectified {a.rectified_date}</span>{a.rectified_notes ? ` — ${a.rectified_notes}` : ""}
                </div>
              )}
              {a.result === "defects_found" && !a.rectified && (
                <button data-testid="mark-walkaround-rectified-button" onClick={() => openRectify(a)} className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 border border-slate-200 rounded-md px-3 py-1.5"><Wrench size={13} /> Mark rectified</button>
              )}
              {a.attachments?.length > 0 && <div className="mt-3"><AttachmentThumbs attachments={a.attachments} /></div>}
            </div>
          ))}
          </div>
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>HGV Daily Walkaround Check</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="walk-reg"><SelectValue placeholder={assets.length ? "Select vehicle" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Driver">
              <Select value={form.driver_name} onValueChange={(v) => setForm({ ...form, driver_name: v })}>
                <SelectTrigger data-testid="walk-driver"><SelectValue placeholder={drivers.length ? "Select driver" : "Add a driver first"} /></SelectTrigger>
                <SelectContent>{drivers.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Date"><Input data-testid="walk-date" type="date" value={form.check_date || ""} onChange={(e) => setForm({ ...form, check_date: e.target.value })} /></Field>
            <Field label="Mileage"><Input data-testid="walk-mileage" value={form.mileage} onChange={(e) => setForm({ ...form, mileage: e.target.value })} /></Field>
          </div>

          <div className="mt-4" data-testid="walk-checklist">
            {(() => {
              const failCount = form.checklist.filter((c) => !c.ok).length;
              return (
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Walkaround Checklist ({form.checklist.length} points)</p>
                  <div className="flex items-center gap-2">
                    <button data-testid="walk-all-pass" onClick={() => setForm((f) => ({ ...f, checklist: f.checklist.map((c) => ({ ...c, ok: true, note: "" })) }))} className="text-[11px] font-semibold text-green-700 hover:underline">Mark all OK</button>
                    <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${failCount ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{failCount ? `${failCount} defect(s)` : "Nil defect"}</span>
                  </div>
                </div>
              );
            })()}
            {CHECKLIST.map((sec) => (
              <div key={sec.section} className="mb-3">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-700 bg-slate-50 px-3 py-1.5 rounded-md">{sec.section}</p>
                <div className="divide-y divide-slate-100">
                  {form.checklist.map((c, idx) => c.section !== sec.section ? null : (
                    <div key={idx} data-testid="walk-check-item" className="py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm text-slate-700">{c.item}</span>
                        <div className="flex items-center gap-1 shrink-0">
                          <button data-testid={`walk-item-ok-${idx}`} onClick={() => setItem(idx, { ok: true, note: "" })} className={`w-8 h-7 rounded-md flex items-center justify-center border ${c.ok ? "bg-green-600 border-green-600 text-white" : "border-slate-300 text-slate-400 hover:bg-slate-50"}`} title="Pass"><Check size={15} /></button>
                          <button data-testid={`walk-item-fail-${idx}`} onClick={() => setItem(idx, { ok: false })} className={`w-8 h-7 rounded-md flex items-center justify-center border ${!c.ok ? "bg-red-600 border-red-600 text-white" : "border-slate-300 text-slate-400 hover:bg-slate-50"}`} title="Defect"><X size={15} /></button>
                        </div>
                      </div>
                      {!c.ok && <Input data-testid={`walk-item-note-${idx}`} value={c.note} onChange={(e) => setItem(idx, { note: e.target.value })} placeholder="Describe the defect…" className="mt-1.5 h-8 text-sm" />}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <Field label="Additional notes / action taken"><Textarea data-testid="walk-notes" value={form.defects_noted} onChange={(e) => setForm({ ...form, defects_noted: e.target.value })} placeholder="Any extra notes (optional)…" /></Field>
          <div className="mt-4"><Field label="Attachments (signed sheet, photos)"><FileUpload attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field></div>
          <DialogFooter><Button data-testid="save-walkaround-button" onClick={save} className="bg-black hover:bg-slate-800">Log Check</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!rectFor} onOpenChange={(o) => !o && setRectFor(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Mark defect rectified — {rectFor?.vehicle_reg}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            {rectFor?.defects_noted && <p className="text-sm text-slate-500">Defect: {rectFor.defects_noted}</p>}
            <Field label="Date rectified"><Input data-testid="walk-rectify-date" type="date" value={rectForm.rectified_date} onChange={(e) => setRectForm({ ...rectForm, rectified_date: e.target.value })} /></Field>
            <Field label="Work carried out / notes"><Textarea data-testid="walk-rectify-notes" value={rectForm.rectified_notes} onChange={(e) => setRectForm({ ...rectForm, rectified_notes: e.target.value })} placeholder="How the defect was fixed…" /></Field>
            <DialogFooter><Button data-testid="save-walk-rectify-button" onClick={saveRectify} className="bg-black hover:bg-slate-800 gap-1.5"><Wrench size={15} /> Confirm rectified</Button></DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Walkaround() { return <WalkaroundPanel />; }
