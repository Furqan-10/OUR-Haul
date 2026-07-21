import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, GraduationCap } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";

const CATEGORIES = ["Driver CPC", "ADR", "First Aid", "Manual Handling", "Forklift / FLT", "Tacho / Drivers' Hours", "Load Security", "HIAB / Crane", "Health & Safety", "Other"];
const empty = { driver_id: "", driver_name: "", course_name: "", category: "Driver CPC", completed_date: "", expiry_date: "", provider: "", hours: 0, notes: "", attachments: [] };

export function TrainingPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [folder, setFolder] = useState("All");

  const driverFolders = ["All", ...Array.from(new Set(items.map((t) => t.driver_name || "Unassigned")))];
  const shown = folder === "All" ? items : items.filter((t) => (t.driver_name || "Unassigned") === folder);
  const countFor = (name) => (name === "All" ? items.length : items.filter((t) => (t.driver_name || "Unassigned") === name).length);

  const load = async () => {
    setItems((await api.get("/training")).data);
    setDrivers((await api.get("/drivers")).data);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (t) => {
    setForm({ ...empty, ...t, completed_date: t.completed_date || "", expiry_date: t.expiry_date || "", attachments: t.attachments || [] });
    setEditId(t.id); setOpen(true);
  };

  const pickDriver = (id) => {
    const d = drivers.find((x) => x.id === id);
    setForm({ ...form, driver_id: id, driver_name: d ? d.name : "" });
  };

  const save = async (e) => {
    e.preventDefault();
    if (!form.completed_date) { toast.error("Please enter the date the training was completed"); return; }
    const payload = { ...form, hours: Number(form.hours) || 0, completed_date: form.completed_date || null, expiry_date: form.expiry_date || null };
    try {
      if (editId) await api.put(`/training/${editId}`, payload);
      else await api.post("/training", payload);
      toast.success(editId ? "Training updated" : "Training record added");
      setOpen(false); load();
    } catch { toast.error("Could not save training record"); }
  };
  const remove = async (id) => { await api.delete(`/training/${id}`); toast.success("Record removed"); load(); };

  return (
    <div data-testid="training-page">
      {!embedded && <Header title="Driver Training" subtitle="Qualifications, courses & certificate records" onAdd={openNew} addTestId="add-training-button" addLabel="Add Record" />}
      {embedded && (
        <div className="flex justify-end mb-4">
          <Button data-testid="add-training-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Record</Button>
        </div>
      )}

      {items.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6" data-testid="training-folders">
          {driverFolders.map((name) => (
            <button
              key={name}
              data-testid={`training-folder-${name}`}
              onClick={() => setFolder(name)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition-all ${folder === name ? "bg-black text-white border-black" : "bg-white text-slate-600 border-slate-300 hover:border-slate-400"}`}
            >{name} <span className="opacity-60">{countFor(name)}</span></button>
          ))}
        </div>
      )}

      {items.length === 0 ? <Empty icon={GraduationCap} text="No training records yet. Log driver courses and upload certificates." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {shown.map((t) => (
            <div key={t.id} data-testid="training-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{t.category}</p>
                  <h3 className="font-heading font-bold text-lg text-slate-900 truncate">{t.course_name}</h3>
                  <p className="text-xs text-slate-500 mt-0.5">{t.driver_name || "Unassigned"}{t.provider && ` · ${t.provider}`}</p>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button data-testid="edit-training-button" onClick={() => openEdit(t)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-training-button" onClick={() => remove(t.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">Expiry</p>
                  <p className="text-sm font-semibold text-slate-700">{t.expiry_date || "—"}{t.days_left != null && <span className="text-slate-400 font-normal"> · {t.days_left < 0 ? `${Math.abs(t.days_left)}d overdue` : `${t.days_left}d`}</span>}</p>
                </div>
                <StatusBadge status={t.status} />
              </div>
              <AttachmentThumbs attachments={t.attachments} />
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Training Record" : "Add Training Record"}</DialogTitle><DialogDescription className="sr-only">Driver training record form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Driver">
              <Select value={form.driver_id || undefined} onValueChange={pickDriver}>
                <SelectTrigger data-testid="training-driver-select"><SelectValue placeholder="Select driver" /></SelectTrigger>
                <SelectContent>{drivers.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Course Name *"><Input data-testid="training-course" required value={form.course_name} onChange={(e) => setForm({ ...form, course_name: e.target.value })} placeholder="Driver CPC Module 3" /></Field>
              <Field label="Category">
                <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                  <SelectTrigger data-testid="training-category-select"><SelectValue /></SelectTrigger>
                  <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Completed *"><Input data-testid="training-completed" type="date" required value={form.completed_date} onChange={(e) => setForm({ ...form, completed_date: e.target.value })} /></Field>
              <Field label="Expiry"><Input data-testid="training-expiry" type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Provider"><Input data-testid="training-provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} placeholder="Training company" /></Field>
              <Field label="CPC Hours"><Input data-testid="training-hours" type="number" step="0.5" value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} placeholder="7" /></Field>
            </div>
            <Field label="Certificate"><FileUpload testid="training-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-training-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Record"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Training() {
  return <TrainingPanel />;
}
