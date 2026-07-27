import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Wrench, Trash2, Pencil, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload } from "@/components/FileUpload";

const CATEGORIES = ["Major repair", "Engine / Driveline", "Bodywork / Chassis", "Electrical", "Accident damage", "Brakes / Suspension", "Modification", "Warranty work", "Other"];
const empty = { vehicle_reg: "", repair_date: new Date().toISOString().slice(0, 10), category: "Major repair", description: "", provider: "", cost: "", odometer: "", notes: "", attachments: [] };

export function RepairsPanel() {
  const [items, setItems] = useState([]);
  const [assets, setAssets] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => {
    const [r, v, t] = await Promise.all([api.get("/repairs"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(r.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (r) => {
    setForm({ ...empty, ...r, cost: r.cost || "", odometer: r.odometer || "", repair_date: r.repair_date || "", attachments: r.attachments || [] });
    setEditId(r.id); setOpen(true);
  };

  const save = async (e) => {
    e.preventDefault();
    if (!form.vehicle_reg) return toast.error("Select a vehicle");
    const payload = { ...form, cost: parseFloat(form.cost) || 0, odometer: parseFloat(form.odometer) || 0, repair_date: form.repair_date || null };
    try {
      if (editId) await api.put(`/repairs/${editId}`, payload);
      else await api.post("/repairs", payload);
      toast.success(editId ? "Repair updated" : "Repair logged");
      setOpen(false); load();
    } catch { toast.error("Could not save repair"); }
  };
  const remove = async (id) => { await api.delete(`/repairs/${id}`); toast.success("Repair removed"); load(); };

  return (
    <div data-testid="repairs-page">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-500">Log major repairs, accident damage and other significant work — separate from routine servicing.</p>
        <Button data-testid="add-repair-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Wrench size={16} /> Log Work</Button>
      </div>

      {items.length === 0 ? (
        <Empty icon={Wrench} text="No major work logged yet. Record repairs, accident damage or modifications here." />
      ) : (
        <div className="bg-white border border-slate-200 rounded-md overflow-hidden overflow-x-auto animate-in-up">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr className="text-xs uppercase tracking-wider text-slate-500">
                <th className="px-5 py-3 font-semibold">Date</th>
                <th className="px-5 py-3 font-semibold">Vehicle</th>
                <th className="px-5 py-3 font-semibold">Category</th>
                <th className="px-5 py-3 font-semibold">Description</th>
                <th className="px-5 py-3 font-semibold">Supplier</th>
                <th className="px-5 py-3 font-semibold">Cost</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((r) => (
                <tr key={r.id} data-testid="repair-row" className="hover:bg-slate-50 transition-colors">
                  <td className="px-5 py-3 text-slate-500 whitespace-nowrap">{r.repair_date || "—"}</td>
                  <td className="px-5 py-3 font-bold text-slate-900">{r.vehicle_reg}</td>
                  <td className="px-5 py-3"><span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">{r.category}</span></td>
                  <td className="px-5 py-3 text-slate-600 max-w-xs">
                    <span className="line-clamp-2">{r.description || "—"}</span>
                    {(r.attachments || []).length > 0 && <span className="inline-flex items-center gap-1 text-[11px] text-slate-400 mt-0.5"><Paperclip size={11} /> {r.attachments.length} file(s)</span>}
                  </td>
                  <td className="px-5 py-3 text-slate-600">{r.provider || "—"}</td>
                  <td className="px-5 py-3 text-slate-600 whitespace-nowrap">{r.cost ? `£${Number(r.cost).toLocaleString()}` : "—"}</td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    <button data-testid="edit-repair-button" onClick={() => openEdit(r)} className="text-slate-400 hover:text-slate-900 p-1.5"><Pencil size={16} /></button>
                    <button data-testid="delete-repair-button" onClick={() => remove(r.id)} className="text-slate-400 hover:text-red-600 p-1.5"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Work Record" : "Log Major Work"}</DialogTitle>
            <DialogDescription className="sr-only">Major work / repair record form</DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Vehicle *">
                <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                  <SelectTrigger data-testid="repair-reg"><SelectValue placeholder={assets.length ? "Select" : "Add a vehicle first"} /></SelectTrigger>
                  <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Date"><Input data-testid="repair-date" type="date" value={form.repair_date} onChange={(e) => setForm({ ...form, repair_date: e.target.value })} /></Field>
            </div>
            <Field label="Category">
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="repair-category"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Description of work *"><Textarea data-testid="repair-description" required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="e.g. Replaced nearside front brake calliper and discs following roadside defect" /></Field>
            <div className="grid grid-cols-3 gap-4">
              <Field label="Supplier"><Input data-testid="repair-provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} placeholder="Garage / 3rd party" /></Field>
              <Field label="Cost (£)"><Input data-testid="repair-cost" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></Field>
              <Field label="Odometer"><Input data-testid="repair-odometer" type="number" value={form.odometer} onChange={(e) => setForm({ ...form, odometer: e.target.value })} /></Field>
            </div>
            <Field label="Notes"><Textarea data-testid="repair-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Optional" /></Field>
            <div>
              <p className="text-sm font-medium text-slate-700 mb-1.5">Invoices / evidence</p>
              <FileUpload attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} />
            </div>
            <DialogFooter><Button data-testid="save-repair-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Log Work"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Repairs() { return <RepairsPanel />; }
