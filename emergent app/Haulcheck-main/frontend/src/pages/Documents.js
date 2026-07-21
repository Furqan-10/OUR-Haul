import { useEffect, useState } from "react";
import api, { API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Trash2, Pencil, FolderCheck, Sparkles, FileSignature, Loader2, Eye, RefreshCw, Link2 } from "lucide-react";
import { toast } from "sonner";
import { Header, Field, Empty } from "@/pages/Vehicles";
import { FileUpload, AttachmentThumbs } from "@/components/FileUpload";

const TYPES = ["Operator Licence", "Insurance", "Audit Report", "Wheel Security Check", "Motor Insurance DB", "Health & Safety", "Attestation Record", "Indoctrination Document", "Driver Infringement", "Infringement Report", "Warning Letter", "Adhoc Note", "Other"];
const LETTER_TEMPLATES = ["Warning Letter", "Driver Infringement", "Infringement Report", "Attestation Record", "Indoctrination Document", "Adhoc Note", "Employment Offer Letter", "Contract of Employment", "Reference Letter", "Disciplinary Invite", "Disciplinary Outcome", "Return to Work", "PRSI Letter", "CMR Consignment Note", "Proof of Delivery (POD)", "Waste Transfer Note"];
const empty = { title: "", doc_type: "Operator Licence", reference: "", expiry_date: "", notes: "", link_url: "", attachments: [] };
const emptyGen = { template: "Warning Letter", title: "", recipient_name: "", recipient_address: "", points: "", subject: "", body: "" };

