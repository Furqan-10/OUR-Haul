import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { AlertOctagon, ExternalLink, Plus, Trash2, Check, RotateCcw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

const OFFICIAL = {
  UK: { label: "DVSA vehicle recall check", url: "https://www.check-vehicle-recalls.service.gov.uk/" },
  IE: { label: "RSA vehicle recalls", url: "https://www.rsa.ie/services/vehicle-standards/vehicle-recalls" },
};
const emptyForm = { vehicle_reg: "", title: "", reference: "", issued_date: new Date().toISOString().slice(0, 10), notes: "" };

export function RecallCard() {
  const { user } = useAuth();
  const off = OFFICIAL[user?.region === "IE" ? "IE" : "UK"];
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const load = async () => { try { const { data } = await api.get("/recalls"); setItems(data); } catch { /* noop */ } };
  useEffect(() => { load(); }, []);

  const outstanding = items.filter((r) => r.status !== "actioned");

  const add = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) return toast.error("Enter a recall title");
    try { await api.post("/recalls", form); toast.success("Recall logged"); setForm(emptyForm); load(); }
    catch { toast.error("Could not save recall"); }
  };
  const toggle = async (r) => {
    const status = r.status === "actioned" ? "outstanding" : "actioned";
    await api.put(`/recalls/${r.id}`, { ...r, status, actioned_date: status === "actioned" ? new Date().toISOString().slice(0, 10) : null });
    load();
  };
  const remove = async (id) => { await api.delete(`/recalls/${id}`); load(); };

  return (
    <>
      <div data-testid="recall-card" className="bg-white border border-slate-200 rounded-md p-5 mb-6 animate-in-up">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${outstanding.length ? "bg-red-100 text-red-600" : "bg-green-100 text-green-600"}`}>
              {outstanding.length ? <AlertOctagon size={22} /> : <ShieldCheck size={22} />}
            </div>
            <div className="min-w-0">
              <h3 className="font-heading font-bold tracking-tight">Vehicle Safety Recalls</h3>
              <p className="text-sm text-slate-500">
                {outstanding.length
                  ? <span data-testid="recall-outstanding" className="text-red-600 font-semibold">{outstanding.length} outstanding recall{outstanding.length !== 1 && "s"} to action</span>
                  : <span data-testid="recall-outstanding">No outstanding recalls logged</span>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a data-testid="recall-official-link" href={off.url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-md border border-slate-300 hover:border-slate-900 transition-colors">
              <ExternalLink size={15} /> {off.label}
            </a>
            <Button data-testid="recall-manage-button" onClick={() => setOpen(true)} className="bg-black hover:bg-slate-800 rounded-md">Manage</Button>
          </div>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[92vh] overflow-y-auto" data-testid="recall-dialog">
          <DialogHeader><DialogTitle className="font-heading">Recall register</DialogTitle>
            <DialogDescription>Log manufacturer/DVSA/RSA recalls and track them until the work is done.</DialogDescription>
          </DialogHeader>

          <form onSubmit={add} className="grid grid-cols-2 gap-3 border-b border-slate-100 pb-4">
            <Input data-testid="recall-vehicle" value={form.vehicle_reg} onChange={(e) => setForm({ ...form, vehicle_reg: e.target.value })} placeholder="Vehicle reg / model" />
            <Input data-testid="recall-ref" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="Recall ref (optional)" />
            <Input data-testid="recall-title" className="col-span-2" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Recall title / fault *" />
            <Input data-testid="recall-date" type="date" value={form.issued_date} onChange={(e) => setForm({ ...form, issued_date: e.target.value })} />
            <Button data-testid="recall-add-button" type="submit" className="bg-slate-900 hover:bg-slate-800 gap-1.5"><Plus size={15} /> Add</Button>
            <Textarea data-testid="recall-notes" className="col-span-2" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Notes (optional)" rows={2} />
          </form>

          <div className="space-y-2 mt-3">
            {items.length === 0 && <p className="text-sm text-slate-400 text-center py-6">No recalls logged yet.</p>}
            {items.map((r) => (
              <div key={r.id} data-testid="recall-row" className="flex items-center gap-3 border border-slate-100 rounded-md px-3 py-2.5">
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full shrink-0 ${r.status === "actioned" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>{r.status === "actioned" ? "Sorted" : "Outstanding"}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-900 truncate">{r.title}</p>
                  <p className="text-xs text-slate-400 truncate">
                    {[r.vehicle_reg, r.reference, r.issued_date].filter(Boolean).join(" · ") || "—"}
                    {r.status === "actioned" && r.actioned_date ? ` · sorted ${r.actioned_date}` : ""}
                  </p>
                </div>
                <button data-testid="recall-toggle" onClick={() => toggle(r)}
                  className={`text-xs font-semibold rounded-md px-2.5 py-1.5 shrink-0 inline-flex items-center gap-1 transition-colors ${r.status === "actioned" ? "text-slate-500 hover:bg-slate-100" : "bg-green-600 text-white hover:bg-green-700"}`}>
                  {r.status === "actioned" ? <><RotateCcw size={13} /> Reopen</> : <><Check size={13} /> Mark sorted</>}
                </button>
                <button data-testid="recall-delete" onClick={() => remove(r.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
