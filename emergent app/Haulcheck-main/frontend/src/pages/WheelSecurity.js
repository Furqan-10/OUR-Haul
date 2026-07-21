import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, Disc3 } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { RegFolders, matchesReg } from "@/components/RegFolders";
import { ReportDownload } from "@/components/ReportDownload";

const RESULTS = { pass: "text-green-700 bg-green-50", advisory: "text-amber-700 bg-amber-50", fail: "text-red-700 bg-red-50" };
const today = () => new Date().toISOString().slice(0, 10);
const empty = { vehicle_reg: "", audit_date: today(), result: "pass", torque_setting: "", checked_by: "", next_due: "", notes: "", attachments: [] };

export function WheelSecurityPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [regFilter, setRegFilter] = useState("");
  const [assets, setAssets] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => {
    const [w, v, t] = await Promise.all([api.get("/wheel-audits"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(w.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (a) => { setForm({ ...empty, ...a }); setEditId(a.id); setOpen(true); };

  const save = async () => {
    if (!form.vehicle_reg) return toast.error("Select a vehicle");
    const payload = { ...form, next_due: form.next_due || null, audit_date: form.audit_date || null };
    try {
      if (editId) await api.put(`/wheel-audits/${editId}`, payload);
      else await api.post("/wheel-audits", payload);
      toast.success(editId ? "Audit updated" : "Wheel security audit logged");
      setOpen(false); load();
    } catch { toast.error("Could not save audit"); }
  };

  const remove = async (id) => { await api.delete(`/wheel-audits/${id}`); load(); };

  return (
    <div data-testid="wheel-security-page">
      <div className="flex justify-end gap-2 mb-4">
        <ReportDownload path="/reports/wheel" filename="wheel-audits-report.pdf" testid="download-wheel-pdf" evidence />
        <Button data-testid="add-wheel-audit-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Log Wheel Audit</Button>
      </div>

      {items.length === 0 ? <Empty icon={Disc3} text="No wheel security audits yet. Log torque/re-torque checks with the result and next due date." /> : (
        <div>
          <RegFolders items={items} value={regFilter} onChange={setRegFilter} />
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.filter((a) => matchesReg(regFilter, a.vehicle_reg)).map((a) => (
            <div key={a.id} className="bg-white border border-slate-200 rounded-md p-5" data-testid="wheel-audit-card">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-heading font-bold text-lg tracking-tight">{a.vehicle_reg}</h3>
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${RESULTS[a.result] || RESULTS.pass}`}>{a.result}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">Audited {a.audit_date || "—"}{a.checked_by ? ` · ${a.checked_by}` : ""}</p>
                </div>
                <div className="flex gap-1">
                  <button data-testid="edit-wheel-audit-button" onClick={() => openEdit(a)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-wheel-audit-button" onClick={() => remove(a.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              {a.torque_setting && <p className="text-sm text-slate-600">Torque: <span className="font-semibold">{a.torque_setting}</span></p>}
              {a.notes && <p className="text-sm text-slate-500 mt-1 line-clamp-2">{a.notes}</p>}
              <div className="mt-3 flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
                <span>Next due</span>
                <div className="flex items-center gap-2"><span className="font-semibold">{a.next_due || "—"}</span><StatusBadge status={a.status} /></div>
              </div>
              {a.attachments?.length > 0 && <div className="mt-3"><AttachmentThumbs attachments={a.attachments} /></div>}
            </div>
          ))}
          </div>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editId ? "Edit" : "Log"} Wheel Security Audit</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="wheel-reg"><SelectValue placeholder={assets.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Audit date"><Input data-testid="wheel-date" type="date" value={form.audit_date || ""} onChange={(e) => setForm({ ...form, audit_date: e.target.value })} /></Field>
            <Field label="Result">
              <Select value={form.result} onValueChange={(v) => setForm({ ...form, result: v })}>
                <SelectTrigger data-testid="wheel-result"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="pass">Pass</SelectItem>
                  <SelectItem value="advisory">Advisory</SelectItem>
                  <SelectItem value="fail">Fail</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Torque setting"><Input data-testid="wheel-torque" value={form.torque_setting} onChange={(e) => setForm({ ...form, torque_setting: e.target.value })} placeholder="e.g. 450 Nm" /></Field>
            <Field label="Checked by"><Input data-testid="wheel-checkedby" value={form.checked_by} onChange={(e) => setForm({ ...form, checked_by: e.target.value })} placeholder="Fitter / technician" /></Field>
            <Field label="Next due"><Input data-testid="wheel-nextdue" type="date" value={form.next_due || ""} onChange={(e) => setForm({ ...form, next_due: e.target.value })} /></Field>
            <div className="col-span-2"><Field label="Notes"><Textarea data-testid="wheel-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Findings, re-torque details…" /></Field></div>
            <div className="col-span-2"><Field label="Attachments"><FileUpload attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field></div>
          </div>
          <DialogFooter><Button data-testid="save-wheel-audit-button" onClick={save} className="bg-black hover:bg-slate-800">{editId ? "Save" : "Log Audit"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function WheelSecurity() {
  return <WheelSecurityPanel />;
}
