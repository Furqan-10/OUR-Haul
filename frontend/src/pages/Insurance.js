import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { getTerms } from "@/lib/terms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, ShieldCheck, Sparkles, Plus, Loader2, Upload, CheckCircle2, AlertTriangle, FolderInput } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";

const TYPES = [
  "Goods in Transit (GIT)",
  "Motor — Truck",
  "Motor — Trailer",
  "Green Card",
  "Public Liability (PL)",
  "Employers' Liability (EL)",
  "Other",
];
const empty = { policy_type: "Motor — Truck", insurer: "", policy_number: "", start_date: "", expiry_date: "", cover_amount: "", notes: "", attachments: [] };

export default function Insurance() {
  return <InsurancePanel />;
}

export function InsurancePanel({ embedded = false }) {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);

  const [aiOpen, setAiOpen] = useState(false);
  const [aiFiles, setAiFiles] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResults, setAiResults] = useState(null);
  const [folder, setFolder] = useState("All");
  const [sorting, setSorting] = useState(false);

  const sortLoose = async () => {
    setSorting(true);
    try {
      const r = await api.post("/insurance/reclassify");
      if (r.data.moved > 0) toast.success(`Sorted ${r.data.moved} loose doc(s) into their correct folders`);
      else toast.info("No loose docs could be auto-sorted");
      load();
    } catch { toast.error("Could not sort loose docs"); }
    finally { setSorting(false); }
  };

  const FOLDERS = [["All", "All"], ["Motor — Truck", "Truck"], ["Motor — Trailer", "Trailer"], ["Goods in Transit (GIT)", "GIT"], ["Public Liability (PL)", "PL"], ["Employers' Liability (EL)", "EL"], ["Green Card", "Green Card"], ["Other", "Other"]];
  const shown = folder === "All" ? items : items.filter((i) => i.policy_type === folder);
  const countFor = (val) => (val === "All" ? items.length : items.filter((i) => i.policy_type === val).length);

  const load = async () => setItems((await api.get("/insurance")).data);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (p) => {
    setForm({ ...empty, ...p, start_date: p.start_date || "", expiry_date: p.expiry_date || "", attachments: p.attachments || [] });
    setEditId(p.id); setOpen(true);
  };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, start_date: form.start_date || null, expiry_date: form.expiry_date || null, needs_review: false };
    try {
      if (editId) await api.put(`/insurance/${editId}`, payload);
      else await api.post("/insurance", payload);
      toast.success(editId ? "Policy updated" : "Policy added");
      setOpen(false); load();
    } catch { toast.error("Could not save policy"); }
  };
  const remove = async (id) => { await api.delete(`/insurance/${id}`); toast.success("Policy removed"); load(); };

  const openAi = () => { setAiFiles(null); setAiResults(null); setAiOpen(true); };
  const runAiImport = async (e) => {
    e.preventDefault();
    if (!aiFiles?.length) { toast.error("Choose one or more files"); return; }
    setAiBusy(true);
    setAiResults(null);
    try {
      const fd = new FormData();
      Array.from(aiFiles).forEach((f) => fd.append("files", f));
      const res = await api.post("/insurance/ai-import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setAiResults(res.data.created);
      toast.success(`AI imported ${res.data.count} polic${res.data.count === 1 ? "y" : "ies"}`);
      load();
    } catch {
      toast.error("AI import failed");
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <div data-testid="insurance-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        {!embedded ? (
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance · {terms.authority}</p>
            <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Insurance</h1>
            <p className="text-slate-500 text-sm mt-1">GIT, motor, green card, PL & EL policy tracking</p>
          </div>
        ) : <div />}
        <div className="flex gap-2">
          <Button data-testid="sort-loose-button" onClick={sortLoose} disabled={sorting} variant="outline" className="border-slate-300 rounded-md gap-2">
            {sorting ? <Loader2 size={16} className="animate-spin" /> : <FolderInput size={16} />} Sort loose docs
          </Button>
          <Button data-testid="ai-import-button" onClick={openAi} variant="outline" className="border-slate-300 rounded-md gap-2"><Sparkles size={16} /> AI Import</Button>
          <Button data-testid="add-insurance-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Plus size={16} /> Add Policy</Button>
        </div>
      </div>

      {items.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6" data-testid="insurance-folders">
          {FOLDERS.map(([val, label]) => (
            <button
              key={val}
              data-testid={`folder-${label}`}
              onClick={() => setFolder(val)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition-all ${folder === val ? "bg-black text-white border-black" : "bg-white text-slate-600 border-slate-300 hover:border-slate-400"}`}
            >{label} <span className="opacity-60">{countFor(val)}</span></button>
          ))}
        </div>
      )}

      {items.length === 0 ? <Empty icon={ShieldCheck} text="No insurance policies yet. Add one manually or use AI Import to upload them all at once." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {shown.map((p) => (
            <div key={p.id} data-testid="insurance-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{p.policy_type}</p>
                    {p.needs_review && <span data-testid="review-badge" className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-yellow-100 text-yellow-800"><AlertTriangle size={10} /> Review</span>}
                    {p.ai_extracted && <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700"><Sparkles size={10} /> AI</span>}
                  </div>
                  <h3 className="font-heading font-bold text-lg text-slate-900 truncate">{p.insurer || "Insurer TBC"}</h3>
                  {p.policy_number && <p className="text-xs text-slate-500 mt-0.5">Policy: {p.policy_number}</p>}
                  {p.cover_amount && <p className="text-xs text-slate-500">Cover: {p.cover_amount}</p>}
                </div>
                <div className="flex gap-1 shrink-0">
                  <button data-testid="edit-insurance-button" onClick={() => openEdit(p)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-insurance-button" onClick={() => remove(p.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">Renewal / expiry</p>
                  <p className="text-sm font-semibold text-slate-700">{p.expiry_date || "—"}{p.days_left != null && <span className="text-slate-400 font-normal"> · {p.days_left < 0 ? `${Math.abs(p.days_left)}d overdue` : `${p.days_left}d`}</span>}</p>
                </div>
                <StatusBadge status={p.status} />
              </div>
              <AttachmentThumbs attachments={p.attachments} />
            </div>
          ))}
        </div>
      )}

      {/* Manual add / edit */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Policy" : "Add Insurance Policy"}</DialogTitle><DialogDescription className="sr-only">Insurance policy form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Policy Type">
              <Select value={form.policy_type} onValueChange={(v) => setForm({ ...form, policy_type: v })}>
                <SelectTrigger data-testid="ins-type-select"><SelectValue /></SelectTrigger>
                <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Insurer"><Input data-testid="ins-insurer" value={form.insurer} onChange={(e) => setForm({ ...form, insurer: e.target.value })} placeholder="e.g. Aviva" /></Field>
              <Field label="Policy Number"><Input data-testid="ins-number" value={form.policy_number} onChange={(e) => setForm({ ...form, policy_number: e.target.value })} placeholder="POL-123456" /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Start Date"><Input data-testid="ins-start" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></Field>
              <Field label="Expiry / Renewal *"><Input data-testid="ins-expiry" type="date" required value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></Field>
            </div>
            <Field label="Cover Amount"><Input data-testid="ins-cover" value={form.cover_amount} onChange={(e) => setForm({ ...form, cover_amount: e.target.value })} placeholder={`e.g. ${terms.currency}250,000`} /></Field>
            <Field label="Certificate / Schedule"><FileUpload testid="ins-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <DialogFooter><Button data-testid="save-insurance-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Policy"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* AI bulk import */}
      <Dialog open={aiOpen} onOpenChange={setAiOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2"><Sparkles size={18} /> AI Insurance Import</DialogTitle>
            <DialogDescription>Upload all your insurance certificates (PDF or photo) at once. AI reads each one, detects the policy type, insurer, number and expiry, and creates the records for you to review.</DialogDescription>
          </DialogHeader>
          <form onSubmit={runAiImport} className="space-y-4">
            <label className="flex items-center justify-center gap-2 border-2 border-dashed border-slate-300 rounded-md py-6 px-3 text-sm text-slate-500 cursor-pointer hover:border-slate-400 hover:bg-slate-50 transition-colors">
              <Upload size={18} />
              <span>{aiFiles?.length ? `${aiFiles.length} file(s) selected` : "Choose insurance documents (PDF / image)"}</span>
              <input data-testid="ai-import-input" type="file" multiple accept="image/*,application/pdf" className="hidden" onChange={(e) => setAiFiles(e.target.files)} disabled={aiBusy} />
            </label>

            {aiResults && (
              <div className="space-y-2" data-testid="ai-import-results">
                {aiResults.map((r) => (
                  <div key={r.id} className="flex items-center justify-between border border-slate-100 rounded-md p-3 text-sm">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-900 truncate">{r.insurer || r.filename}</p>
                      <p className="text-xs text-slate-500">{r.policy_type}{r.expiry_date && ` · exp ${r.expiry_date}`}</p>
                    </div>
                    {r.needs_review
                      ? <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-800"><AlertTriangle size={11} /> Review</span>
                      : <CheckCircle2 size={16} className="text-green-600 shrink-0" />}
                  </div>
                ))}
              </div>
            )}

            <DialogFooter>
              {aiResults ? (
                <Button type="button" data-testid="ai-import-done" onClick={() => setAiOpen(false)} className="bg-black hover:bg-slate-800">Done</Button>
              ) : (
                <Button type="submit" data-testid="ai-import-run" disabled={aiBusy || !aiFiles?.length} className="bg-black hover:bg-slate-800 gap-2">
                  {aiBusy ? <><Loader2 size={15} className="animate-spin" /> Reading documents…</> : <><Sparkles size={15} /> Import with AI</>}
                </Button>
              )}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
