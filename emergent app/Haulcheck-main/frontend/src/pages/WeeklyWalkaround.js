import { useEffect, useState, Fragment } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, CalendarRange, FileDown, Check, X, Minus } from "lucide-react";
import { toast } from "sonner";
import { Field, Empty } from "@/pages/Vehicles";
import { CHECKLIST } from "@/pages/Walkaround";
import { SignaturePad } from "@/components/SignaturePad";
import { downloadPdf } from "@/lib/download";

const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];
const ALL_ITEMS = CHECKLIST.flatMap((s) => s.items.map((item) => ({ section: s.section, item })));

const mondayOf = (iso) => {
  const d = iso ? new Date(iso) : new Date();
  const day = (d.getDay() + 6) % 7; // 0 = Monday
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
};
const total = (a, b) => {
  const s = parseInt(String(a).replace(/,/g, ""), 10);
  const f = parseInt(String(b).replace(/,/g, ""), 10);
  return Number.isFinite(s) && Number.isFinite(f) && f >= s ? String(f - s) : "—";
};
const daysDone = (rec) => DAYS.filter(([k]) => (rec.days?.[k]?.checklist || []).length > 0).length;
const defectCount = (rec) =>
  DAYS.reduce((n, [k]) => n + (rec.days?.[k]?.checklist || []).filter((c) => !c.ok).length, 0);

const dayDate = (weekStart, idx) => {
  const d = new Date(`${weekStart}T00:00:00`);
  d.setDate(d.getDate() + idx);
  return d;
};
// a weekday counts as "missed" if its date is already in the past and it has no check recorded
const isMissed = (rec, idx, key) => {
  if ((rec.days?.[key]?.checklist || []).length > 0) return false;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return dayDate(rec.week_start, idx) < today;
};
const missedCount = (rec) => DAYS.filter(([k], i) => isMissed(rec, i, k)).length;

// cell value for an item on a day: true=ok, false=defect, null=not recorded
const cellFor = (rec, dayKey, itemName) => {
  const cl = rec.days?.[dayKey]?.checklist || [];
  const hit = cl.find((c) => c.item === itemName);
  return hit ? !!hit.ok : null;
};