export function DocumentsPanel({ embedded = false }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [genOpen, setGenOpen] = useState(false);
  const [gen, setGen] = useState(emptyGen);
  const [genEditId, setGenEditId] = useState(null);
  const [drafting, setDrafting] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = async () => setItems((await api.get("/documents")).data.filter((d) => !d.driver_id));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  // Prefill the generator from a tacho analysis "Create infringement letter" handoff.
  useEffect(() => {
    const raw = sessionStorage.getItem("tacho_infringement_draft");
    if (raw) {
      sessionStorage.removeItem("tacho_infringement_draft");
      try {
        const d = JSON.parse(raw);
        setGen({ ...emptyGen, template: "Driver Infringement", recipient_name: d.recipient_name || "", points: d.points || "" });
        setGenEditId(null);
        setGenOpen(true);
      } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (d) => { setForm({ ...empty, ...d, expiry_date: d.expiry_date || "", attachments: d.attachments || [] }); setEditId(d.id); setOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form, expiry_date: form.expiry_date || null };
    try {
      if (editId) await api.put(`/documents/${editId}`, payload);
      else await api.post("/documents", payload);
      toast.success(editId ? "Document updated" : "Document added");
      setOpen(false); load();
    } catch { toast.error("Could not save document"); }
  };
  const remove = async (id) => { await api.delete(`/documents/${id}`); toast.success("Document removed"); load(); };

  const openGen = () => { setGen(emptyGen); setGenEditId(null); setGenOpen(true); };
  const openRegen = (d) => {
    const l = d.letter_data || {};
    setGen({ ...emptyGen, ...l, points: "" });
    setGenEditId(d.id); setGenOpen(true);
  };
  const draft = async () => {
    setDrafting(true);
    try {
      const { data } = await api.post("/documents/draft", { template: gen.template, recipient_name: gen.recipient_name, points: gen.points });
      setGen((g) => ({ ...g, subject: data.subject || g.template, body: data.body || "" }));
      toast.success("Draft ready — review & edit below");
    } catch { toast.error("Could not draft letter"); }
    setDrafting(false);
  };
  const generate = async () => {
    setGenerating(true);
    const payload = {
      template: gen.template, title: gen.title, recipient_name: gen.recipient_name,
      recipient_address: gen.recipient_address, subject: gen.subject, body: gen.body,
    };
    try {
      if (genEditId) { await api.put(`/documents/${genEditId}/regenerate`, payload); toast.success("Document updated"); }
      else { await api.post("/documents/generate", payload); toast.success("Document generated & saved"); }
      setGenOpen(false); load();
    } catch { toast.error("Could not generate document"); }
    setGenerating(false);
  };

  return (
    <div data-testid="documents-page">
      {!embedded && <Header title="Documents" subtitle="Operator licence, insurance, audits & wheel security" onAdd={openNew} addTestId="add-document-button" addLabel="Add Document" />}
      <div className="flex justify-end gap-2 mb-4">
        <Button data-testid="generate-document-button" onClick={openGen} variant="outline" className="rounded-md gap-2 border-slate-300"><FileSignature size={16} /> Generate Document</Button>
        {embedded && <Button data-testid="add-document-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2">Add Document</Button>}
      </div>

      {items.length === 0 ? <Empty icon={FolderCheck} text="No documents yet. Track expiry of key operator documents." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((d) => (
            <div key={d.id} data-testid="document-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{d.doc_type}</p>
                  <h3 className="font-heading font-bold text-lg text-slate-900 truncate">{d.title}</h3>
                  {d.reference && <p className="text-xs text-slate-500 mt-0.5">Ref: {d.reference}</p>}
                  {d.letter_data && d.notes && <p className="text-[11px] text-slate-400 mt-0.5">{d.notes}</p>}
                </div>
                <div className="flex gap-1 shrink-0">
                  {d.link_url && (
                    <a data-testid="doc-link-button" href={d.link_url} target="_blank" rel="noopener noreferrer" title="Open web link" className="text-slate-400 hover:text-slate-900 p-1"><Link2 size={15} /></a>
                  )}
                  {d.attachments?.length > 0 && (
                    <a data-testid="view-document-button" href={`${API}/files/${d.attachments[0].file_id}?auth=${localStorage.getItem("token") || ""}`} target="_blank" rel="noopener noreferrer" title="View / download" className="text-slate-400 hover:text-slate-900 p-1"><Eye size={15} /></a>
                  )}
                  {d.letter_data && (
                    <button data-testid="regenerate-document-button" onClick={() => openRegen(d)} title="Edit / regenerate" className="text-slate-400 hover:text-slate-900 p-1"><RefreshCw size={15} /></button>
                  )}
                  <button data-testid="edit-document-button" onClick={() => openEdit(d)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                  <button data-testid="delete-document-button" onClick={() => remove(d.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400">Expiry</p>
                  <p className="text-sm font-semibold text-slate-700">{d.expiry_date || "—"}{d.days_left != null && <span className="text-slate-400 font-normal"> · {d.days_left < 0 ? `${Math.abs(d.days_left)}d overdue` : `${d.days_left}d`}</span>}</p>
                </div>
                <StatusBadge status={d.status} />
              </div>
              <AttachmentThumbs attachments={d.attachments} />
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Document" : "Add Document"}</DialogTitle><DialogDescription className="sr-only">Document details form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Title *"><Input data-testid="doc-title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Standard National O-Licence" /></Field>
            <Field label="Type">
              <Select value={form.doc_type} onValueChange={(v) => setForm({ ...form, doc_type: v })}>
                <SelectTrigger data-testid="doc-type-select"><SelectValue /></SelectTrigger>
                <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Reference"><Input data-testid="doc-reference" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="OB1234567" /></Field>
              <Field label="Expiry Date"><Input data-testid="doc-expiry" type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} /></Field>
            </div>
            <Field label="Scan / Document"><FileUpload testid="doc-upload" attachments={form.attachments} onChange={(a) => setForm({ ...form, attachments: a })} /></Field>
            <Field label="Web link (optional)"><Input data-testid="doc-link" type="url" value={form.link_url} onChange={(e) => setForm({ ...form, link_url: e.target.value })} placeholder="https://… (e.g. VOL portal, shared drive)" /></Field>
            <DialogFooter><Button data-testid="save-document-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Document"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={genOpen} onOpenChange={setGenOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading flex items-center gap-2"><FileSignature size={18} /> {genEditId ? "Edit / Regenerate Document" : "Generate Company Document"}</DialogTitle><DialogDescription>Pick a template, add the details, let AI draft it, then edit &amp; save a branded PDF to your documents.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Template">
                <Select value={gen.template} onValueChange={(v) => setGen({ ...gen, template: v })}>
                  <SelectTrigger data-testid="gen-template"><SelectValue /></SelectTrigger>
                  <SelectContent>{LETTER_TEMPLATES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Recipient name"><Input data-testid="gen-recipient" value={gen.recipient_name} onChange={(e) => setGen({ ...gen, recipient_name: e.target.value })} placeholder="John Smith" /></Field>
            </div>
            <Field label="Recipient address (optional)"><Textarea data-testid="gen-address" rows={2} value={gen.recipient_address} onChange={(e) => setGen({ ...gen, recipient_address: e.target.value })} placeholder="1 High Street&#10;Manchester&#10;M1 2AB" /></Field>
            <Field label="Key points / context for the AI">
              <Textarea data-testid="gen-points" rows={3} value={gen.points} onChange={(e) => setGen({ ...gen, points: e.target.value })} placeholder="e.g. 3rd speeding infringement in 6 months. Formal first written warning. Expect improvement within 3 months." />
            </Field>
            <Button data-testid="gen-draft-button" onClick={draft} disabled={drafting} variant="outline" className="w-full gap-2 border-slate-300">
              {drafting ? <><Loader2 size={16} className="animate-spin" /> Drafting…</> : <><Sparkles size={16} /> AI Draft Letter</>}
            </Button>
            <Field label="Subject / reference line"><Input data-testid="gen-subject" value={gen.subject} onChange={(e) => setGen({ ...gen, subject: e.target.value })} placeholder="First Written Warning — Speeding" /></Field>
            <Field label="Letter body (editable)"><Textarea data-testid="gen-body" rows={9} value={gen.body} onChange={(e) => setGen({ ...gen, body: e.target.value })} placeholder="Click ‘AI Draft Letter’ to generate, or write the body here…" /></Field>
            <Field label="Save as (document title, optional)"><Input data-testid="gen-title" value={gen.title} onChange={(e) => setGen({ ...gen, title: e.target.value })} placeholder="Defaults to template + recipient" /></Field>
            <DialogFooter>
              <Button data-testid="gen-generate-button" onClick={generate} disabled={generating || !gen.body} className="bg-black hover:bg-slate-800 gap-2">
                {generating ? <><Loader2 size={16} className="animate-spin" /> {genEditId ? "Updating…" : "Generating…"}</> : (genEditId ? "Update & Save PDF" : "Generate & Save PDF")}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Documents() {
  return <DocumentsPanel />;
}
