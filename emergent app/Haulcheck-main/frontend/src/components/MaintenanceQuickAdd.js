import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Wrench, Cog, FileWarning, ClipboardCheck, Disc3 } from "lucide-react";
import { toast } from "sonner";

const TYPES = [
  { key: "pmi", label: "PMI Schedule", icon: Wrench },
  { key: "service", label: "Service Record", icon: Cog },
  { key: "defect", label: "Defect", icon: FileWarning },
  { key: "walkaround", label: "Daily Check", icon: ClipboardCheck },
  { key: "wheel", label: "Wheel Security Audit", icon: Disc3 },
];

const F = ({ label, children }) => (
  <div><Label className="mb-1.5 block">{label}</Label>{children}</div>
);

export function MaintenanceQuickAdd({ open, onOpenChange, defaultDate, assets = [], onSaved }) {
  const [type, setType] = useState("pmi");
  const [drivers, setDrivers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({});

  const reset = (t) => {
    const d = defaultDate;
    const defaults = {
      pmi: { vehicle_reg: "", next_due: d, frequency_weeks: "6", inspector: "" },
      service: { vehicle_reg: "", service_date: d, service_type: "Full service", odometer: "", provider: "", cost: "", next_service_due: "", notes: "" },
      defect: { vehicle_reg: "", reported_by: "", category: "General", severity: "minor", description: "", defect_date: d, odometer: "" },
      walkaround: { vehicle_reg: "", driver_name: "", check_date: d, result: "nil_defect", mileage: "", defects_noted: "" },
      wheel: { vehicle_reg: "", audit_date: d, result: "pass", torque_setting: "", checked_by: "", next_due: "", notes: "" },
    };
    setType(t);
    setForm(defaults[t]);
  };

  useEffect(() => {
    if (open) {
      reset("pmi");
      api.get("/drivers").then((r) => setDrivers(r.data.map((x) => x.name))).catch(() => {});
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.vehicle_reg) { toast.error("Select a vehicle"); return; }
    setBusy(true);
    try {
      if (type === "pmi") {
        await api.post("/pmi", { ...form, frequency_weeks: Number(form.frequency_weeks), next_due: form.next_due || null });
        toast.success("PMI scheduled — dates added to calendar");
      } else if (type === "service") {
        await api.post("/service-records", { ...form, odometer: Number(form.odometer) || 0, cost: Number(form.cost) || 0, next_service_due: form.next_service_due || null, service_date: form.service_date || null, attachments: [] });
        toast.success("Service record added");
      } else if (type === "defect") {
        if (!form.description) { toast.error("Enter a description"); setBusy(false); return; }
        await api.post("/defects", { ...form, defect_date: form.defect_date || null, attachments: [] });
        toast.success("Defect logged");
      } else if (type === "walkaround") {
        await api.post("/walkarounds", { ...form, check_date: form.check_date || null, attachments: [] });
        toast.success("Daily check logged");
      } else if (type === "wheel") {
        await api.post("/wheel-audits", { ...form, next_due: form.next_due || null, audit_date: form.audit_date || null, attachments: [] });
        toast.success("Wheel security audit logged");
      }
      onOpenChange(false);
      onSaved && onSaved();
    } catch { toast.error("Could not save"); }
    finally { setBusy(false); }
  };

  const VehicleSelect = () => (
    <F label="Vehicle *">
      <Select value={form.vehicle_reg} onValueChange={(v) => set("vehicle_reg", v)}>
        <SelectTrigger data-testid="mqa-vehicle"><SelectValue placeholder={assets.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
        <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
      </Select>
    </F>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading">Add Maintenance</DialogTitle>
          <DialogDescription>Pick what you'd like to add, then fill in the details.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap gap-2" data-testid="mqa-type-picker">
          {TYPES.map((t) => (
            <button key={t.key} type="button" data-testid={`mqa-type-${t.key}`} onClick={() => reset(t.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${type === t.key ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
              <t.icon size={13} /> {t.label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4 mt-2">
          <VehicleSelect />

          {type === "pmi" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <F label="First inspection date"><Input data-testid="mqa-pmi-date" type="date" value={form.next_due} onChange={(e) => set("next_due", e.target.value)} /></F>
                <F label="Frequency (weeks)">
                  <Select value={String(form.frequency_weeks)} onValueChange={(v) => set("frequency_weeks", v)}>
                    <SelectTrigger data-testid="mqa-pmi-freq"><SelectValue /></SelectTrigger>
                    <SelectContent>{[0, 4, 6, 8, 10, 12, 13].map((w) => <SelectItem key={w} value={String(w)}>{w === 0 ? "One-off / interim" : `Every ${w} weeks`}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
              </div>
              <F label="Inspector (optional)"><Input data-testid="mqa-pmi-inspector" value={form.inspector} onChange={(e) => set("inspector", e.target.value)} placeholder="Garage / fitter" /></F>
            </>
          )}

          {type === "service" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <F label="Service type">
                  <Select value={form.service_type} onValueChange={(v) => set("service_type", v)}>
                    <SelectTrigger data-testid="mqa-service-type"><SelectValue /></SelectTrigger>
                    <SelectContent>{["Full service", "Interim service", "Oil & filter", "Air-con / AdBlue", "Repair", "Other"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
                <F label="Service date"><Input data-testid="mqa-service-date" type="date" value={form.service_date} onChange={(e) => set("service_date", e.target.value)} /></F>
                <F label="Odometer"><Input data-testid="mqa-service-odo" value={form.odometer} onChange={(e) => set("odometer", e.target.value)} /></F>
                <F label="Provider"><Input data-testid="mqa-service-provider" value={form.provider} onChange={(e) => set("provider", e.target.value)} /></F>
                <F label="Cost"><Input data-testid="mqa-service-cost" value={form.cost} onChange={(e) => set("cost", e.target.value)} /></F>
                <F label="Next service due"><Input data-testid="mqa-service-next" type="date" value={form.next_service_due} onChange={(e) => set("next_service_due", e.target.value)} /></F>
              </div>
              <F label="Notes"><Textarea data-testid="mqa-service-notes" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></F>
            </>
          )}

          {type === "defect" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <F label="Reported by">
                  <Select value={form.reported_by} onValueChange={(v) => set("reported_by", v)}>
                    <SelectTrigger data-testid="mqa-defect-reporter"><SelectValue placeholder={drivers.length ? "Select driver" : "Add a driver first"} /></SelectTrigger>
                    <SelectContent>{drivers.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
                <F label="Category">
                  <Select value={form.category} onValueChange={(v) => set("category", v)}>
                    <SelectTrigger data-testid="mqa-defect-category"><SelectValue /></SelectTrigger>
                    <SelectContent>{["General", "Brakes", "Tyres & Wheels", "Lights", "Steering", "Bodywork", "Load Security", "Other"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
                <F label="Severity">
                  <Select value={form.severity} onValueChange={(v) => set("severity", v)}>
                    <SelectTrigger data-testid="mqa-defect-severity"><SelectValue /></SelectTrigger>
                    <SelectContent>{[["minor", "Minor"], ["major", "Major"], ["safety_critical", "Safety Critical"]].map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
                <F label="Date"><Input data-testid="mqa-defect-date" type="date" value={form.defect_date} onChange={(e) => set("defect_date", e.target.value)} /></F>
                <F label="Mileage / Odometer"><Input data-testid="mqa-defect-odometer" value={form.odometer} onChange={(e) => set("odometer", e.target.value)} placeholder="e.g. 128,400" /></F>
              </div>
              <F label="Description *"><Textarea data-testid="mqa-defect-desc" rows={3} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Describe the defect…" /></F>
            </>
          )}

          {type === "walkaround" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <F label="Driver">
                  <Select value={form.driver_name} onValueChange={(v) => set("driver_name", v)}>
                    <SelectTrigger data-testid="mqa-walk-driver"><SelectValue placeholder={drivers.length ? "Select driver" : "Add a driver first"} /></SelectTrigger>
                    <SelectContent>{drivers.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                  </Select>
                </F>
                <F label="Date"><Input data-testid="mqa-walk-date" type="date" value={form.check_date} onChange={(e) => set("check_date", e.target.value)} /></F>
                <F label="Result">
                  <Select value={form.result} onValueChange={(v) => set("result", v)}>
                    <SelectTrigger data-testid="mqa-walk-result"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="nil_defect">Nil defect</SelectItem><SelectItem value="defects_found">Defects found</SelectItem></SelectContent>
                  </Select>
                </F>
                <F label="Mileage"><Input data-testid="mqa-walk-mileage" value={form.mileage} onChange={(e) => set("mileage", e.target.value)} /></F>
              </div>
              <F label="Defects noted"><Textarea data-testid="mqa-walk-notes" rows={2} value={form.defects_noted} onChange={(e) => set("defects_noted", e.target.value)} /></F>
            </>
          )}

          {type === "wheel" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <F label="Audit date"><Input data-testid="mqa-wheel-date" type="date" value={form.audit_date} onChange={(e) => set("audit_date", e.target.value)} /></F>
                <F label="Result">
                  <Select value={form.result} onValueChange={(v) => set("result", v)}>
                    <SelectTrigger data-testid="mqa-wheel-result"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="pass">Pass</SelectItem><SelectItem value="advisory">Advisory</SelectItem><SelectItem value="fail">Fail</SelectItem></SelectContent>
                  </Select>
                </F>
                <F label="Torque setting"><Input data-testid="mqa-wheel-torque" value={form.torque_setting} onChange={(e) => set("torque_setting", e.target.value)} placeholder="e.g. 450 Nm" /></F>
                <F label="Checked by"><Input data-testid="mqa-wheel-checkedby" value={form.checked_by} onChange={(e) => set("checked_by", e.target.value)} /></F>
                <F label="Next due"><Input data-testid="mqa-wheel-next" type="date" value={form.next_due} onChange={(e) => set("next_due", e.target.value)} /></F>
              </div>
              <F label="Notes"><Textarea data-testid="mqa-wheel-notes" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></F>
            </>
          )}

          <DialogFooter><Button data-testid="mqa-save-button" type="submit" disabled={busy} className="bg-black hover:bg-slate-800">{busy ? "Saving…" : "Save"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
