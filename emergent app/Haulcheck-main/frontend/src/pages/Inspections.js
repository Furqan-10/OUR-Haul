import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Trash2, Pencil, ClipboardCheck, CheckCircle2, Wrench, History, FileDown } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { RegFolders, matchesReg } from "@/components/RegFolders";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { SignaturePad } from "@/components/SignaturePad";
import { downloadPdf } from "@/lib/download";
import { ReportDownload } from "@/components/ReportDownload";

const emptySched = { vehicle_reg: "", frequency_weeks: 6, next_due: "", inspector: "", notes: "" };
const RESULTS = [["pass", "Pass"], ["advisory", "Advisory"], ["fail", "Fail"]];
const today = () => new Date().toISOString().slice(0, 10);

const resultBadge = { pass: "bg-green-100 text-green-700", advisory: "bg-yellow-100 text-yellow-800", fail: "bg-red-100 text-red-700" };

const PMI_CHECKLIST = [
  { section: "A: Inside cab", items: ["Registration/Licence/VIN", "Vehicle Weights & Dimensions Plate", "Warning Triangle", "Seats", "Seat belts", "Mirrors", "Windows, Glass & view of the road", "Windscreen wipers & washers", "Tachograph/Speedometer", "Horn", "Gauges, warning devices & malfunction indicators", "ABS warning", "Driving controls", "Steering control", "Service brake pedal", "Service Brake Operation (Inspection in Cab)", "Pressure/Air/Vacuum warnings", "Pressure/Air/Vacuum build-up", "Mechanical Brake Hand Levers", "Air/Vacuum Hand Control Valves", "Cab mounting, floor, doors & steps", "Doors/Locks/Anti Theft Devices"] },
  { section: "B: Ground level & under-vehicle", items: ["Condition & Security of body", "Exhaust Smoke emission", "Road wheels & hubs", "Tyre Specification", "Tyre Condition", "Tyre Tread", "Sideguards, Rear under-run Protection & bumpers", "Spare wheel & carrier", "Chassis/Underbody", "Towing Coupling/Fifth Wheel", "Trailer parking, emergency brake & air connections", "Trailer landing legs", "Spray suppression, wings & wheel arches", "Speed limiter & Plate", "Electrical wiring, equipment, batteries & trailer connections", "Engine & transmission mountings", "Fuel tanks & system", "Oil leaks", "Exhaust System/Noise", "Steering Mechanism", "Steering Alignment", "Suspension Units", "Suspension Linkage & Pins/Bushes", "Shock Absorbers", "Axles, stub axles & wheel bearings", "Transmission & Final Drive", "Brake Lines & Hoses", "Brake Wheel Units", "Brake Reservoirs/Valves/Master Cylinders/Connections", "Brake Fluid", "Mechanical Brake Components", "Brake Drums/Discs & Linings/Pads", "Front & Rear lamps & No. Plate lamps", "Stop lamps", "Fog lamps", "Marker Lamps", "Headlamps & Aim", "Reflectors and Rear & Side Markings", "Direction indicators & hazard warning lamps", "Additional braking devices", "Ancillary equipment", "Other Items"] },
  { section: "C: Brake performance", items: ["Service Brake performance", "Emergency/Secondary brake performance", "Parking brake performance"] },
];
const buildPmiChecklist = () => PMI_CHECKLIST.flatMap((s) => s.items.map((item) => ({ section: s.section, item, ok: true, note: "" })));
const emptyComplete = () => ({ inspection_date: today(), result: "pass", inspector: "", rectified_by: "", notes: "", brake_test_type: "none", laden: false, service_brake_pct: "", secondary_brake_pct: "", parking_brake_pct: "", checklist: buildPmiChecklist(), attachments: [], inspector_signature: "", rectifier_signature: "", odometer: "", make_model: "" });