export function WeeklyWalkaroundPanel() {
  const [items, setItems] = useState([]);
  const [assets, setAssets] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [newOpen, setNewOpen] = useState(false);
  const [nf, setNf] = useState({ vehicle_reg: "", driver_name: "", week_start: mondayOf(), mileage_start: "" });
  const [edit, setEdit] = useState(null); // full record being edited

  const load = async () => {
    const [w, v, t, dr] = await Promise.all([
      api.get("/weekly-walkarounds"), api.get("/vehicles"), api.get("/trailers"), api.get("/drivers"),
    ]);
    setItems(w.data);
    setAssets([...v.data.map((x) => x.registration), ...t.data.map((x) => x.trailer_number)]);
    setDrivers(dr.data.map((x) => x.name));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const createSheet = async () => {
    if (!nf.vehicle_reg) return toast.error("Select a vehicle");
    try {
      const { data } = await api.post("/weekly-walkarounds", { ...nf, week_start: mondayOf(nf.week_start) });
      toast.success("Weekly sheet created");
      setNewOpen(false); setNf({ vehicle_reg: "", driver_name: "", week_start: mondayOf(), mileage_start: "" });
      await load();
      setEdit(data);
    } catch { toast.error("Could not create sheet"); }
  };

  const remove = async (id) => { await api.delete(`/weekly-walkarounds/${id}`); toast.success("Sheet removed"); load(); };

  return (
    <div data-testid="weekly-walkaround-page">
      <div className="flex justify-end gap-2 mb-4">
        <Button data-testid="add-weekly-button" onClick={() => setNewOpen(true)} className="bg-black hover:bg-slate-800 rounded-md gap-2">
          <CalendarRange size={16} /> New Weekly Sheet
        </Button>
      </div>

      {items.length === 0 ? (
        <Empty icon={CalendarRange} text="No weekly walkaround sheets yet. One sheet covers a full Mon–Sun week per vehicle." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((a) => {
            const done = daysDone(a);
            const defs = defectCount(a);
            return (
              <div key={a.id} data-testid="weekly-card" className="bg-white border border-slate-200 rounded-md p-5">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-heading font-bold text-lg tracking-tight">{a.vehicle_reg || "—"}</h3>
                      <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${defs ? "text-amber-700 bg-amber-50" : "text-green-700 bg-green-50"}`}>{defs ? `${defs} defect(s)` : "Nil defect"}</span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">Week commencing {a.week_start}{a.driver_name ? ` · ${a.driver_name}` : ""}</p>
                  </div>
                  <button data-testid="delete-weekly-button" onClick={() => remove(a.id)} className="text-slate-400 hover:text-red-600 p-1"><Trash2 size={15} /></button>
                </div>
                <div className="flex items-center gap-1 mt-3">
                  {DAYS.map(([k, lbl], i) => {
                    const filled = (a.days?.[k]?.checklist || []).length > 0;
                    const hasDefect = (a.days?.[k]?.checklist || []).some((c) => !c.ok);
                    const missed = isMissed(a, i, k);
                    const cls = filled
                      ? (hasDefect ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700")
                      : missed ? "bg-red-100 text-red-600" : "bg-slate-100 text-slate-400";
                    return (
                      <div key={k} data-testid={`weekly-card-day-${k}`} className={`flex-1 text-center text-[10px] font-bold py-1.5 rounded ${cls}`}>{lbl}</div>
                    );
                  })}
                </div>
                <p className="text-xs text-slate-400 mt-2">
                  {done}/7 days recorded · {total(a.mileage_start, a.mileage_finish)} mi total
                  {missedCount(a) > 0 && <span data-testid="weekly-missed-flag" className="text-red-600 font-semibold"> · {missedCount(a)} missed day(s)</span>}
                </p>
                <div className="flex gap-2 mt-4">
                  <Button data-testid="edit-weekly-button" onClick={() => setEdit(a)} variant="outline" size="sm" className="rounded-md flex-1">Open / Edit</Button>
                  <Button data-testid="download-weekly-button" onClick={() => downloadPdf(`/weekly-walkarounds/${a.id}/sheet`, `weekly-${(a.vehicle_reg || "veh").replace(/ /g, "_")}-${a.week_start}.pdf`)} variant="outline" size="sm" className="rounded-md gap-1.5"><FileDown size={14} /> PDF</Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* New sheet dialog */}
      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>New weekly walkaround sheet</DialogTitle>
            <DialogDescription>Create a Mon–Sun check sheet for one vehicle. It snaps to the Monday of the chosen week.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Vehicle *">
              <Select value={nf.vehicle_reg} onValueChange={(v) => setNf({ ...nf, vehicle_reg: v })}>
                <SelectTrigger data-testid="weekly-reg"><SelectValue placeholder={assets.length ? "Select" : "Add a vehicle first"} /></SelectTrigger>
                <SelectContent>{assets.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Driver">
              <Select value={nf.driver_name} onValueChange={(v) => setNf({ ...nf, driver_name: v })}>
                <SelectTrigger data-testid="weekly-driver"><SelectValue placeholder={drivers.length ? "Select" : "Add a driver first"} /></SelectTrigger>
                <SelectContent>{drivers.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Week commencing"><Input data-testid="weekly-week" type="date" value={nf.week_start} onChange={(e) => setNf({ ...nf, week_start: e.target.value })} /></Field>
            <Field label="Mileage start"><Input data-testid="weekly-mileage-start" value={nf.mileage_start} onChange={(e) => setNf({ ...nf, mileage_start: e.target.value })} /></Field>
          </div>
          <p className="text-xs text-slate-400">The sheet snaps to the Monday of the chosen week. Drivers can fill it day-by-day from the driver app, or you can complete it here.</p>
          <DialogFooter><Button data-testid="save-weekly-button" onClick={createSheet} className="bg-black hover:bg-slate-800">Create sheet</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {edit && <WeeklyEditor record={edit} onClose={() => setEdit(null)} onSaved={load} />}
    </div>
  );
}

function WeeklyEditor({ record, onClose, onSaved }) {
  const [rec, setRec] = useState(() => JSON.parse(JSON.stringify(record)));
  const [busy, setBusy] = useState(false);

  const setCell = (dayKey, it) => {
    setRec((r) => {
      const days = { ...(r.days || {}) };
      const day = { ...(days[dayKey] || { date: r.week_start, checklist: [] }) };
      const cl = [...(day.checklist || [])];
      const i = cl.findIndex((c) => c.item === it.item);
      const cur = i >= 0 ? cl[i].ok : null;
      const next = cur === null ? true : cur === true ? false : null; // cycle blank→✓→✗→blank
      if (next === null) { if (i >= 0) cl.splice(i, 1); }
      else if (i >= 0) cl[i] = { ...cl[i], ok: next };
      else cl.push({ section: it.section, item: it.item, ok: next, note: "" });
      day.checklist = cl;
      day.result = cl.some((c) => !c.ok) ? "defects_found" : "nil_defect";
      days[dayKey] = day;
      return { ...r, days };
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/weekly-walkarounds/${rec.id}`, {
        driver_name: rec.driver_name || "", mileage_start: rec.mileage_start || "",
        mileage_finish: rec.mileage_finish || "", days: rec.days || {},
        fault_reporting: rec.fault_reporting || "", driver_signature: rec.driver_signature || "",
      });
      toast.success("Weekly sheet saved");
      await onSaved(); onClose();
    } catch { toast.error("Could not save"); }
    setBusy(false);
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto" data-testid="weekly-editor">
        <DialogHeader><DialogTitle>Weekly sheet — {rec.vehicle_reg} · w/c {rec.week_start}</DialogTitle>
          <DialogDescription>Tap each cell to record ✓ or ✗ per day, add mileage, fault notes and the driver signature.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-3 gap-4">
          <Field label="Driver"><Input data-testid="weekly-edit-driver" value={rec.driver_name || ""} onChange={(e) => setRec({ ...rec, driver_name: e.target.value })} /></Field>
          <Field label="Mileage start"><Input data-testid="weekly-edit-mstart" value={rec.mileage_start || ""} onChange={(e) => setRec({ ...rec, mileage_start: e.target.value })} /></Field>
          <Field label="Mileage finish"><Input data-testid="weekly-edit-mfinish" value={rec.mileage_finish || ""} onChange={(e) => setRec({ ...rec, mileage_finish: e.target.value })} /></Field>
        </div>
        <p className="text-xs text-slate-400 -mt-2">Total this week: <span className="font-semibold text-slate-600">{total(rec.mileage_start, rec.mileage_finish)} mi</span> · Tap a cell to cycle blank → ✓ → ✗</p>

        <div className="overflow-x-auto border border-slate-200 rounded-md">
          <table className="w-full text-sm" data-testid="weekly-grid">
            <thead>
              <tr className="bg-slate-900 text-white">
                <th className="text-left px-3 py-2 font-semibold sticky left-0 bg-slate-900">Check item</th>
                {DAYS.map(([k, lbl]) => <th key={k} className="px-2 py-2 font-semibold text-center w-12">{lbl}</th>)}
              </tr>
            </thead>
            <tbody>
              {CHECKLIST.map((sec) => (
                <Fragment key={sec.section}>
                  <tr className="bg-slate-100"><td colSpan={8} className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-600">{sec.section}</td></tr>
                  {sec.items.map((item) => (
                    <tr key={item} className="border-t border-slate-100">
                      <td className="px-3 py-1.5 text-slate-700 sticky left-0 bg-white">{item}</td>
                      {DAYS.map(([k]) => {
                        const v = cellFor(rec, k, item);
                        return (
                          <td key={k} className="px-1 py-1 text-center">
                            <button
                              data-testid={`weekly-cell-${k}`}
                              onClick={() => setCell(k, { section: sec.section, item })}
                              className={`w-8 h-7 rounded flex items-center justify-center mx-auto border ${v === true ? "bg-green-600 border-green-600 text-white" : v === false ? "bg-red-600 border-red-600 text-white" : "border-slate-200 text-slate-300 hover:bg-slate-50"}`}
                            >
                              {v === true ? <Check size={14} /> : v === false ? <X size={14} /> : <Minus size={12} />}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        <Field label="Fault Reporting / Action Taken"><Textarea data-testid="weekly-fault" value={rec.fault_reporting || ""} onChange={(e) => setRec({ ...rec, fault_reporting: e.target.value })} placeholder="Details of any defects and action taken…" /></Field>
        <div><SignaturePad label="Driver signature (for the week)" testid="weekly-signature" value={rec.driver_signature || ""} onChange={(v) => setRec({ ...rec, driver_signature: v })} /></div>

        <DialogFooter><Button data-testid="save-weekly-edit-button" onClick={save} disabled={busy} className="bg-black hover:bg-slate-800">{busy ? "Saving…" : "Save sheet"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function WeeklyWalkaround() { return <WeeklyWalkaroundPanel />; }
