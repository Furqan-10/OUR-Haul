import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { getTerms } from "@/lib/terms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Pencil, Fuel as FuelIcon, Gauge, Leaf, PoundSterling, Droplet, FileDown } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";

const empty = { vehicle_reg: "", fill_type: "diesel", fill_date: new Date().toISOString().slice(0, 10), litres: "", cost: "", odometer: "", notes: "" };

export function FuelPanel() {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const cur = user?.region === "IE" ? "€" : "£";
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState({ vehicles: [], totals: {} });
  const [assets, setAssets] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [tab, setTab] = useState("all"); // all | diesel | adblue
  const [reportOpen, setReportOpen] = useState(false);
  const [rpt, setRpt] = useState({ from_date: "", to_date: "", vehicle_reg: "" });
  const [downloading, setDownloading] = useState(false);

  const load = async () => {
    const [f, s, v, t] = await Promise.all([api.get("/fuel"), api.get("/fuel/summary"), api.get("/vehicles"), api.get("/trailers")]);
    setItems(f.data); setSummary(s.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)].filter(Boolean));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = (type) => { setForm({ ...empty, fill_type: type || "diesel" }); setEditId(null); setOpen(true); };
  const openEdit = (r) => { setForm({ ...empty, ...r, fill_date: r.fill_date || "" }); setEditId(r.id); setOpen(true); };
  const num = (v) => (v === "" || v == null ? 0 : Number(v));

  const save = async (e) => {
    e.preventDefault();
    if (!form.vehicle_reg) { toast.error("Select a vehicle"); return; }
    const payload = { ...form, litres: num(form.litres), cost: num(form.cost), odometer: num(form.odometer), fill_date: form.fill_date || null };
    try {
      if (editId) await api.put(`/fuel/${editId}`, payload);
      else await api.post("/fuel", payload);
      toast.success(editId ? "Fill updated" : `${form.fill_type === "adblue" ? "AdBlue" : "Diesel"} fill added`);
      setOpen(false); load();
    } catch { toast.error("Could not save fill"); }
  };
  const remove = async (id) => { await api.delete(`/fuel/${id}`); toast.success("Record removed"); load(); };

  const downloadReport = async () => {
    setDownloading(true);
    try {
      const params = new URLSearchParams();
      if (rpt.from_date) params.set("from_date", rpt.from_date);
      if (rpt.to_date) params.set("to_date", rpt.to_date);
      if (rpt.vehicle_reg) params.set("vehicle_reg", rpt.vehicle_reg);
      const res = await api.get(`/fuel/report?${params.toString()}`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url; a.download = `fuel-report.pdf`; a.click();
      window.URL.revokeObjectURL(url);
      toast.success("Report downloaded");
      setReportOpen(false);
    } catch { toast.error("Could not generate report"); }
    finally { setDownloading(false); }
  };

  const t = summary.totals || {};
  const filtered = items.filter((r) => tab === "all" || (r.fill_type || "diesel") === tab);
  const isAdblueForm = form.fill_type === "adblue";

  return (
    <div data-testid="fuel-page">
      <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
        <div className="flex gap-2" data-testid="fuel-type-tabs">
          {[["all", "All fills"], ["diesel", "Diesel"], ["adblue", "AdBlue"]].map(([k, l]) => (
            <button key={k} data-testid={`fuel-tab-${k}`} onClick={() => setTab(k)}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${tab === k ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>{l}</button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button data-testid="fuel-report-button" variant="outline" onClick={() => { setRpt({ from_date: "", to_date: "", vehicle_reg: "" }); setReportOpen(true); }} className="rounded-md gap-2 border-slate-300"><FileDown size={16} /> Generate report</Button>
          <Button data-testid="add-adblue-button" variant="outline" onClick={() => openNew("adblue")} className="rounded-md gap-2 border-slate-300"><Droplet size={16} /> Add AdBlue</Button>
          <Button data-testid="add-fuel-button" onClick={() => openNew("diesel")} className="bg-black hover:bg-slate-800 rounded-md gap-2"><FuelIcon size={16} /> Add Diesel</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" data-testid="fuel-totals">
        <Stat icon={FuelIcon} label="Diesel used" value={`${t.diesel_litres || 0} L`} sub={`${cur}${t.diesel_cost || 0} · ${t.diesel_fills || 0} fills`} />
        <Stat icon={Droplet} label="AdBlue used" value={`${t.adblue_litres || 0} L`} sub={`${cur}${t.adblue_cost || 0} · ${t.adblue_fills || 0} fills`} />
        <Stat icon={Gauge} label="Fleet avg MPG" value={t.avg_mpg != null ? `${t.avg_mpg}` : "—"} sub={`${t.miles || 0} mi`} />
        <Stat icon={Leaf} label="CO₂ emitted" value={`${t.co2_tonnes || 0} t`} sub={`${t.co2_kg || 0} kg`} />
      </div>

      {summary.vehicles?.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-md overflow-hidden mb-6" data-testid="fuel-league">
          <div className="px-5 py-3 border-b border-slate-100"><h3 className="font-heading font-bold text-sm tracking-tight">Per-vehicle efficiency ({terms.authority})</h3></div>
          <div className="divide-y divide-slate-100">
            {summary.vehicles.map((v) => (
              <div key={v.vehicle_reg} data-testid="fuel-vehicle-row" className="flex items-center justify-between px-5 py-2.5 text-sm">
                <span className="font-semibold text-slate-800">{v.vehicle_reg}</span>
                <div className="flex items-center gap-5 text-slate-500 text-xs">
                  <span><b className="text-slate-800 text-sm">{v.avg_mpg ?? "—"}</b> mpg</span>
                  <span>{v.diesel_litres} L diesel</span>
                  <span>{v.adblue_litres} L AdBlue</span>
                  <span>{v.co2_kg} kg CO₂</span>
                  <span>{v.cost_per_mile != null ? `${cur}${v.cost_per_mile}/mi` : "—"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {filtered.length === 0 ? <Empty icon={FuelIcon} text="No fills yet. Log diesel and AdBlue separately to track MPG, CO₂ and usage." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((r) => {
            const adblue = (r.fill_type || "diesel") === "adblue";
            return (
              <div key={r.id} data-testid="fuel-card" className="bg-white border border-slate-200 rounded-md p-5 hover:-translate-y-1 hover:shadow-sm hover:border-slate-300 transition-all duration-200 animate-in-up">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-heading font-bold text-lg text-slate-900">{r.vehicle_reg}</h3>
                      <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${adblue ? "bg-sky-100 text-sky-700" : "bg-amber-100 text-amber-700"}`}>{adblue ? "AdBlue" : "Diesel"}</span>
                    </div>
                    <p className="text-xs text-slate-500">{r.fill_date || "—"}{r.odometer ? ` · ${r.odometer} mi` : ""}</p>
                  </div>
                  <div className="flex gap-1">
                    <button data-testid="edit-fuel-button" onClick={() => openEdit(r)} className="text-slate-400 hover:text-slate-900 p-1"><Pencil size={15} /></button>
                    <button data-testid="delete-fuel-button" onClick={() => remove(r.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <KV label="Litres" value={`${r.litres || 0} L`} strong />
                  <KV label="Cost" value={`${cur}${r.cost || 0}`} />
                  {!adblue && <KV label="MPG" value={r.mpg != null ? `${r.mpg}` : "—"} strong />}
                  {!adblue && <KV label="CO₂" value={`${r.co2_kg || 0} kg`} />}
                  {!adblue && <KV label="Miles" value={r.miles != null ? `${r.miles}` : "—"} />}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Fill" : "Add Fill"}</DialogTitle><DialogDescription>Diesel fills calculate MPG (from miles between fills) and CO₂ at 2.64 kg/L. AdBlue is tracked as usage only.</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Fill type *">
              <Select value={form.fill_type} onValueChange={(v) => setForm({ ...form, fill_type: v })}>
                <SelectTrigger data-testid="fuel-type"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="diesel">Diesel</SelectItem><SelectItem value="adblue">AdBlue</SelectItem></SelectContent>
              </Select>
            </Field>
            <Field label="Vehicle *">
              <Select value={form.vehicle_reg} onValueChange={(v) => setForm({ ...form, vehicle_reg: v })}>
                <SelectTrigger data-testid="fuel-vehicle"><SelectValue placeholder={assets.length ? "Select vehicle" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Date"><Input data-testid="fuel-date" type="date" value={form.fill_date} onChange={(e) => setForm({ ...form, fill_date: e.target.value })} /></Field>
              <Field label={`${isAdblueForm ? "AdBlue" : "Diesel"} (litres)`}><Input data-testid="fuel-litres" type="number" step="0.01" value={form.litres} onChange={(e) => setForm({ ...form, litres: e.target.value })} /></Field>
            </div>
            {!isAdblueForm && (
              <Field label="Odometer (miles)"><Input data-testid="fuel-odometer" type="number" step="1" value={form.odometer} onChange={(e) => setForm({ ...form, odometer: e.target.value })} placeholder="e.g. 128400 — needed for MPG" /></Field>
            )}
            <Field label={`Cost (${cur})`}><Input data-testid="fuel-cost" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></Field>
            <Field label="Notes"><Input data-testid="fuel-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
            <DialogFooter><Button data-testid="save-fuel-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Fill"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle className="font-heading">Generate Fuel Report</DialogTitle><DialogDescription>Download a branded PDF of diesel & AdBlue usage, MPG, CO₂ and spend. Leave dates blank for all-time.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="From"><Input data-testid="report-from" type="date" value={rpt.from_date} onChange={(e) => setRpt({ ...rpt, from_date: e.target.value })} /></Field>
              <Field label="To"><Input data-testid="report-to" type="date" value={rpt.to_date} onChange={(e) => setRpt({ ...rpt, to_date: e.target.value })} /></Field>
            </div>
            <Field label="Vehicle">
              <Select value={rpt.vehicle_reg || "all"} onValueChange={(v) => setRpt({ ...rpt, vehicle_reg: v === "all" ? "" : v })}>
                <SelectTrigger data-testid="report-vehicle"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">All vehicles</SelectItem>{assets.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <DialogFooter><Button data-testid="download-report-button" onClick={downloadReport} disabled={downloading} className="bg-black hover:bg-slate-800 gap-2"><FileDown size={16} /> {downloading ? "Generating…" : "Download PDF"}</Button></DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub }) {
  return (
    <div className="bg-white border border-slate-200 rounded-md p-4 animate-in-up">
      <div className="flex items-center gap-1.5 text-slate-400 mb-1"><Icon size={14} /><span className="text-[10px] uppercase tracking-widest font-semibold">{label}</span></div>
      <p className="font-heading font-black text-2xl text-slate-900 tracking-tight">{value}</p>
      <p className="text-xs text-slate-400">{sub}</p>
    </div>
  );
}

function KV({ label, value, strong }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{label}</p>
      <p className={strong ? "font-bold text-slate-900" : "text-slate-700"}>{value}</p>
    </div>
  );
}

export default function Fuel() {
  return <FuelPanel />;
}
