import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { RegionToggle } from "@/components/RegionToggle";
import { getTerms } from "@/lib/terms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Building2, UserCog, Save } from "lucide-react";
import { toast } from "sonner";
import { Field } from "@/pages/Vehicles";
import { FileUpload } from "@/components/FileUpload";

const LICENCE_TYPES = ["Standard National", "Standard International", "Restricted"];

const Card = ({ icon: Icon, title, children }) => (
  <div className="bg-white border border-slate-200 rounded-md p-6 animate-in-up">
    <div className="flex items-center gap-2 mb-5">
      <Icon size={18} className="text-slate-900" />
      <h3 className="font-heading font-bold text-lg tracking-tight">{title}</h3>
    </div>
    <div className="space-y-4">{children}</div>
  </div>
);

const empty = {
  company_name: "", company_number: "", operator_licence_number: "", licence_type: "Standard National",
  address: "", authorised_vehicles: 0, authorised_trailers: 0,
  tm_name: "", tm_cpc_number: "", tm_email: "", tm_phone: "", notes: "", logo_file_id: "",
};

export default function Operator() {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/operator").then((r) => setForm({ ...empty, ...r.data }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.put("/operator", { ...form, authorised_vehicles: Number(form.authorised_vehicles) || 0, authorised_trailers: Number(form.authorised_trailers) || 0 });
      toast.success("Operator details saved");
    } catch { toast.error("Could not save details"); }
    finally { setBusy(false); }
  };

  return (
    <div data-testid="operator-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance · {terms.authority}</p>
          <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Operator Details</h1>
          <p className="text-slate-500 text-sm mt-1">Company, {terms.operatorLicence} & Transport Manager details</p>
        </div>
        <div className="flex items-center gap-3">
          <RegionToggle />
          <Button data-testid="save-operator-button" onClick={save} disabled={busy} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Save size={16} /> {busy ? "Saving…" : "Save Details"}</Button>
        </div>
      </div>

      <form onSubmit={save} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card icon={Building2} title="Company & Licence">
          <Field label="Company Name"><Input data-testid="op-company-name" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} placeholder="HaulCheck Logistics Ltd" /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Company Number"><Input data-testid="op-company-number" value={form.company_number} onChange={(e) => setForm({ ...form, company_number: e.target.value })} placeholder="12345678" /></Field>
            <Field label={`${terms.operatorLicence} No.`}><Input data-testid="op-licence-number" value={form.operator_licence_number} onChange={(e) => setForm({ ...form, operator_licence_number: e.target.value })} placeholder="OB1234567" /></Field>
          </div>
          <Field label="Licence Type">
            <Select value={form.licence_type} onValueChange={(v) => setForm({ ...form, licence_type: v })}>
              <SelectTrigger data-testid="op-licence-type"><SelectValue /></SelectTrigger>
              <SelectContent>{LICENCE_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Authorised Vehicles"><Input data-testid="op-auth-vehicles" type="number" min="0" value={form.authorised_vehicles} onChange={(e) => setForm({ ...form, authorised_vehicles: e.target.value })} /></Field>
            <Field label="Authorised Trailers"><Input data-testid="op-auth-trailers" type="number" min="0" value={form.authorised_trailers} onChange={(e) => setForm({ ...form, authorised_trailers: e.target.value })} /></Field>
          </div>
          <Field label="Operating Centre Address"><Textarea data-testid="op-address" rows={3} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="Full operating centre address" /></Field>
          <Field label="Company Logo (used as letterhead on generated documents)">
            <FileUpload testid="op-logo" accept="image/*" label="Upload logo (PNG / JPG)"
              attachments={form.logo_file_id ? [{ file_id: form.logo_file_id, filename: "logo", content_type: "image/png" }] : []}
              onChange={(a) => setForm({ ...form, logo_file_id: a.length ? a[a.length - 1].file_id : "" })} />
          </Field>
        </Card>

        <Card icon={UserCog} title="Transport Manager">
          <Field label="TM Name"><Input data-testid="op-tm-name" value={form.tm_name} onChange={(e) => setForm({ ...form, tm_name: e.target.value })} placeholder="Transport Manager full name" /></Field>
          <Field label="TM CPC Number"><Input data-testid="op-tm-cpc" value={form.tm_cpc_number} onChange={(e) => setForm({ ...form, tm_cpc_number: e.target.value })} placeholder="Certificate of Professional Competence no." /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="TM Email"><Input data-testid="op-tm-email" type="email" value={form.tm_email} onChange={(e) => setForm({ ...form, tm_email: e.target.value })} placeholder="tm@company.com" /></Field>
            <Field label="TM Phone"><Input data-testid="op-tm-phone" value={form.tm_phone} onChange={(e) => setForm({ ...form, tm_phone: e.target.value })} placeholder="07…" /></Field>
          </div>
          <Field label="Notes"><Textarea data-testid="op-notes" rows={4} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Additional operator notes, undertakings, conditions…" /></Field>
        </Card>
      </form>
    </div>
  );
}