export function InspectionsPanel({ embedded = false }) {
  const { user } = useAuth();
  const isIE = user?.region === "IE";
  const [items, setItems] = useState([]);
  const [records, setRecords] = useState([]);
  const [regFilter, setRegFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptySched);
  const [editId, setEditId] = useState(null);
  const [completeFor, setCompleteFor] = useState(null);
  const [cForm, setCForm] = useState(emptyComplete());
  const [assets, setAssets] = useState([]);
  const [interim, setInterim] = useState(false);
  const [interimReg, setInterimReg] = useState("");
  const [editRecordId, setEditRecordId] = useState(null);

  const load = async () => {
    const [p, r, v, t] = await Promise.all([api.get("/pmi"), api.get("/pmi/records"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(p.data); setRecords(r.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(emptySched); setEditId(null); setOpen(true); };
  const openEdit = (p) => { setForm({ ...emptySched, ...p, next_due: p.next_due || "" }); setEditId(p.id); setOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, frequency_weeks: Number(form.frequency_weeks), next_due: form.next_due || null };
    try {
      if (editId) await api.put(`/pmi/${editId}`, payload);
      else await api.post("/pmi", payload);
      toast.success(editId ? "Schedule updated" : "PMI schedule created");
      setOpen(false); load();
    } catch { toast.error("Could not save schedule"); }
  };
  const remove = async (id) => { await api.delete(`/pmi/${id}`); toast.success("Schedule removed"); load(); };

  const removeRecord = async (id) => { await api.delete(`/pmi/records/${id}`); toast.success("Inspection record removed"); load(); };

  const openComplete = (p) => { setEditRecordId(null); setInterim(false); setCompleteFor(p); setCForm({ ...emptyComplete(), inspector: p.inspector || "" }); };
  const openInterim = () => { setEditRecordId(null); setInterim(true); setInterimReg(""); setCForm(emptyComplete()); setCompleteFor({ interim: true }); };
  const openEditRecord = (r) => {
    setEditRecordId(r.id);
    setInterim(false);
    setCForm({
      ...emptyComplete(),
      inspection_date: r.inspection_date || today(), result: r.result || "pass",
      inspector: r.inspector || "", rectified_by: r.rectified_by || "", notes: r.notes || "",
      brake_test_type: r.brake_test_type || "none", laden: !!r.laden,
      service_brake_pct: r.service_brake_pct || "", secondary_brake_pct: r.secondary_brake_pct || "",
      parking_brake_pct: r.parking_brake_pct || "", odometer: r.odometer || "", make_model: r.make_model || "",
      inspector_signature: r.inspector_signature || "", rectifier_signature: r.rectifier_signature || "",
      attachments: r.attachments || [],
      checklist: (r.checklist && r.checklist.length) ? r.checklist : buildPmiChecklist(),
    });
    setCompleteFor({ editing: true, vehicle_reg: r.vehicle_reg });
  };
  const setCItem = (idx, patch) => setCForm((f) => ({ ...f, checklist: f.checklist.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }));
  const submitComplete = async (e) => {
    e.preventDefault();
    const yr = parseInt((cForm.inspection_date || "").slice(0, 4), 10);
    if (!cForm.inspection_date || isNaN(yr) || yr < 2015 || yr > new Date().getFullYear() + 1) {
      toast.error("Please enter a valid inspection date"); return;
    }
    const defects = cForm.checklist.filter((c) => !c.ok);
    const result = defects.length && cForm.result === "pass" ? "fail" : cForm.result;
    const defectSummary = defects.map((c) => `${c.item}${c.note ? `: ${c.note}` : ""}`).join("; ");
    const notes = defects.length ? [defectSummary, cForm.notes].filter(Boolean).join(" — ") : cForm.notes;
    try {
      if (editRecordId) {
        await api.put(`/pmi/records/${editRecordId}`, { ...cForm, result, notes });
        toast.success("Inspection updated");
      } else if (interim) {
        if (!interimReg) { toast.error("Select a vehicle"); return; }
        await api.post(`/pmi/interim`, { ...cForm, vehicle_reg: interimReg, result, notes });
        toast.success("Interim inspection recorded");
      } else {
        await api.post(`/pmi/${completeFor.id}/complete`, { ...cForm, result, notes });
        toast.success("Inspection recorded · next due updated");
      }
      setCompleteFor(null); setEditRecordId(null); load();
    } catch { toast.error("Could not record inspection"); }
  };

  return (
    <div data-testid="inspections-page">
      {!embedded && <Header title="PMI Inspections" subtitle="Recurring maintenance schedules & inspection records" onAdd={openNew} addTestId="add-pmi-button" addLabel="New Schedule" />}
      <div className="flex justify-end gap-2 mb-4">
        <ReportDownload path="/reports/pmi" filename="pmi-report.pdf" testid="download-pmi-pdf" evidence />
        <Button data-testid="add-interim-button" onClick={openInterim} variant="outline" className="rounded-md gap-2 border-slate-300"><ClipboardCheck size={15} /> Interim Inspection</Button>
        {embedded && <Button data-testid="add-pmi-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">New Schedule</Button>}
      </div>

      {(items.length > 0 || records.length > 0) && (
        <RegFolders items={[...items, ...records]} value={regFilter} onChange={setRegFilter} />
      )}

      {items.length === 0 ? <Empty icon={ClipboardCheck} text="No PMI schedules yet. Add a recurring inspection schedule per vehicle." /> : (
        <>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-10">
          {items.filter((p) => matchesReg(regFilter, p.vehicle_reg)).map((p) => (
            <div key={p.id} data-testid="pmi-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Wrench size={16} className="text-slate-400" />
                    <h3 className="font-heading font-bold text-lg text-slate-900">{p.vehicle_reg}</h3>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">Every {p.frequency_weeks} weeks</p>
                </div>
                <div className="flex gap-1">
                  <button data-testid="edit-pmi-button" onClick={() => openEdit(p)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-pmi-button" onClick={() => remove(p.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">Next inspection due</p>
                  <p className="text-sm font-semibold text-slate-700">{p.next_due || "—"}{p.days_left != null && <span className="text-slate-400 font-normal"> · {p.days_left < 0 ? `${Math.abs(p.days_left)}d overdue` : `${p.days_left}d`}</span>}</p>
                </div>
                <StatusBadge status={p.status} />
              </div>
              {(() => {
                const schedRecords = records
                  .filter((r) => r.pmi_id === p.id && r.inspection_date)
                  .sort((a, b) => (a.inspection_date < b.inspection_date ? 1 : -1));
                const last = schedRecords[0]?.inspection_date;
                return (
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-xs text-slate-400">Last inspection: <span className="font-medium text-slate-600">{last || "—"}</span></p>
                    {schedRecords.length > 0 && (
                      <Popover>
                        <PopoverTrigger asChild>
                          <button data-testid="pmi-history-button" className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors">
                            <History size={13} /> History ({schedRecords.length})
                          </button>
                        </PopoverTrigger>
                        <PopoverContent align="end" className="w-80 p-0" data-testid="pmi-history-popover">
                          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-2">
                            <div>
                              <p className="font-heading font-bold text-sm text-slate-900">{p.vehicle_reg} · Inspection history</p>
                              <p className="text-xs text-slate-400">Every {p.frequency_weeks} weeks</p>
                            </div>
                            <button data-testid="pmi-history-pdf-button" onClick={() => downloadPdf(`/pmi/${p.id}/report?include_files=true`, `pmi-history-${p.vehicle_reg}.pdf`)} className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-slate-900 shrink-0"><FileDown size={13} /> PDF + sheets</button>
                          </div>
                          <div className="max-h-72 overflow-y-auto divide-y divide-slate-100">
                            {schedRecords.map((r) => (
                              <div key={r.id} data-testid="pmi-history-row" className="px-4 py-3">
                                <div className="flex items-center justify-between">
                                  <p className="text-sm font-semibold text-slate-800">{r.inspection_date}</p>
                                  <div className="flex items-center gap-2">
                                    {r.checklist?.length > 0 && (
                                      <button data-testid="history-sheet-button" onClick={() => downloadPdf(`/pmi/records/${r.id}/sheet`, `inspection-sheet-${p.vehicle_reg}-${r.inspection_date}.pdf`)} title="Download inspection sheet (PDF)" className="text-slate-400 hover:text-slate-900"><FileDown size={14} /></button>
                                    )}
                                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${resultBadge[r.result] || resultBadge.pass}`}>{r.result?.toUpperCase()}</span>
                                  </div>
                                </div>
                                {(r.inspector || r.notes) && <p className="text-xs text-slate-500 mt-0.5">{[r.inspector, r.notes].filter(Boolean).join(" · ")}</p>}
                                {r.rectified_by && <p className="text-xs text-slate-500 mt-0.5">Rectified by: <span className="font-medium">{r.rectified_by}</span></p>}
                                {r.checklist?.length > 0 && <p className="text-[11px] text-slate-400 mt-0.5">{r.checklist.filter((c) => c.ok).length}/{r.checklist.length} items serviceable</p>}
                                {r.attachments?.length > 0 && <div className="mt-2"><AttachmentThumbs attachments={r.attachments} /></div>}
                              </div>
                            ))}
                          </div>
                        </PopoverContent>
                      </Popover>
                    )}
                  </div>
                );
              })()}
              <Button data-testid="complete-pmi-button" onClick={() => openComplete(p)} variant="outline" className="w-full mt-4 gap-2 border-slate-300">
                <CheckCircle2 size={15} /> Record Inspection
              </Button>
            </div>
          ))}
        </div>
        </>
      )}

      {records.length > 0 && (
        <div className="animate-in-up">
          <h3 className="font-heading font-bold text-lg tracking-tight text-slate-900 mb-3">Recent Inspections</h3>
          <div className="bg-white border border-slate-200 rounded-md divide-y divide-slate-100">
            {records.filter((r) => matchesReg(regFilter, r.vehicle_reg)).map((r) => (
              <div key={r.id} data-testid="pmi-record-row" className="flex items-center justify-between px-5 py-3.5">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-semibold text-slate-900 text-sm">{r.vehicle_reg}</p>
                    {r.inspection_type === "interim" && <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600">Interim</span>}
                  </div>
                  <p className="text-xs text-slate-500">{r.inspection_date}{r.inspector && ` · ${r.inspector}`}{r.notes && ` · ${r.notes}`}</p>
                  {r.attachments?.length > 0 && <div className="mt-2"><AttachmentThumbs attachments={r.attachments} /></div>}
                </div>
                <div className="flex items-center gap-3">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${resultBadge[r.result] || resultBadge.pass}`}>{r.result?.toUpperCase()}</span>
                  {r.checklist?.length > 0 && (
                    <button data-testid="download-sheet-button" onClick={() => downloadPdf(`/pmi/records/${r.id}/sheet`, `inspection-sheet-${r.vehicle_reg}-${r.inspection_date}.pdf`)} title="Download inspection sheet (PDF)" className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-slate-900"><FileDown size={14} /> Sheet</button>
                  )}
                  <button data-testid="edit-pmi-record-button" onClick={() => openEditRecord(r)} title="Edit inspection" className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-pmi-record-button" onClick={() => removeRecord(r.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add / edit schedule */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit PMI Schedule" : "New PMI Schedule"}</DialogTitle><DialogDescription className="sr-only">PMI schedule form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="pmi-reg"><SelectValue placeholder={assets.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Frequency (weeks)"><Input data-testid="pmi-frequency" type="number" min="0" value={form.frequency_weeks} onChange={(e) => setForm({ ...form, frequency_weeks: e.target.value })} placeholder="0 = one-off / interim" /></Field>
              <Field label="Next Due"><Input data-testid="pmi-next-due" type="date" value={form.next_due} onChange={(e) => setForm({ ...form, next_due: e.target.value })} /></Field>
            </div>
            <Field label="Default Inspector"><Input data-testid="pmi-inspector" value={form.inspector} onChange={(e) => setForm({ ...form, inspector: e.target.value })} placeholder="e.g. In-house / ABC Commercials" /></Field>
            <DialogFooter><Button data-testid="save-pmi-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Create Schedule"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Record inspection */}
      <Dialog open={!!completeFor} onOpenChange={(v) => { if (!v) { setCompleteFor(null); setEditRecordId(null); } }}>
        <DialogContent className="max-w-2xl max-h-[92vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editRecordId ? `Edit Inspection — ${completeFor?.vehicle_reg}` : interim ? "Interim Inspection" : `Record PMI — ${completeFor?.vehicle_reg}`}</DialogTitle><DialogDescription className="sr-only">Record completed inspection form</DialogDescription></DialogHeader>
          <form onSubmit={submitComplete} className="space-y-4">
            {interim && (
              <Field label="Vehicle *">
                <Select value={interimReg} onValueChange={setInterimReg}>
                  <SelectTrigger data-testid="interim-reg"><SelectValue placeholder={assets.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
                  <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                </Select>
                <p className="text-xs text-slate-400 mt-1">One-off inspection — no recurring schedule is created.</p>
              </Field>
            )}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Inspection Date *"><Input data-testid="complete-date" type="date" required min="2015-01-01" max={today()} value={cForm.inspection_date} onChange={(e) => setCForm({ ...cForm, inspection_date: e.target.value })} /></Field>
              <Field label="Result">
                <Select value={cForm.result} onValueChange={(v) => setCForm({ ...cForm, result: v })}>
                  <SelectTrigger data-testid="complete-result-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{RESULTS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Inspector"><Input data-testid="complete-inspector" value={cForm.inspector} onChange={(e) => setCForm({ ...cForm, inspector: e.target.value })} placeholder="Suitably qualified person" /></Field>
              <Field label="Rectified by (Workshop Manager)"><Input data-testid="complete-rectified-by" value={cForm.rectified_by} onChange={(e) => setCForm({ ...cForm, rectified_by: e.target.value })} placeholder="Who rectified defects" /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Odometer reading"><Input data-testid="complete-odometer" value={cForm.odometer} onChange={(e) => setCForm({ ...cForm, odometer: e.target.value })} placeholder="e.g. 342,118 km" /></Field>
              <Field label="Vehicle make / model"><Input data-testid="complete-make-model" value={cForm.make_model} onChange={(e) => setCForm({ ...cForm, make_model: e.target.value })} placeholder="e.g. DAF XF 480" /></Field>
            </div>

            <div className="border-t border-slate-100 pt-3" data-testid="pmi-checklist">
              {(() => {
                const failCount = cForm.checklist.filter((c) => !c.ok).length;
                return (
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">Inspection Checklist ({cForm.checklist.length} points)</p>
                    <div className="flex items-center gap-2">
                      <button type="button" data-testid="pmi-all-serviceable" onClick={() => setCForm((f) => ({ ...f, checklist: f.checklist.map((c) => ({ ...c, ok: true, note: "" })) }))} className="text-[11px] font-semibold text-green-700 hover:underline">Mark all ✓</button>
                      <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${failCount ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"}`}>{failCount ? `${failCount} defect(s)` : "All serviceable"}</span>
                    </div>
                  </div>
                );
              })()}
              {(() => { let flat = -1; return PMI_CHECKLIST.map((sec) => (
                <div key={sec.section} className="mb-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-slate-700 bg-slate-50 px-3 py-1.5 rounded-md">{sec.section}</p>
                  <div className="divide-y divide-slate-100">
                    {sec.items.map((item) => {
                      flat += 1; const idx = flat; const c = cForm.checklist[idx];
                      return (
                        <div key={item} data-testid="pmi-check-item" className="py-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm text-slate-700 flex-1">{item}</span>
                            <Select value={c.ok ? "ok" : "defect"} onValueChange={(v) => setCItem(idx, { ok: v === "ok", note: v === "ok" ? "" : c.note })}>
                              <SelectTrigger data-testid={`pmi-item-select-${idx}`} className={`w-28 h-8 shrink-0 ${c.ok ? "text-green-700" : "text-red-700 border-red-300"}`}><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="ok">✓ Serviceable</SelectItem>
                                <SelectItem value="defect">✗ Defect</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                          {(!c.ok || idx === 0) && <Input data-testid={`pmi-item-note-${idx}`} value={c.note} onChange={(e) => setCItem(idx, { note: e.target.value })} placeholder={idx === 0 ? "Enter registration, licence & VIN numbers" : "Description of defect…"} className="mt-1.5 h-8 text-sm" />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )); })()}
            </div>

            <div className="border-t border-slate-100 pt-3">
              <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold mb-2">Brake Test</p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Brake test type">
                  <Select value={cForm.brake_test_type} onValueChange={(v) => setCForm({ ...cForm, brake_test_type: v })}>
                    <SelectTrigger data-testid="brake-type-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      <SelectItem value="roller">Roller brake test</SelectItem>
                      <SelectItem value="decelerometer">Decelerometer</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                {!isIE && (
                  <Field label="Laden?">
                    <Select value={cForm.laden ? "yes" : "no"} onValueChange={(v) => setCForm({ ...cForm, laden: v === "yes" })}>
                      <SelectTrigger data-testid="brake-laden-select"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="yes">Laden</SelectItem><SelectItem value="no">Unladen</SelectItem></SelectContent>
                    </Select>
                  </Field>
                )}
                <Field label="Service brake %"><Input data-testid="brake-service" value={cForm.service_brake_pct} onChange={(e) => setCForm({ ...cForm, service_brake_pct: e.target.value })} placeholder="e.g. 52" /></Field>
                <Field label="Secondary brake %"><Input data-testid="brake-secondary" value={cForm.secondary_brake_pct} onChange={(e) => setCForm({ ...cForm, secondary_brake_pct: e.target.value })} placeholder="e.g. 28" /></Field>
                <Field label="Parking brake %"><Input data-testid="brake-parking" value={cForm.parking_brake_pct} onChange={(e) => setCForm({ ...cForm, parking_brake_pct: e.target.value })} placeholder="e.g. 18" /></Field>
              </div>
            </div>
            <Field label="Notes"><Textarea data-testid="complete-notes" rows={3} value={cForm.notes} onChange={(e) => setCForm({ ...cForm, notes: e.target.value })} placeholder="Advisories, work carried out…" /></Field>
            <div className="border-t border-slate-100 pt-3">
              <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold mb-2">Signatures (Suitably Qualified Person)</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <SignaturePad testid="inspector-signature" label="Inspection carried out by" value={cForm.inspector_signature} onChange={(v) => setCForm((f) => ({ ...f, inspector_signature: v }))} />
                <SignaturePad testid="rectifier-signature" label="Defects rectified by" value={cForm.rectifier_signature} onChange={(v) => setCForm((f) => ({ ...f, rectifier_signature: v }))} />
              </div>
            </div>
            <Field label="Inspection report / sheet (save a copy)"><FileUpload testid="pmi-report-upload" attachments={cForm.attachments} onChange={(a) => setCForm({ ...cForm, attachments: a })} label="Upload the signed PMI inspection sheet (image or PDF)" /></Field>
            <DialogFooter><Button data-testid="submit-complete-button" type="submit" className="bg-black hover:bg-slate-800 gap-2"><CheckCircle2 size={15} /> {editRecordId ? "Save Changes" : interim ? "Record Interim Inspection" : "Record & Reschedule"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Inspections() {
  return <InspectionsPanel />;
}
