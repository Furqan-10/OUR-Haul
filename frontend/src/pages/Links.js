import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, Link2, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Empty } from "@/pages/Vehicles";

const CATEGORIES = ["Government / Authority", "Legislation", "Portal / Login", "Training", "Supplier", "General"];
const empty = { title: "", url: "", category: "General", notes: "" };

export function LinksPanel() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const load = async () => setItems((await api.get("/links")).data);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (l) => { setForm({ ...empty, ...l }); setEditId(l.id); setOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    try {
      if (editId) await api.put(`/links/${editId}`, form);
      else await api.post("/links", form);
      toast.success(editId ? "Link updated" : "Link added");
      setOpen(false); load();
    } catch { toast.error("Could not save link"); }
  };
  const remove = async (id) => { await api.delete(`/links/${id}`); toast.success("Link removed"); load(); };
  const seed = async () => {
    try {
      const { data } = await api.post("/links/seed");
      toast.success(data.added ? `Added ${data.added} starter links` : "Starter links already added");
      load();
    } catch { toast.error("Could not add starter links"); }
  };

  const groups = CATEGORIES.filter((c) => items.some((l) => l.category === c));

  return (
    <div data-testid="links-page">
      <div className="flex justify-between items-center mb-4">
        <p className="text-sm text-slate-500">Handy reference websites — DVSA/RSA, legislation, portals & suppliers.</p>
        <div className="flex gap-2">
          <Button data-testid="seed-links-button" onClick={seed} variant="outline" className="rounded-md border-slate-300">Add starter links</Button>
          <Button data-testid="add-link-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Link</Button>
        </div>
      </div>

      {items.length === 0 ? <Empty icon={Link2} text="No links yet. Save useful websites for quick reference." /> : (
        <div className="space-y-6">
          {groups.map((cat) => (
            <div key={cat}>
              <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold mb-2">{cat}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {items.filter((l) => l.category === cat).map((l) => (
                  <div key={l.id} data-testid="link-card" className="group bg-white border border-slate-200 rounded-md p-4 hover:border-slate-300 hover:shadow-sm transition-all duration-200 animate-in-up">
                    <div className="flex items-start justify-between gap-2">
                      <a data-testid="open-link-button" href={l.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1">
                        <p className="font-heading font-bold text-sm text-slate-900 truncate flex items-center gap-1.5">{l.title} <ExternalLink size={12} className="text-slate-300 group-hover:text-slate-600 shrink-0" /></p>
                        <p className="text-xs text-blue-600 truncate">{l.url}</p>
                        {l.notes && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{l.notes}</p>}
                      </a>
                      <div className="flex gap-1 shrink-0">
                        <button data-testid="edit-link-button" onClick={() => openEdit(l)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={14} /></button>
                        <button data-testid="delete-link-button" onClick={() => remove(l.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Link" : "Add Link"}</DialogTitle><DialogDescription className="sr-only">Reference website link form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <div><label className="text-sm font-medium mb-1.5 block">Title *</label><Input data-testid="link-title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. DVSA operator licensing" /></div>
            <div><label className="text-sm font-medium mb-1.5 block">URL *</label><Input data-testid="link-url" required value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://www.gov.uk/…" /></div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">Category</label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger data-testid="link-category"><SelectValue /></SelectTrigger>
                <SelectContent>{CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><label className="text-sm font-medium mb-1.5 block">Notes</label><Input data-testid="link-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="What's this for?" /></div>
            <DialogFooter><Button data-testid="save-link-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Link"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Links() {
  return <LinksPanel />;
}
