import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, Users, Clock, GraduationCap, FileDown, FileText, Smartphone, QrCode } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { FileUpload } from "@/components/FileUpload";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { downloadPdf } from "@/lib/download";
import { QRCodeSVG } from "qrcode.react";

const empty = { name: "", licence_number: "", licence_expiry: "", cpc_expiry: "", tacho_card_expiry: "", licence_check_date: "", licence_check_code: "", penalty_points: 0, licence_check_due: "", weekly_hours: 0, max_weekly_hours: 56, assigned_vehicle_reg: "", notes: "" };
const DRIVER_DOC_TYPES = ["Driver Infringement", "Infringement Report", "Warning Letter", "Attestation Record", "Indoctrination Document", "Adhoc Note", "Other"];
const emptyDoc = { title: "", doc_type: "Driver Infringement", reference: "", expiry_date: "", notes: "", attachments: [] };

export default function Drivers() {
  const [items, setItems] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [training, setTraining] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [docFor, setDocFor] = useState(null);
  const [docForm, setDocForm] = useState(emptyDoc);
  const [cpcFor, setCpcFor] = useState(null);
  const [cpcForm, setCpcForm] = useState({ course_name: "", hours: "", completed_date: new Date().toISOString().slice(0, 10), provider: "" });
  const [qrFor, setQrFor] = useState(null);

  const load = async () => {
    const [d, t, docs, v] = await Promise.all([api.get("/drivers"), api.get("/training"), api.get("/documents"), api.get("/vehicles")]);
    setItems(d.data); setTraining(t.data); setDocuments(docs.data.filter((x) => x.driver_id)); setVehicles(v.data.map((x) => x.registration));
  };
  const driverTraining = (d) => training.filter((t) => (t.driver_id && t.driver_id === d.id) || t.driver_name === d.name);
  const driverDocs = (d) => documents.filter((x) => x.driver_id === d.id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (d) => {
    setForm({ ...empty, ...d, licence_expiry: d.licence_expiry || "", cpc_expiry: d.cpc_expiry || "", tacho_card_expiry: d.tacho_card_expiry || "", licence_check_date: d.licence_check_date || "", licence_check_due: d.licence_check_due || "" });
    setEditId(d.id); setOpen(true);
  };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, weekly_hours: Number(form.weekly_hours), max_weekly_hours: Number(form.max_weekly_hours), penalty_points: Number(form.penalty_points) };
    ["licence_expiry", "cpc_expiry", "tacho_card_expiry", "licence_check_date", "licence_check_due"].forEach((k) => { if (!payload[k]) payload[k] = null; });
    try {
      if (editId) await api.put(`/drivers/${editId}`, payload);
      else await api.post("/drivers", payload);
      toast.success(editId ? "Driver updated" : "Driver added");
      setOpen(false); load();
    } catch { toast.error("Could not save driver"); }
  };
  const remove = async (id) => { await api.delete(`/drivers/${id}`); toast.success("Driver removed"); load(); };

  const issueCode = async (d) => {
    try {
      const { data } = await api.post(`/drivers/${d.id}/access-code`);
      toast.success(`Access code: ${data.access_code}`);
      load();
    } catch { toast.error("Could not generate code"); }
  };

  const openDoc = (d) => { setDocFor(d); setDocForm(emptyDoc); };
  const saveDoc = async () => {
    try {
      await api.post("/documents", { ...docForm, driver_id: docFor.id, driver_name: docFor.name, expiry_date: docForm.expiry_date || null });
      toast.success("Document added"); setDocFor(null); load();
    } catch { toast.error("Could not save document"); }
  };
  const removeDoc = async (id) => { await api.delete(`/documents/${id}`); toast.success("Document removed"); load(); };

  const openCpc = (d) => { setCpcFor(d); setCpcForm({ course_name: "", hours: "", completed_date: new Date().toISOString().slice(0, 10), provider: "" }); };
  const saveCpc = async () => {
    if (!cpcForm.course_name || !cpcForm.hours) { toast.error("Enter a course and hours"); return; }
    if (!cpcForm.completed_date) { toast.error("Enter the completed date"); return; }
    try {
      await api.post("/training", {
        driver_id: cpcFor.id, driver_name: cpcFor.name, course_name: cpcForm.course_name,
        category: "Driver CPC", hours: Number(cpcForm.hours), completed_date: cpcForm.completed_date || null,
        expiry_date: cpcFor.cpc_expiry || null, provider: cpcForm.provider,
      });
      toast.success("CPC training logged"); setCpcFor(null); load();
    } catch { toast.error("Could not log training"); }
  };

  return (
    <div data-testid="drivers-page">
      <Header title="Drivers" subtitle="Licence, CPC, tachograph card & weekly hours" onAdd={openNew} addTestId="add-driver-button" addLabel="Add Driver" />
      <div className="flex justify-end mb-4 -mt-4">
        <Button data-testid="download-drivers-pdf" variant="outline" onClick={() => downloadPdf("/reports/drivers", "drivers-report.pdf")} className="rounded-md gap-2 border-slate-300"><FileDown size={16} /> Download PDF</Button>
      </div>

      {items.length === 0 ? <Empty icon={Users} text="No drivers yet. Add drivers to track licences and hours." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((d) => {
            const over = d.weekly_hours > d.max_weekly_hours;
            return (
              <div key={d.id} data-testid="driver-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-heading font-bold text-lg text-slate-900">{d.name}</h3>
                    <p className="text-xs text-slate-500">{d.licence_number || "No licence no."}</p>
                  </div>
                  <div className="flex gap-1">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button data-testid="export-driver-button" className="text-slate-400 hover:text-slate-900 p-1" title="Export PDF"><FileDown size={15} /></button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem data-testid="export-driver-summary" onClick={() => downloadPdf(`/export/driver/${d.id}`, `driver-${(d.name || "file").replace(/ /g, "_")}.pdf`)}>
                          Driver file (summary)
                        </DropdownMenuItem>
                        <DropdownMenuItem data-testid="export-driver-files" onClick={() => downloadPdf(`/export/driver/${d.id}?include_files=true`, `driver-${(d.name || "file").replace(/ /g, "_")}-pack.pdf`)}>
                          Driver file + certificates
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <button data-testid="edit-driver-button" onClick={() => openEdit(d)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                    <button data-testid="delete-driver-button" onClick={() => remove(d.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                  </div>
                </div>
                <div className="mt-4 space-y-2">
                  <Row label="Licence" status={d.licence_status} date={d.licence_expiry} />
                  <Row label="CPC" status={d.cpc_status} date={d.cpc_expiry} />
                  <Row label="Tacho Card" status={d.tacho_status} date={d.tacho_card_expiry} />
                  <Row label="Licence Check" status={d.licence_check_status} date={d.licence_check_due} />
                </div>
                <div className="mt-3 rounded-md bg-slate-50 px-3 py-2.5" data-testid="driver-cpc-hours">
                  <div className="flex items-center justify-between text-sm mb-1.5">
                    <span className="text-slate-500">Driver CPC training</span>
                    <div className="flex items-center gap-2">
                      <button data-testid="log-cpc-button" onClick={() => openCpc(d)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-900">+ Log</button>
                      <span className={`font-bold ${(d.cpc_hours || 0) >= 35 ? "text-green-700" : "text-amber-600"}`}>{(d.cpc_hours || 0).toFixed(0)} / 35h</span>
                    </div>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                    <div data-testid="cpc-progress-bar" className={`h-full rounded-full transition-all duration-500 ${(d.cpc_hours || 0) >= 35 ? "bg-green-600" : "bg-amber-500"}`} style={{ width: `${Math.min(100, ((d.cpc_hours || 0) / 35) * 100)}%` }} />
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1.5">
                    {(d.cpc_hours || 0) >= 35 ? "Periodic training complete for this cycle" : `${Math.max(0, 35 - (d.cpc_hours || 0)).toFixed(0)}h remaining`}
                    {d.cpc_expiry ? ` · renews ${d.cpc_expiry}` : ""}
                  </p>
                </div>
                {d.penalty_points > 0 && (
                  <div className="mt-2 text-xs text-slate-500">Licence points: <span className="font-semibold text-slate-700">{d.penalty_points}</span>{d.licence_check_code ? ` · Check code ${d.licence_check_code}` : ""}</div>
                )}
                <div className={`mt-4 flex items-center justify-between rounded-md px-3 py-2 text-sm ${over ? "bg-red-50 text-red-700" : "bg-slate-50 text-slate-600"}`}>
                  <span className="flex items-center gap-1.5"><Clock size={15} /> Weekly hours</span>
                  <span className="font-bold">{d.weekly_hours} / {d.max_weekly_hours}h</span>
                </div>
                <div className="mt-3 rounded-md border border-slate-200 px-3 py-2.5" data-testid="driver-access-code">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-slate-400 font-semibold"><Smartphone size={12} /> Driver App Access</div>
                    <button data-testid="issue-code-button" onClick={() => issueCode(d)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-900">{d.access_code ? "Regenerate" : "Generate code"}</button>
                  </div>
                  {d.access_code ? (
                    <div className="mt-1.5 flex items-center justify-between">
                      <span data-testid="driver-code-value" className="font-mono font-black text-lg tracking-[0.25em] text-slate-900">{d.access_code}</span>
                      <div className="flex items-center gap-2">
                        {d.assigned_vehicle_reg && <span className="text-xs text-slate-400">→ {d.assigned_vehicle_reg}</span>}
                        <button data-testid="show-qr-button" onClick={() => setQrFor(d)} title="Show QR to install & auto-login" className="text-slate-400 hover:text-slate-900"><QrCode size={17} /></button>
                      </div>
                    </div>
                  ) : <p className="text-[11px] text-slate-400 mt-1">Generate a code so this driver can log in at <span className="font-semibold">/driver</span></p>}
                </div>
                {driverTraining(d).length > 0 && (
                  <div className="mt-3 border-t border-slate-100 pt-3" data-testid="driver-training-list">
                    <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold mb-1.5 flex items-center gap-1"><GraduationCap size={12} /> Training</p>
                    <div className="space-y-1.5">
                      {driverTraining(d).map((t) => (
                        <div key={t.id} className="flex items-center justify-between text-xs gap-2">
                          <span className="text-slate-600 truncate">{t.course_name || t.category}</span>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-slate-400">{t.expiry_date || "—"}</span>
                            <StatusBadge status={t.status} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mt-3 border-t border-slate-100 pt-3" data-testid="driver-docs-list">
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold flex items-center gap-1"><FileText size={12} /> Documents</p>
                    <button data-testid="add-driver-doc-button" onClick={() => openDoc(d)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-900">+ Add</button>
                  </div>
                  {driverDocs(d).length > 0 ? (
                    <div className="space-y-1.5">
                      {driverDocs(d).map((x) => (
                        <div key={x.id} data-testid="driver-doc-item" className="flex items-center justify-between text-xs gap-2">
                          <span className="text-slate-600 truncate"><span className="text-slate-400">{x.doc_type}:</span> {x.title}</span>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-slate-400">{x.expiry_date || ""}</span>
                            <button data-testid="delete-driver-doc-button" onClick={() => removeDoc(x.id)} className="text-slate-300 hover:text-red-600"><Trash2 size={12} /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : <p className="text-xs text-slate-400">No documents yet.</p>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Driver" : "Add Driver"}</DialogTitle><DialogDescription className="sr-only">Driver details form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Name *"><Input data-testid="drv-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="John Smith" /></Field>
            <Field label="Licence Number"><Input data-testid="drv-licence-no" value={form.licence_number} onChange={(e) => setForm({ ...form, licence_number: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Licence Expiry"><Input data-testid="drv-licence-exp" type="date" value={form.licence_expiry} onChange={(e) => setForm({ ...form, licence_expiry: e.target.value })} /></Field>
              <Field label="CPC Expiry"><Input data-testid="drv-cpc-exp" type="date" value={form.cpc_expiry} onChange={(e) => setForm({ ...form, cpc_expiry: e.target.value })} /></Field>
            </div>
            <Field label="Tacho Card Expiry"><Input data-testid="drv-tacho-exp" type="date" value={form.tacho_card_expiry} onChange={(e) => setForm({ ...form, tacho_card_expiry: e.target.value })} /></Field>
            <Field label="Assigned Vehicle (for driver app)">
              <Select value={form.assigned_vehicle_reg || "none"} onValueChange={(v) => setForm({ ...form, assigned_vehicle_reg: v === "none" ? "" : v })}>
                <SelectTrigger data-testid="drv-assigned-vehicle"><SelectValue placeholder="Select vehicle" /></SelectTrigger>
                <SelectContent><SelectItem value="none">None</SelectItem>{vehicles.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="border-t border-slate-100 pt-4">
              <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold mb-3">Licence Checking (DVLA / NDLS)</p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Last Check Date"><Input data-testid="drv-check-date" type="date" value={form.licence_check_date} onChange={(e) => setForm({ ...form, licence_check_date: e.target.value })} /></Field>
                <Field label="Next Check Due"><Input data-testid="drv-check-due" type="date" value={form.licence_check_due} onChange={(e) => setForm({ ...form, licence_check_due: e.target.value })} /></Field>
                <Field label="Check Code"><Input data-testid="drv-check-code" value={form.licence_check_code} onChange={(e) => setForm({ ...form, licence_check_code: e.target.value })} placeholder="DVLA share code" /></Field>
                <Field label="Penalty Points"><Input data-testid="drv-points" type="number" value={form.penalty_points} onChange={(e) => setForm({ ...form, penalty_points: e.target.value })} /></Field>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Weekly Hours"><Input data-testid="drv-hours" type="number" step="0.5" value={form.weekly_hours} onChange={(e) => setForm({ ...form, weekly_hours: e.target.value })} /></Field>
              <Field label="Max Weekly Hours"><Input data-testid="drv-max-hours" type="number" step="0.5" value={form.max_weekly_hours} onChange={(e) => setForm({ ...form, max_weekly_hours: e.target.value })} /></Field>
            </div>
            <DialogFooter><Button data-testid="save-driver-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Driver"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!docFor} onOpenChange={(o) => !o && setDocFor(null)}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">Add document — {docFor?.name}</DialogTitle><DialogDescription className="sr-only">Driver document form</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <Field label="Type">
              <Select value={docForm.doc_type} onValueChange={(v) => setDocForm({ ...docForm, doc_type: v })}>
                <SelectTrigger data-testid="ddoc-type"><SelectValue /></SelectTrigger>
                <SelectContent>{DRIVER_DOC_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Title *"><Input data-testid="ddoc-title" value={docForm.title} onChange={(e) => setDocForm({ ...docForm, title: e.target.value })} placeholder="e.g. Speeding infringement — M6" /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Reference"><Input data-testid="ddoc-ref" value={docForm.reference} onChange={(e) => setDocForm({ ...docForm, reference: e.target.value })} /></Field>
              <Field label="Date / Expiry"><Input data-testid="ddoc-date" type="date" value={docForm.expiry_date} onChange={(e) => setDocForm({ ...docForm, expiry_date: e.target.value })} /></Field>
            </div>
            <Field label="Notes"><Input data-testid="ddoc-notes" value={docForm.notes} onChange={(e) => setDocForm({ ...docForm, notes: e.target.value })} /></Field>
            <Field label="Scan / File"><FileUpload testid="ddoc-upload" attachments={docForm.attachments} onChange={(a) => setDocForm({ ...docForm, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-driver-doc-button" onClick={saveDoc} disabled={!docForm.title} className="bg-black hover:bg-slate-800">Add Document</Button></DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!cpcFor} onOpenChange={(o) => !o && setCpcFor(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle className="font-heading">Log CPC training — {cpcFor?.name}</DialogTitle><DialogDescription>Adds a Driver CPC training record; the progress bar updates automatically.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <Field label="Course / module *"><Input data-testid="cpc-course" value={cpcForm.course_name} onChange={(e) => setCpcForm({ ...cpcForm, course_name: e.target.value })} placeholder="e.g. Drivers' Hours & WTD" /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Hours *"><Input data-testid="cpc-hours" type="number" step="0.5" value={cpcForm.hours} onChange={(e) => setCpcForm({ ...cpcForm, hours: e.target.value })} placeholder="7" /></Field>
              <Field label="Completed *"><Input data-testid="cpc-date" type="date" required value={cpcForm.completed_date} onChange={(e) => setCpcForm({ ...cpcForm, completed_date: e.target.value })} /></Field>
            </div>
            <Field label="Provider"><Input data-testid="cpc-provider" value={cpcForm.provider} onChange={(e) => setCpcForm({ ...cpcForm, provider: e.target.value })} placeholder="Training centre" /></Field>
            <DialogFooter><Button data-testid="save-cpc-button" onClick={saveCpc} disabled={!cpcForm.course_name || !cpcForm.hours} className="bg-black hover:bg-slate-800">Log Training</Button></DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={!!qrFor} onOpenChange={(o) => !o && setQrFor(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle className="font-heading">Driver app QR — {qrFor?.name}</DialogTitle>
            <DialogDescription>Ask the driver to scan this with their phone camera. It opens the app and fills in their code automatically.</DialogDescription>
          </DialogHeader>
          {qrFor && (
            <div className="flex flex-col items-center gap-4 py-2" data-testid="driver-qr">
              <div className="bg-white p-4 rounded-lg border border-slate-200">
                <QRCodeSVG value={`${window.location.origin}/driver?code=${qrFor.access_code}`} size={200} level="M" />
              </div>
              <div className="text-center">
                <p className="text-xs text-slate-400 uppercase tracking-widest">Access code</p>
                <p className="font-mono font-black text-xl tracking-[0.25em] text-slate-900">{qrFor.access_code}</p>
              </div>
              <p className="text-[11px] text-slate-400 text-center">On the phone, after it opens they can tap <span className="font-semibold">Add to Home Screen</span> to install HaulCheck.</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, status, date }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-500">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-400">{date || "—"}</span>
        <StatusBadge status={status} />
      </div>
    </div>
  );
}
