import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, CalendarDays, Wrench, CheckCircle2, FileWarning, GraduationCap, ShieldCheck, Gauge, Plus, Flag, Trash2, Pencil, Cog, ArrowRight, ClipboardCheck, Palmtree } from "lucide-react";
import {
  startOfMonth, endOfMonth, startOfWeek, endOfWeek, eachDayOfInterval,
  format, isSameMonth, isToday, addMonths, subMonths, parseISO, isSameDay,
} from "date-fns";
import { cn } from "@/lib/utils";
import { MaintenanceQuickAdd } from "@/components/MaintenanceQuickAdd";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const TYPE_META = {
  pmi_due: { icon: Wrench, label: "PMI Due" },
  pmi_done: { icon: CheckCircle2, label: "PMI Completed" },
  defect: { icon: FileWarning, label: "Defect" },
  training: { icon: GraduationCap, label: "Training Expiry" },
  insurance: { icon: ShieldCheck, label: "Insurance Renewal" },
  tacho: { icon: Gauge, label: "Tacho Download" },
  wheel: { icon: Wrench, label: "Wheel Security" },
  service: { icon: Cog, label: "Service" },
  walkaround: { icon: ClipboardCheck, label: "Daily Check" },
  vehicle: { icon: Gauge, label: "Vehicle" },
  driver: { icon: ShieldCheck, label: "Driver" },
  holiday: { icon: Palmtree, label: "Holiday" },
  custom: { icon: Flag, label: "Event" },
};

const dotColor = (status) => (status === "expired" ? "bg-red-500" : status === "due_soon" ? "bg-yellow-500" : "bg-green-500");
const pillColor = (status) => (status === "expired" ? "bg-red-100 text-red-700" : status === "due_soon" ? "bg-yellow-100 text-yellow-800" : "bg-green-100 text-green-700");

// Where each auto-generated event type lives so the user can edit it at source.
const EVENT_LINK = {
  pmi_due: "/maintenance?tab=pmi",
  pmi_done: "/maintenance?tab=pmi",
  wheel: "/maintenance?tab=wheel",
  service: "/maintenance?tab=service",
  walkaround: "/maintenance?tab=walkaround",
  defect: "/maintenance?tab=defects",
  training: "/office?tab=training",
  insurance: "/office?tab=insurance",
  tacho: "/tacho",
  vehicle: "/vehicles",
  driver: "/drivers",
};

