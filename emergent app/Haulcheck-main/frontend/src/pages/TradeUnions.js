import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Trash2, Pencil, Users, Mail, Phone } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";

const empty = { union_name: "", branch: "", rep_name: "", rep_role: "", contact_email: "", contact_phone: "", membership_number: "", agreement_ref: "", notes: "", attachments: [] };

export function TradeUnionsPanel() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => setItems((await api.get("/trade-unions")).data);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (t) => { setForm({ ...empty, ...t, attachments: t.attachments || [] }); setEditId(t.id); setOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    if (!form.union_name) { toast.error("Enter a union name"); return; }
    try {
      if (editId) await api.put(`/trade-unions/${editId}`, form);
      else await api.post("/trade-unions", form);
      toast.success(editId ? "Trade union updated" : "Trade union added");
      setOpen(false); load();
    } catch { toast.error("Could not save"); }
  };
  const remove = async (id) => { await api.delete(`/trade-unions/${id}`); toast.success("Removed"); load(); };

  return (
    <div data-testid="trade-unions-page">
      <div className="flex justify-between items-center mb-4">
        <p className="text-sm text-slate-500">Recognised unions, reps & collective agreements.</p>
        <Button data-testid="add-union-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Trade Union</Button>
      </div>

      {items.length === 0 ? <Empty icon={Users} text="No trade union details yet. Add your recognised union(s) and rep contacts." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((t) => (
            <div key={t.id} data-testid="union-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <h3 className="font-heading font-bold text-lg text-slate-900 truncate">{t.union_name}</h3>
                  {t.branch && <p className="text-xs text-slate-500">{t.branch}</p>}
                </div>
                <div className="flex gap-1 shrink-0">
                  <button data-testid="edit-union-button" onClick={() => openEdit(t)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-union-button" onClick={() => remove(t.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              {(t.rep_name || t.rep_role) && <p className="text-sm text-slate-700 mt-3 font-medium">{t.rep_name}{t.rep_role ? ` · ${t.rep_role}` : ""}</p>}
              <div className="mt-2 space-y-1">
                {t.contact_email && <a href={`mailto:${t.contact_email}`} className="flex items-center gap-1.5 text-xs text-blue-600 hover:underline"><Mail size={12} /> {t.contact_email}</a>}
                {t.contact_phone && <a href={`tel:${t.contact_phone}`} className="flex items-center gap-1.5 text-xs text-slate-600 hover:underline"><Phone size={12} /> {t.contact_phone}</a>}
              </div>
              {(t.membership_number || t.agreement_ref) && (
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  {t.membership_number && <span>Membership: <b className="text-slate-700">{t.membership_number}</b></span>}
                  {t.agreement_ref && <span>Agreement: <b className="text-slate-700">{t.agreement_ref}</b></span>}
                </div>
              )}
              {t.notes && <p className="text-xs text-slate-500 mt-2 line-clamp-2">{t.notes}</p>}
              <AttachmentThumbs attachments={t.attachments} />
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Trade Union" : "Add Trade Union"}</DialogTitle><DialogDescription className="sr-only">Trade union details form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Union name *"><Input data-testid="union-name" required value={form.union_name} onChange={(e) => setForm({ ...form, union_name: e.target.value })} placeholder="e.g. Unite / SIPTU" /></Field>
              <Field label="Branch"><Input data-testid="union-branch" value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Rep name"><Input data-testid="union-rep-name" value={form.rep_name} onChange={(e) => setForm({ ...form, rep_name: e.target.value })} /></Field>
              <Field label="Rep role"><Input data-testid="union-rep-role" value={form.rep_role} onChange={(e) => setForm({ ...form, rep_role: e.target.value })} placeholder="Shop steward / official" /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Contact email"><Input data-testid="union-email" type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} /></Field>
              <Field label="Contact phone"><Input data-testid="union-phone" value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Membership no."><Input data-testid="union-membership" value={form.membership_number} onChange={(e) => setForm({ ...form, membership_number: e.target.value })} /></Field>
              <Field label="Agreement ref"><Input data-testid="union-agreement" value={form.agreement_ref} onChange={(e) => setForm({ ...form, agreement_ref: e.target.value })} /></Field>
            </div>
            <Field label="Notes"><Input data-testid="union-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
            <Field label="Agreement / documents"><FileUpload testid="union-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-union-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Trade Union"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function TradeUnions() {
  return <TradeUnionsPanel />;
}
