import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash2, Pencil, Container, FileDown } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { getTerms } from "@/lib/terms";
import { downloadPdf } from "@/lib/download";

const TYPES = ["Curtainsider", "Flatbed", "Refrigerated", "Tanker", "Skeletal", "Box", "Low Loader", "Other"];
const empty = { trailer_number: "", type: "Curtainsider", mot_due: "", service_due: "", vor: false, vor_reason: "", notes: "" };

const LocalField = ({ label, children }) => (<div><Label className="mb-1.5 block">{label}</Label>{children}</div>);
const LocalEmpty = ({ text }) => (
  <div className="bg-white border border-dashed border-slate-300 rounded-md p-14 text-center text-slate-500 flex flex-col items-center gap-3 animate-in-up">
    <Container size={36} className="text-slate-300" />
    <p className="text-sm max-w-xs">{text}</p>
  </div>
);

export function TrailersPanel() {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => setItems((await api.get("/trailers")).data);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (t) => { setForm({ ...empty, ...t, mot_due: t.mot_due || "", service_due: t.service_due || "" }); setEditId(t.id); setOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, mot_due: form.mot_due || null, service_due: form.service_due || null };
    try {
      if (editId) await api.put(`/trailers/${editId}`, payload);
      else await api.post("/trailers", payload);
      toast.success(editId ? "Trailer updated" : "Trailer added");
      setOpen(false); load();
    } catch { toast.error("Could not save trailer"); }
  };
  const remove = async (id) => { await api.delete(`/trailers/${id}`); toast.success("Trailer removed"); load(); };

  return (
    <div>
      <div className="flex justify-end gap-2 mb-4">
        <Button data-testid="download-trailers-pdf" variant="outline" onClick={() => downloadPdf("/reports/trailers", "trailers-report.pdf")} className="rounded-md gap-2 border-slate-300"><FileDown size={16} /> Download PDF</Button>
        <Button data-testid="add-trailer-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Plus size={16} /> Add Trailer</Button>
      </div>
      {items.length === 0 ? <LocalEmpty text="No trailers yet. Add trailers to track annual tests and servicing." /> : (
        <div className="bg-white border border-slate-200 rounded-md overflow-hidden overflow-x-auto animate-in-up">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr className="text-xs uppercase tracking-wider text-slate-500">
                <th className="px-5 py-3 font-semibold">Trailer No.</th>
                <th className="px-5 py-3 font-semibold">Type</th>
                <th className="px-5 py-3 font-semibold">{terms.trailerTest}</th>
                <th className="px-5 py-3 font-semibold">Service</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((t) => (
                <tr key={t.id} data-testid="trailer-row" className="hover:bg-slate-50 transition-colors">
                  <td className="px-5 py-3 font-bold text-slate-900">
                    <div className="flex items-center gap-2">
                      {t.trailer_number}
                      {t.vor && <span data-testid="trailer-vor-badge" className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-red-100 text-red-700" title={t.vor_reason || "Off road"}>VOR</span>}
                    </div>
                  </td>
                  <td className="px-5 py-3 text-slate-600">{t.type}</td>
                  <td className="px-5 py-3"><div className="flex flex-col gap-1 items-start"><StatusBadge status={t.mot_status} /><span className="text-xs text-slate-400">{t.mot_due || "—"}</span></div></td>
                  <td className="px-5 py-3"><div className="flex flex-col gap-1 items-start"><StatusBadge status={t.service_status} /><span className="text-xs text-slate-400">{t.service_due || "—"}</span></div></td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    <button data-testid="edit-trailer-button" onClick={() => openEdit(t)} className="text-slate-400 hover:text-slate-900 p-1.5"><Pencil size={16} /></button>
                    <button data-testid="delete-trailer-button" onClick={() => remove(t.id)} className="text-slate-400 hover:text-red-600 p-1.5"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Trailer" : "Add Trailer"}</DialogTitle><DialogDescription className="sr-only">Trailer details form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <LocalField label="Trailer Number *"><Input data-testid="trl-number" required value={form.trailer_number} onChange={(e) => setForm({ ...form, trailer_number: e.target.value })} placeholder="TRL-001" /></LocalField>
            <LocalField label="Type">
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="trl-type-select"><SelectValue /></SelectTrigger>
                <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
              </Select>
            </LocalField>
            <div className="grid grid-cols-2 gap-4">
              <LocalField label={`${terms.trailerTest} Due`}><Input data-testid="trl-mot" type="date" value={form.mot_due} onChange={(e) => setForm({ ...form, mot_due: e.target.value })} /></LocalField>
              <LocalField label="Service Due"><Input data-testid="trl-service" type="date" value={form.service_due} onChange={(e) => setForm({ ...form, service_due: e.target.value })} /></LocalField>
            </div>
            <div className="rounded-md border border-slate-200 p-3">
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input data-testid="trl-vor" type="checkbox" checked={!!form.vor} onChange={(e) => setForm({ ...form, vor: e.target.checked })} className="h-4 w-4 rounded border-slate-300 accent-red-600" />
                <span className="text-sm font-semibold text-slate-800">Trailer Off Road (VOR)</span>
              </label>
              {form.vor && (
                <Input data-testid="trl-vor-reason" value={form.vor_reason} onChange={(e) => setForm({ ...form, vor_reason: e.target.value })} placeholder="Reason (e.g. awaiting parts)" className="mt-3" />
              )}
              <p className="text-xs text-slate-400 mt-2">Off-road trailers are flagged and excluded from compliance due/overdue alerts.</p>
            </div>
            <DialogFooter><Button data-testid="save-trailer-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Trailer"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