export default function Calendar() {
  const navigate = useNavigate();
  const [cursor, setCursor] = useState(new Date());
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(new Date());
  const [dayOpen, setDayOpen] = useState(false);
  const [evtOpen, setEvtOpen] = useState(false);
  const [evtForm, setEvtForm] = useState({ date: "", title: "", notes: "" });
  const [evtEditId, setEvtEditId] = useState(null);
  const [assets, setAssets] = useState([]);
  const [vehicleRegs, setVehicleRegs] = useState([]);
  const [driverNames, setDriverNames] = useState([]);
  const [maintOpen, setMaintOpen] = useState(false);
  const [evtMode, setEvtMode] = useState("event"); // event | tacho | holiday
  const [tachoForm, setTachoForm] = useState({ source_type: "Vehicle Unit", reference: "", last_download: "", frequency_days: 90 });
  const [holForm, setHolForm] = useState({ name: "", from_date: "", to_date: "", notes: "" });
  const [defectForm, setDefectForm] = useState({ vehicle_reg: "", reported_by: "", category: "General", severity: "minor", description: "", defect_date: "", odometer: "" });

  const loadEvents = () => api.get("/calendar").then((r) => setEvents(r.data));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    loadEvents();
    Promise.all([api.get("/vehicles"), api.get("/trailers"), api.get("/drivers")]).then(([v, t, dr]) => {
      const vr = v.data.map((x) => x.registration).filter(Boolean);
      setVehicleRegs([...vr, ...t.data.map((x) => x.trailer_number).filter(Boolean)]);
      setDriverNames(dr.data.map((x) => x.name).filter(Boolean));
      setAssets([...vr, ...t.data.map((x) => x.trailer_number)].filter(Boolean));
    });
  }, []);

  const openAddMaint = () => setMaintOpen(true);

  const openAddEvent = () => {
    setEvtForm({ date: format(selected, "yyyy-MM-dd"), title: "", notes: "" });
    setTachoForm({ source_type: "Vehicle Unit", reference: "", last_download: format(selected, "yyyy-MM-dd"), frequency_days: 90 });
    setHolForm({ name: "", from_date: format(selected, "yyyy-MM-dd"), to_date: format(selected, "yyyy-MM-dd"), notes: "" });
    setDefectForm({ vehicle_reg: "", reported_by: "", category: "General", severity: "minor", description: "", defect_date: format(selected, "yyyy-MM-dd"), odometer: "" });
    setEvtMode("event");
    setEvtEditId(null);
    setEvtOpen(true);
  };
  const openEditEvent = (ev) => {
    setEvtForm({ date: ev.date, title: ev.title, notes: ev.subtitle || "" });
    setEvtMode("event");
    setEvtEditId(ev.id);
    setEvtOpen(true);
  };
  const saveEvent = async (e) => {
    e.preventDefault();
    if (evtMode === "tacho") {
      if (!tachoForm.reference) { toast.error("Select a vehicle or driver"); return; }
      try {
        await api.post("/tacho", { ...tachoForm, frequency_days: Number(tachoForm.frequency_days) });
        toast.success("Tacho download logged — next due added to calendar");
        setEvtOpen(false); loadEvents();
      } catch { toast.error("Could not log tacho download"); }
      return;
    }
    if (evtMode === "holiday") {
      if (!holForm.name) { toast.error("Enter who the holiday is for"); return; }
      if (!holForm.from_date || !holForm.to_date) { toast.error("Enter from and to dates"); return; }
      try {
        await api.post("/holidays", holForm);
        toast.success("Holiday added across the date range");
        setEvtOpen(false); loadEvents();
      } catch { toast.error("Could not save holiday"); }
      return;
    }
    if (evtMode === "defect") {
      if (!defectForm.vehicle_reg) { toast.error("Select a vehicle"); return; }
      if (!defectForm.description) { toast.error("Enter a description"); return; }
      try {
        await api.post("/defects", { ...defectForm, defect_date: defectForm.defect_date || null, attachments: [] });
        toast.success("Defect logged & added to calendar");
        setEvtOpen(false); loadEvents();
      } catch { toast.error("Could not log defect"); }
      return;
    }
    try {
      if (evtEditId) { await api.put(`/calendar/events/${evtEditId}`, evtForm); toast.success("Event updated"); }
      else { await api.post("/calendar/events", evtForm); toast.success("Event added to calendar"); }
      setEvtOpen(false);
      loadEvents();
    } catch { toast.error("Could not save event"); }
  };
  const deleteEvent = async (id) => {
    try { await api.delete(`/calendar/events/${id}`); toast.success("Event removed"); loadEvents(); }
    catch { toast.error("Could not remove event"); }
  };

  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(cursor), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(cursor), { weekStartsOn: 1 });
    return eachDayOfInterval({ start, end });
  }, [cursor]);

  const eventsForDay = (day) => events.filter((e) => {
    try { return isSameDay(parseISO(e.date), day); } catch { return false; }
  });

  const selectedEvents = eventsForDay(selected);
  const openDay = (day) => { setSelected(day); setDayOpen(true); };

  const renderEvent = (e, i) => {
    const M = TYPE_META[e.type] || TYPE_META.defect;
    const link = e.type !== "custom" ? EVENT_LINK[e.type] : null;
    return (
      <div key={`${e.date}-${e.type}-${e.title}-${i}`} className="flex items-start gap-3 border border-slate-100 rounded-md p-3">
        <M.icon size={16} className="text-slate-500 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-900">{e.title}</p>
          <p className="text-xs text-slate-500">{e.subtitle}</p>
          {link && (
            <button
              data-testid="calendar-view-record-button"
              onClick={() => navigate(link)}
              className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-slate-900"
            >
              View / edit record <ArrowRight size={12} />
            </button>
          )}
        </div>
        <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0", pillColor(e.status))}>{M.label}</span>
        {e.type === "custom" && e.id && (
          <div className="flex items-center gap-1.5 shrink-0">
            <button data-testid="edit-event-button" onClick={() => openEditEvent(e)} className="text-slate-300 hover:text-slate-900"><Pencil size={14} /></button>
            <button data-testid="delete-event-button" onClick={() => deleteEvent(e.id)} className="text-slate-300 hover:text-red-600"><Trash2 size={14} /></button>
          </div>
        )}
        {e.type === "holiday" && e.id && (
          <button data-testid="delete-holiday-button" onClick={() => deleteHoliday(e.id)} className="text-slate-300 hover:text-red-600 shrink-0"><Trash2 size={14} /></button>
        )}
      </div>
    );
  };

  return (
    <div data-testid="calendar-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance</p>
          <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Calendar</h1>
          <p className="text-slate-500 text-sm mt-1">PMI inspections & driver defect reports</p>
        </div>
        <div className="flex items-center gap-2">
          <Button data-testid="cal-prev" variant="outline" size="icon" className="border-slate-300" onClick={() => setCursor(subMonths(cursor, 1))}><ChevronLeft size={18} /></Button>
          <span data-testid="cal-month-label" className="font-heading font-bold text-lg tracking-tight w-40 text-center">{format(cursor, "MMMM yyyy")}</span>
          <Button data-testid="cal-next" variant="outline" size="icon" className="border-slate-300" onClick={() => setCursor(addMonths(cursor, 1))}><ChevronRight size={18} /></Button>
          <Button data-testid="cal-today" variant="outline" className="border-slate-300 ml-2" onClick={() => { setCursor(new Date()); setSelected(new Date()); }}>Today</Button>
          <Button data-testid="cal-add-maintenance" variant="outline" className="border-slate-300 rounded-md gap-2 ml-1" onClick={openAddMaint}><Wrench size={16} /> Maintenance</Button>
          <Button data-testid="cal-add-event" className="bg-black hover:bg-slate-800 rounded-md gap-2 ml-1" onClick={openAddEvent}><Plus size={16} /> Add Event</Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Grid */}
        <div className="lg:col-span-3 bg-white border border-slate-200 rounded-md overflow-hidden animate-in-up">
          <div className="grid grid-cols-7 bg-slate-50 border-b border-slate-200">
            {WEEKDAYS.map((d) => (
              <div key={d} className="px-2 py-2.5 text-center text-xs uppercase tracking-wider text-slate-500 font-semibold">{d}</div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {days.map((day) => {
              const evs = eventsForDay(day);
              const inMonth = isSameMonth(day, cursor);
              const isSel = isSameDay(day, selected);
              return (
                <button
                  key={day.toISOString()}
                  data-testid="calendar-day"
                  onClick={() => openDay(day)}
                  className={cn(
                    "min-h-[120px] border-b border-r border-slate-100 p-1.5 text-left align-top transition-colors relative",
                    !inMonth && "bg-slate-50/60 text-slate-300",
                    isSel && "ring-2 ring-inset ring-black",
                    "hover:bg-slate-50"
                  )}
                >
                  <span className={cn(
                    "inline-flex items-center justify-center w-6 h-6 text-xs font-semibold rounded-full",
                    isToday(day) ? "bg-black text-white" : inMonth ? "text-slate-700" : "text-slate-300"
                  )}>{format(day, "d")}</span>
                  <div className="mt-1 space-y-0.5">
                    {evs.slice(0, 4).map((e, i) => (
                      <div key={`${e.date}-${e.type}-${e.title}-${i}`} className="flex items-center gap-1 truncate">
                        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dotColor(e.status))} />
                        <span className="text-[10px] text-slate-600 truncate">{e.title}</span>
                      </div>
                    ))}
                    {evs.length > 4 && <span className="text-[10px] text-slate-400">+{evs.length - 4} more</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Day detail */}
        <div className="bg-white border border-slate-200 rounded-md p-4 animate-in-up" style={{ animationDelay: "80ms" }}>
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-2 min-w-0">
              <CalendarDays size={16} className="text-slate-900 shrink-0" />
              <h3 className="font-heading font-bold text-base tracking-tight truncate">{format(selected, "EEE d")}</h3>
            </div>
            <Button data-testid="day-add-maintenance" size="sm" variant="outline" className="border-slate-300 rounded-md gap-1.5 h-8" onClick={openAddMaint}><Wrench size={14} /> Add</Button>
          </div>
          <p className="text-xs text-slate-400 mb-4">{selectedEvents.length} event{selectedEvents.length !== 1 && "s"}{selectedEvents.length > 0 && " · click a day to enlarge"}</p>
          {selectedEvents.length === 0 ? (
            <p className="text-sm text-slate-400 py-6 text-center">Nothing scheduled for this day.</p>
          ) : (
            <div className="space-y-3" data-testid="day-events">
              {selectedEvents.map(renderEvent)}
            </div>
          )}

          <div className="mt-6 pt-4 border-t border-slate-100 space-y-2">
            <p className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">Legend</p>
            <Legend color="bg-red-500" label="Overdue / safety-critical" />
            <Legend color="bg-yellow-500" label="Due soon / logged defect" />
            <Legend color="bg-green-500" label="Completed / on track" />
          </div>
        </div>
      </div>

      {/* Enlarged day view */}
      <Dialog open={dayOpen} onOpenChange={setDayOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading flex items-center gap-2"><CalendarDays size={18} /> {format(selected, "EEEE d MMMM yyyy")}</DialogTitle>
            <DialogDescription>{selectedEvents.length} event{selectedEvents.length !== 1 && "s"} scheduled for this day</DialogDescription>
          </DialogHeader>
          {selectedEvents.length === 0 ? (
            <p className="text-sm text-slate-400 py-6 text-center">Nothing scheduled for this day.</p>
          ) : (
            <div className="space-y-3" data-testid="day-dialog-events">
              {selectedEvents.map(renderEvent)}
            </div>
          )}
          <DialogFooter>
            <Button data-testid="day-dialog-add" variant="outline" className="border-slate-300 rounded-md gap-1.5" onClick={() => { setDayOpen(false); openAddMaint(); }}><Wrench size={14} /> Add maintenance for this day</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={evtOpen} onOpenChange={setEvtOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">{evtEditId ? "Edit Calendar Event" : "Add to Calendar"}</DialogTitle>
            <DialogDescription className="sr-only">Add a custom event or log a tacho download</DialogDescription>
          </DialogHeader>

          {!evtEditId && (
            <div className="flex gap-2" data-testid="event-mode-picker">
              <button type="button" data-testid="event-mode-event" onClick={() => setEvtMode("event")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${evtMode === "event" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
                <Flag size={13} /> General event
              </button>
              <button type="button" data-testid="event-mode-tacho" onClick={() => setEvtMode("tacho")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${evtMode === "tacho" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
                <Gauge size={13} /> Tacho download
              </button>
              <button type="button" data-testid="event-mode-holiday" onClick={() => setEvtMode("holiday")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${evtMode === "holiday" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
                <Palmtree size={13} /> Holiday
              </button>
              <button type="button" data-testid="event-mode-defect" onClick={() => setEvtMode("defect")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors ${evtMode === "defect" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"}`}>
                <FileWarning size={13} /> Defect
              </button>
            </div>
          )}

          <form onSubmit={saveEvent} className="space-y-4">
            {evtMode === "event" ? (
              <>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Date</label>
                  <Input data-testid="event-date" type="date" required value={evtForm.date} onChange={(e) => setEvtForm({ ...evtForm, date: e.target.value })} />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Title</label>
                  <Input data-testid="event-title" required value={evtForm.title} onChange={(e) => setEvtForm({ ...evtForm, title: e.target.value })} placeholder="e.g. Tacho analysis meeting" />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Notes</label>
                  <Textarea data-testid="event-notes" rows={2} value={evtForm.notes} onChange={(e) => setEvtForm({ ...evtForm, notes: e.target.value })} />
                </div>
              </>
            ) : evtMode === "tacho" ? (
              <>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Download type</label>
                  <Select value={tachoForm.source_type} onValueChange={(v) => setTachoForm({ ...tachoForm, source_type: v, reference: "", frequency_days: v === "Driver Card" ? 28 : 90 })}>
                    <SelectTrigger data-testid="tacho-source"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Vehicle Unit">Vehicle Unit (truck)</SelectItem>
                      <SelectItem value="Driver Card">Driver Card</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">{tachoForm.source_type === "Driver Card" ? "Driver" : "Vehicle / trailer"}</label>
                  <Select value={tachoForm.reference} onValueChange={(v) => setTachoForm({ ...tachoForm, reference: v })}>
                    <SelectTrigger data-testid="tacho-reference"><SelectValue placeholder="Select…" /></SelectTrigger>
                    <SelectContent>
                      {(tachoForm.source_type === "Driver Card" ? driverNames : vehicleRegs).map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Download date</label>
                    <Input data-testid="tacho-date" type="date" value={tachoForm.last_download} onChange={(e) => setTachoForm({ ...tachoForm, last_download: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Next due in (days)</label>
                    <Input data-testid="tacho-freq" type="number" min="1" value={tachoForm.frequency_days} onChange={(e) => setTachoForm({ ...tachoForm, frequency_days: e.target.value })} />
                  </div>
                </div>
                <p className="text-xs text-slate-400">Logs the download and schedules the next due date on the calendar & Tacho Portal. (Driver cards typically every 28 days, vehicle units every 90 days.)</p>
              </>
            ) : evtMode === "holiday" ? (
              <>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Who is it for?</label>
                  <Select value={holForm.name} onValueChange={(v) => setHolForm({ ...holForm, name: v })}>
                    <SelectTrigger data-testid="holiday-name"><SelectValue placeholder="Select driver or type below" /></SelectTrigger>
                    <SelectContent>{driverNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                  </Select>
                  <Input data-testid="holiday-name-input" className="mt-2" value={holForm.name} onChange={(e) => setHolForm({ ...holForm, name: e.target.value })} placeholder="…or type a name / reason (e.g. John Smith, Office closed)" />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">From</label>
                    <Input data-testid="holiday-from" type="date" required value={holForm.from_date} onChange={(e) => setHolForm({ ...holForm, from_date: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">To</label>
                    <Input data-testid="holiday-to" type="date" required value={holForm.to_date} onChange={(e) => setHolForm({ ...holForm, to_date: e.target.value })} />
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Notes</label>
                  <Input data-testid="holiday-notes" value={holForm.notes} onChange={(e) => setHolForm({ ...holForm, notes: e.target.value })} placeholder="Optional" />
                </div>
                <p className="text-xs text-slate-400">Adds the holiday to every day between the two dates automatically.</p>
              </>
            ) : (
              <>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Vehicle *</label>
                  <Select value={defectForm.vehicle_reg} onValueChange={(v) => setDefectForm({ ...defectForm, vehicle_reg: v })}>
                    <SelectTrigger data-testid="cal-defect-vehicle"><SelectValue placeholder={vehicleRegs.length ? "Select vehicle / trailer" : "Add a vehicle first"} /></SelectTrigger>
                    <SelectContent>{vehicleRegs.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Reported by</label>
                    <Select value={defectForm.reported_by} onValueChange={(v) => setDefectForm({ ...defectForm, reported_by: v })}>
                      <SelectTrigger data-testid="cal-defect-reporter"><SelectValue placeholder={driverNames.length ? "Select driver" : "Add a driver first"} /></SelectTrigger>
                      <SelectContent>{driverNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Date</label>
                    <Input data-testid="cal-defect-date" type="date" value={defectForm.defect_date} onChange={(e) => setDefectForm({ ...defectForm, defect_date: e.target.value })} />
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Category</label>
                    <Select value={defectForm.category} onValueChange={(v) => setDefectForm({ ...defectForm, category: v })}>
                      <SelectTrigger data-testid="cal-defect-category"><SelectValue /></SelectTrigger>
                      <SelectContent>{["General", "Brakes", "Tyres & Wheels", "Lights", "Steering", "Bodywork", "Load Security", "Other"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Severity</label>
                    <Select value={defectForm.severity} onValueChange={(v) => setDefectForm({ ...defectForm, severity: v })}>
                      <SelectTrigger data-testid="cal-defect-severity"><SelectValue /></SelectTrigger>
                      <SelectContent>{[["minor", "Minor"], ["major", "Major"], ["safety_critical", "Safety Critical"]].map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">Description *</label>
                  <Textarea data-testid="cal-defect-description" rows={3} value={defectForm.description} onChange={(e) => setDefectForm({ ...defectForm, description: e.target.value })} placeholder="Describe the defect…" />
                </div>
                <p className="text-xs text-slate-400">Logs the defect (with AI safety triage) and pins it to this date on the calendar.</p>
              </>
            )}
            <DialogFooter><Button data-testid="save-event-button" type="submit" className="bg-black hover:bg-slate-800">{evtMode === "tacho" ? "Log Tacho Download" : evtMode === "holiday" ? "Add Holiday" : evtMode === "defect" ? "Log Defect" : evtEditId ? "Save Changes" : "Add Event"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <MaintenanceQuickAdd
        open={maintOpen}
        onOpenChange={setMaintOpen}
        defaultDate={format(selected, "yyyy-MM-dd")}
        assets={assets}
        onSaved={loadEvents}
      />
    </div>
  );
}

function Legend({ color, label }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-600">
      <span className={cn("w-2.5 h-2.5 rounded-full", color)} /> {label}
    </div>
  );
}
