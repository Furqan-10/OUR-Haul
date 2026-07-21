import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";
import { RegFolders, matchesReg } from "@/components/RegFolders";
import { ReportDownload } from "@/components/ReportDownload";

const TYPES = ["Full service", "Interim service", "Oil & filter", "Air-con / AdBlue", "Repair", "Other"];
const empty = { vehicle_reg: "", service_date: new Date().toISOString().slice(0, 10), service_type: "Full service", odometer: "", provider: "", cost: "", next_service_due: "", notes: "", attachments: [] };

export function ServicePanel() {
  const { user } = useAuth();
  const cur = user?.region === "IE" ? "€" : "£";
  const [items, setItems] = useState([]);
  const [assets, setAssets] = useState([]);
  const [regFilter, setRegFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => {
    const [s, v, t] = await Promise.all([api.get("/service-records"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(s.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.registration)].filter(Boolean));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (r) => { setForm({ ...empty, ...r, service_date: r.service_date || "", next_service_due: r.next_service_due || "", attachments: r.attachments || [] }); setEditId(r.id); setOpen(true); };
  const num = (v) => (v === "" || v == null ? 0 : Number(v));

  const save = async (e) => {
    e.preventDefault();
    if (!form.vehicle_reg) { toast.error("Select a vehicle"); return; }
    const payload = { ...form, odometer: num(form.odometer), cost: num(form.cost), service_date: form.service_date || null, next_service_due: form.next_service_due || null };
    try {
      if (editId) await api.put(`/service-records/${editId}`, payload);
      else await api.post("/service-records", payload);
      toast.success(editId ? "Service record updated" : "Service record added");
      setOpen(false); load();
    } catch { toast.error("Could not save service record"); }
  };
  const remove = async (id) => { await api.delete(`/service-records/${id}`); toast.success("Record removed"); load(); };

  return (
    <div data-testid="service-page">
      <div className="flex justify-end gap-2 mb-4">
        <ReportDownload path="/reports/service" filename="service-report.pdf" testid="download-service-pdf" evidence />
        <Button data-testid="add-service-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Service Record</Button>
      </div>

      {items.length === 0 ? <Empty icon={Wrench} text="No service records yet. Log routine servicing, repairs and the next service due." /> : (
        <div>
          <RegFolders items={items} value={regFilter} onChange={setRegFilter} />
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.filter((r) => matchesReg(regFilter, r.vehicle_reg)).map((r) => (
            <div key={r.id} data-testid="service-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{r.service_type}</p>
                  <h3 className="font-heading font-bold text-lg text-slate-900">{r.vehicle_reg}</h3>
                  <p className="text-xs text-slate-500">{r.service_date || "—"}{r.odometer ? ` · ${r.odometer} mi` : ""}{r.provider ? ` · ${r.provider}` : ""}</p>
                </div>
                <div className="flex gap-1">
                  <button data-testid="edit-service-button" onClick={() => openEdit(r)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-service-button" onClick={() => remove(r.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">Next service due</p>
                  <p className="text-sm font-semibold text-slate-700">{r.next_service_due || "—"}{r.days_left != null && <span className="text-slate-400 font-normal"> · {r.days_left < 0 ? `${Math.abs(r.days_left)}d overdue` : `${r.days_left}d`}</span>}</p>
                </div>
                {r.next_service_due && <StatusBadge status={r.status} />}
              </div>
              {r.cost ? <p className="text-xs text-slate-500 mt-2">Cost: {cur}{r.cost}</p> : null}
              {r.notes && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{r.notes}</p>}
              <AttachmentThumbs attachments={r.attachments} />
            </div>
          ))}
          </div>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Service Record" : "Add Service Record"}</DialogTitle><DialogDescription className="sr-only">Vehicle service record form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="service-vehicle"><SelectValue placeholder={assets.length ? "Select vehicle" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Service type">
                <Select value={form.service_type} onValueChange={(v) => setForm({ ...form, service_type: v })}>
                  <SelectTrigger data-testid="service-type"><SelectValue /></SelectTrigger>
                  <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Date"><Input data-testid="service-date" type="date" value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Odometer (miles)"><Input data-testid="service-odometer" type="number" value={form.odometer} onChange={(e) => setForm({ ...form, odometer: e.target.value })} /></Field>
              <Field label={`Cost (${cur})`}><Input data-testid="service-cost" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Provider / garage"><Input data-testid="service-provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} /></Field>
              <Field label="Next service due"><Input data-testid="service-next-due" type="date" value={form.next_service_due} onChange={(e) => setForm({ ...form, next_service_due: e.target.value })} /></Field>
            </div>
            <Field label="Work carried out / notes"><Input data-testid="service-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Oil, filters, brakes…" /></Field>
            <Field label="Invoice / documents"><FileUpload testid="service-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-service-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Record"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Service() {
  return <ServicePanel />;
}
