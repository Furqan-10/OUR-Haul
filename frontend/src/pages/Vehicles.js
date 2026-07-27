import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { getTerms } from "@/lib/terms";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Plus, Truck, Trash2, Pencil, FileDown, Ban, History, Tag, Undo2 } from "lucide-react";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { TrailersPanel } from "@/pages/Trailers";
import { TestHistoryPanel } from "@/pages/TestHistory";
import { FuelPanel } from "@/pages/Fuel";
import { downloadPdf } from "@/lib/download";

const VEHICLE_TYPES = ["HGV (Rigid)", "HGV (Artic / Tractor Unit)", "LGV / Van", "Car", "Minibus / PSV", "Other"];
const empty = { registration: "", make: "", model: "", type: "HGV (Rigid)", mot_due: "", service_due: "", tax_due: "", first_use_date: "", tacho_calibration_due: "", speed_limiter_due: "", vor: false, vor_reason: "", notes: "" };

function VehiclesPanel() {
  const { user } = useAuth();
  const terms = getTerms(user?.region);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [insurance, setInsurance] = useState([]);
  const [vorFor, setVorFor] = useState(null);
  const [vorForm, setVorForm] = useState({ reason: "", off_date: "", expected_return: "" });
  const [soldFor, setSoldFor] = useState(null);
  const [soldForm, setSoldForm] = useState({ sold_date: "", notes: "" });

  const load = async () => {
    const [v, i] = await Promise.all([api.get("/vehicles"), api.get("/insurance")]);
    setItems(v.data); setInsurance(i.data);
  };
  const insByType = (t) => insurance.find((p) => p.policy_type === t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(empty); setEditId(null); setOpen(true); };
  const openEdit = (v) => {
    setForm({ ...empty, ...v, mot_due: v.mot_due || "", service_due: v.service_due || "", tax_due: v.tax_due || "", first_use_date: v.first_use_date || "", tacho_calibration_due: v.tacho_calibration_due || "", speed_limiter_due: v.speed_limiter_due || "" });
    setEditId(v.id); setOpen(true);
  };

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...form };
    ["mot_due", "service_due", "tax_due", "first_use_date", "tacho_calibration_due", "speed_limiter_due"].forEach((k) => { if (!payload[k]) payload[k] = null; });
    try {
      if (editId) await api.put(`/vehicles/${editId}`, payload);
      else await api.post("/vehicles", payload);
      toast.success(editId ? "Vehicle updated" : "Vehicle added");
      setOpen(false); load();
    } catch (err) { toast.error("Could not save vehicle"); }
  };

  const remove = async (id) => { await api.delete(`/vehicles/${id}`); toast.success("Vehicle removed"); load(); };

  const openVor = (v) => {
    setVorForm({ reason: v.vor_reason || "", off_date: v.vor_off_date || new Date().toISOString().slice(0, 10), expected_return: v.vor_expected_return || "" });
    setVorFor(v);
  };
  const saveVor = async () => {
    try {
      await api.post(`/vehicles/${vorFor.id}/vor`, vorForm);
      toast.success("Vehicle marked VOR — added to calendar");
      setVorFor(null); load();
    } catch { toast.error("Could not mark VOR"); }
  };
  const clearVor = async (v) => {
    try { await api.post(`/vehicles/${v.id}/vor/clear`); toast.success(`${v.registration} returned to service`); load(); }
    catch { toast.error("Could not update"); }
  };

  const openSold = (v) => {
    setSoldForm({ sold_date: v.sold_date || new Date().toISOString().slice(0, 10), notes: v.sold_notes || "" });
    setSoldFor(v);
  };
  const saveSold = async () => {
    try {
      await api.post(`/vehicles/${soldFor.id}/sold`, soldForm);
      toast.success("Vehicle marked sold — records retained for 18 months");
      setSoldFor(null); load();
    } catch { toast.error("Could not mark sold"); }
  };
  const clearSold = async (v) => {
    try { await api.post(`/vehicles/${v.id}/sold/clear`); toast.success(`${v.registration} restored to active fleet`); load(); }
    catch { toast.error("Could not update"); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex flex-wrap gap-2" data-testid="fleet-insurance-summary">
          {[["Motor — Truck", "Truck insurance"], ["Motor — Trailer", "Trailer insurance"], ["Goods in Transit (GIT)", "GIT"]].map(([t, label]) => {
            const p = insByType(t);
            return (
              <div key={t} className="flex items-center gap-2 bg-white border border-slate-200 rounded-full pl-3 pr-2 py-1 text-xs">
                <span className="text-slate-500">{label}:</span>
                <span className="font-semibold text-slate-800">{p?.expiry_date || "Not on file"}</span>
                {p && <StatusBadge status={p.status} />}
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <Button data-testid="download-vehicles-pdf" variant="outline" onClick={() => downloadPdf("/reports/vehicles", "vehicles-report.pdf")} className="rounded-md gap-2 border-slate-300"><FileDown size={16} /> Download PDF</Button>
          <Button data-testid="add-vehicle-button" onClick={openNew} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Plus size={16} /> Add Vehicle</Button>
        </div>
      </div>
      {items.length === 0 ? (
        <Empty icon={Truck} text="No vehicles yet. Add your first vehicle to start tracking." />
      ) : (
        <div className="bg-white border border-slate-200 rounded-md overflow-hidden overflow-x-auto animate-in-up">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr className="text-xs uppercase tracking-wider text-slate-500">
                <th className="px-5 py-3 font-semibold">Registration</th>
                <th className="px-5 py-3 font-semibold">Vehicle</th>
                <th className="px-5 py-3 font-semibold">{terms.vehicleTest}</th>
                <th className="px-5 py-3 font-semibold">Service</th>
                <th className="px-5 py-3 font-semibold">{terms.roadTax}</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((v) => (
                <tr key={v.id} data-testid="vehicle-row" className="hover:bg-slate-50 transition-colors">
                  <td className="px-5 py-3 font-bold text-slate-900">
                    <div className="flex items-center gap-2">
                      {v.registration}
                      {v.vor && !v.sold && <span data-testid="vor-badge" className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-red-100 text-red-700" title={v.vor_reason || "Vehicle off road"}>VOR</span>}
                      {v.sold && <span data-testid="sold-badge" className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-700" title={v.sold_notes || `Sold / disposed${v.sold_date ? ` ${v.sold_date}` : ""}`}>SOLD</span>}
                    </div>
                  </td>
                  <td className="px-5 py-3 text-slate-600">{[v.make, v.model].filter(Boolean).join(" ") || "—"} <span className="text-slate-400">({v.type})</span></td>
                  <td className="px-5 py-3"><div className="flex flex-col gap-1 items-start"><StatusBadge status={v.mot_status} /><span className="text-xs text-slate-400">{v.mot_due || "—"}</span></div></td>
                  <td className="px-5 py-3"><div className="flex flex-col gap-1 items-start"><StatusBadge status={v.service_status} /><span className="text-xs text-slate-400">{v.service_due || "—"}</span></div></td>
                  <td className="px-5 py-3"><div className="flex flex-col gap-1 items-start"><StatusBadge status={v.tax_status} /><span className="text-xs text-slate-400">{v.tax_due || "—"}</span></div></td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    {v.sold
                      ? <button data-testid="restore-sold-button" onClick={() => clearSold(v)} title="Restore to active fleet" className="text-amber-600 hover:text-emerald-600 p-1.5"><Undo2 size={16} /></button>
                      : (v.vor
                        ? <button data-testid="clear-vor-button" onClick={() => clearVor(v)} title="Return to service" className="text-red-500 hover:text-emerald-600 p-1.5"><Ban size={16} /></button>
                        : <>
                            <button data-testid="vor-button" onClick={() => openVor(v)} title="Mark off road (VOR)" className="text-slate-400 hover:text-red-600 p-1.5"><Ban size={16} /></button>
                            <button data-testid="sold-button" onClick={() => openSold(v)} title="Mark as sold / disposed" className="text-slate-400 hover:text-amber-600 p-1.5"><Tag size={16} /></button>
                          </>)}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button data-testid="vehicle-history-button" aria-label="Vehicle history pack" title="Vehicle history pack (PDF)" className="text-slate-400 hover:text-slate-900 p-1.5"><History size={16} /></button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem data-testid="vehicle-history-summary" onClick={() => downloadPdf(`/reports/vehicle/${encodeURIComponent(v.registration)}`, `vehicle-history-${(v.registration || "vehicle").replace(/ /g, "")}.pdf`)}>
                          History pack (summary)
                        </DropdownMenuItem>
                        <DropdownMenuItem data-testid="vehicle-history-files" onClick={() => downloadPdf(`/reports/vehicle/${encodeURIComponent(v.registration)}?include_files=true`, `vehicle-history-${(v.registration || "vehicle").replace(/ /g, "")}-pack.pdf`)}>
                          History pack + evidence
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <button data-testid="edit-vehicle-button" onClick={() => openEdit(v)} className="text-slate-400 hover:text-slate-900 p-1.5"><Pencil size={16} /></button>
                    <button data-testid="delete-vehicle-button" onClick={() => remove(v.id)} className="text-slate-400 hover:text-red-600 p-1.5"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle className="font-heading">{editId ? "Edit Vehicle" : "Add Vehicle"}</DialogTitle><DialogDescription className="sr-only">Vehicle details form</DialogDescription></DialogHeader>
          <form onSubmit={save} className="space-y-4">
            <Field label="Registration *"><Input data-testid="veh-registration" required value={form.registration} onChange={(e) => setForm({ ...form, registration: e.target.value })} placeholder="AB12 CDE" /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Make"><Input data-testid="veh-make" value={form.make} onChange={(e) => setForm({ ...form, make: e.target.value })} placeholder="DAF" /></Field>
              <Field label="Model"><Input data-testid="veh-model" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="XF 480" /></Field>
            </div>
            <Field label="Vehicle type *">
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="veh-type-select"><SelectValue placeholder="Select vehicle type" /></SelectTrigger>
                <SelectContent>{VEHICLE_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label={`${terms.vehicleTest} Due`}><Input data-testid="veh-mot" type="date" value={form.mot_due} onChange={(e) => setForm({ ...form, mot_due: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Service Due"><Input data-testid="veh-service" type="date" value={form.service_due} onChange={(e) => setForm({ ...form, service_due: e.target.value })} /></Field>
              <Field label={`${terms.roadTax} Due`}><Input data-testid="veh-tax" type="date" value={form.tax_due} onChange={(e) => setForm({ ...form, tax_due: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Tacho Calibration Due"><Input data-testid="veh-tachocal" type="date" value={form.tacho_calibration_due} onChange={(e) => setForm({ ...form, tacho_calibration_due: e.target.value })} /></Field>
              <Field label="Speed Limiter Check Due"><Input data-testid="veh-speedlimiter" type="date" value={form.speed_limiter_due} onChange={(e) => setForm({ ...form, speed_limiter_due: e.target.value })} /></Field>
            </div>
            <Field label="Date of First Use"><Input data-testid="veh-firstuse" type="date" value={form.first_use_date} onChange={(e) => setForm({ ...form, first_use_date: e.target.value })} /></Field>
            <div className="rounded-md border border-slate-200 p-3">
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input data-testid="veh-vor" type="checkbox" checked={!!form.vor} onChange={(e) => setForm({ ...form, vor: e.target.checked })} className="h-4 w-4 rounded border-slate-300 accent-red-600" />
                <span className="text-sm font-semibold text-slate-800">Vehicle Off Road (VOR)</span>
              </label>
              {form.vor && (
                <Input data-testid="veh-vor-reason" value={form.vor_reason} onChange={(e) => setForm({ ...form, vor_reason: e.target.value })} placeholder="Reason (e.g. awaiting parts, accident damage)" className="mt-3" />
              )}
              <p className="text-xs text-slate-400 mt-2">VOR vehicles are flagged and excluded from compliance due/overdue alerts while off road.</p>
            </div>
            <DialogFooter><Button data-testid="save-vehicle-button" type="submit" className="bg-black hover:bg-slate-800">{editId ? "Save Changes" : "Add Vehicle"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!vorFor} onOpenChange={(o) => !o && setVorFor(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle className="font-heading">Mark {vorFor?.registration} off road (VOR)</DialogTitle>
            <DialogDescription>This flags the vehicle and adds off-road / expected-return events to your calendar.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field label="Reason"><Input data-testid="vor-reason" value={vorForm.reason} onChange={(e) => setVorForm({ ...vorForm, reason: e.target.value })} placeholder="e.g. awaiting brake parts, accident damage" /></Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Off-road date"><Input data-testid="vor-off-date" type="date" value={vorForm.off_date} onChange={(e) => setVorForm({ ...vorForm, off_date: e.target.value })} /></Field>
              <Field label="Expected return"><Input data-testid="vor-return-date" type="date" value={vorForm.expected_return} onChange={(e) => setVorForm({ ...vorForm, expected_return: e.target.value })} /></Field>
            </div>
          </div>
          <DialogFooter><Button data-testid="save-vor-button" onClick={saveVor} className="bg-red-600 hover:bg-red-700">Mark VOR &amp; add to calendar</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!soldFor} onOpenChange={(o) => !o && setSoldFor(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle className="font-heading">Mark {soldFor?.registration} as sold / disposed</DialogTitle>
            <DialogDescription>Keeps the vehicle and all its records on file (excluded from your compliance score). DVSA requires records to be retained for 18 months after disposal — this appears in the Records Retention tracker.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field label="Date sold / disposed"><Input data-testid="sold-date" type="date" value={soldForm.sold_date} onChange={(e) => setSoldForm({ ...soldForm, sold_date: e.target.value })} /></Field>
            <Field label="Notes"><Input data-testid="sold-notes" value={soldForm.notes} onChange={(e) => setSoldForm({ ...soldForm, notes: e.target.value })} placeholder="e.g. sold to ABC Haulage, weighbridge ticket #123" /></Field>
          </div>
          <DialogFooter><Button data-testid="save-sold-button" onClick={saveSold} className="bg-amber-600 hover:bg-amber-700">Mark sold — retain 18 months</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Vehicles() {
  return (
    <div data-testid="vehicles-page">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance</p>
        <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Fleet</h1>
        <p className="text-slate-500 text-sm mt-1">Vehicles & trailers — test, service & tax tracking</p>
      </div>
      <Tabs defaultValue="vehicles">
        <TabsList className="mb-6">
          <TabsTrigger value="vehicles" data-testid="tab-vehicles">Vehicles</TabsTrigger>
          <TabsTrigger value="trailers" data-testid="tab-trailers">Trailers</TabsTrigger>
          <TabsTrigger value="fuel" data-testid="tab-fuel">Fuel &amp; Emissions</TabsTrigger>
          <TabsTrigger value="history" data-testid="tab-test-history">Test History</TabsTrigger>
        </TabsList>
        <TabsContent value="vehicles"><VehiclesPanel /></TabsContent>
        <TabsContent value="trailers"><TrailersPanel /></TabsContent>
        <TabsContent value="fuel"><FuelPanel /></TabsContent>
        <TabsContent value="history"><TestHistoryPanel embedded /></TabsContent>
      </Tabs>
    </div>
  );
}

export function Header({ title, subtitle, onAdd, addTestId, addLabel }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance</p>
        <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">{title}</h1>
        <p className="text-slate-500 text-sm mt-1">{subtitle}</p>
      </div>
      {onAdd && <Button data-testid={addTestId} onClick={onAdd} className="bg-black hover:bg-slate-800 rounded-md gap-2"><Plus size={16} /> {addLabel}</Button>}
    </div>
  );
}
export function Field({ label, children }) {
  return <div><Label className="mb-1.5 block">{label}</Label>{children}</div>;
}
export function Empty({ icon: Icon, text }) {
  return (
    <div className="bg-white border border-dashed border-slate-300 rounded-md p-14 text-center text-slate-500 flex flex-col items-center gap-3 animate-in-up">
      <Icon size={36} className="text-slate-300" />
      <p className="text-sm max-w-xs">{text}</p>
    </div>
  );
}
