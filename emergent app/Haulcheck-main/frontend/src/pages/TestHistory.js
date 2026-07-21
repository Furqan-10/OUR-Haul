import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Gavel } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";

const today = () => new Date().toISOString().slice(0, 10);
const empty = { vehicle_reg: "", event_type: "annual_test", event_date: today(), result: "pass", reference: "", notes: "", attachments: [] };
const RESULT_TONE = { pass: "text-green-700 bg-green-50", fail: "text-red-700 bg-red-50", pg9: "text-red-700 bg-red-50", advisory: "text-amber-700 bg-amber-50", cleared: "text-green-700 bg-green-50" };

export function TestHistoryPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [assets, setAssets] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);

  const load = async () => {
    const [h, v, t] = await Promise.all([api.get("/test-history"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(h.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!form.vehicle_reg) return toast.error("Select a vehicle");
    try {
      await api.post("/test-history", { ...form, event_date: form.event_date || null });
      toast.success("Record added");
      setOpen(false); setForm(empty); load();
    } catch { toast.error("Could not save record"); }
  };
  const remove = async (id) => { await api.delete(`/test-history/${id}`); load(); };

  return (
    <div data-testid="test-history-page">
      <div className="flex justify-end mb-4">
        <Button data-testid="add-test-history-button" onClick={() => { setForm(empty); setOpen(true); }} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Test / Prohibition</Button>
      </div>
      {items.length === 0 ? <Empty icon={Gavel} text="No annual test or prohibition (PG9) history yet." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((a) => (
            <div key={a.id} className="bg-white border border-slate-200 rounded-md p-5" data-testid="test-history-card">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-heading font-bold text-lg tracking-tight">{a.vehicle_reg}</h3>
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${RESULT_TONE[a.result] || RESULT_TONE.pass}`}>{a.result}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{a.event_type === "annual_test" ? "Annual test" : "Prohibition / PG9"} · {a.event_date || "—"}{a.reference ? ` · ${a.reference}` : ""}</p>
                </div>
                <button data-testid="delete-test-history-button" onClick={() => remove(a.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
              </div>
              {a.notes && <p className="text-sm text-slate-500 mt-1">{a.notes}</p>}
              {a.attachments?.length > 0 && <div className="mt-3"><AttachmentThumbs attachments={a.attachments} /></div>}
            </div>
          ))}
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Add Test / Prohibition Record</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="th-reg"><SelectValue placeholder={assets.length ? "Select vehicle" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Type">
              <Select value={form.event_type} onValueChange={(v) => setForm({ ...form, event_type: v })}>
                <SelectTrigger data-testid="th-type"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="annual_test">Annual test</SelectItem><SelectItem value="prohibition">Prohibition / PG9</SelectItem></SelectContent>
              </Select>
            </Field>
            <Field label="Date"><Input data-testid="th-date" type="date" value={form.event_date || ""} onChange={(e) => setForm({ ...form, event_date: e.target.value })} /></Field>
            <Field label="Result">
              <Select value={form.result} onValueChange={(v) => setForm({ ...form, result: v })}>
                <SelectTrigger data-testid="th-result"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="pass">Pass</SelectItem>
                  <SelectItem value="fail">Fail</SelectItem>
                  <SelectItem value="pg9">PG9 issued</SelectItem>
                  <SelectItem value="advisory">Advisory</SelectItem>
                  <SelectItem value="cleared">Cleared</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <div className="col-span-2"><Field label="Reference"><Input data-testid="th-ref" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="Test / prohibition number" /></Field></div>
            <div className="col-span-2"><Field label="Notes"><Textarea data-testid="th-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field></div>
            <div className="col-span-2"><Field label="Attachments"><FileUpload attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field></div>
          </div>
          <DialogFooter><Button data-testid="save-test-history-button" onClick={save} className="bg-black hover:bg-slate-800">Save Record</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function TestHistory() { return <TestHistoryPanel />; }
