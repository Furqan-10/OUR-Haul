import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Bell, Mail, Plus, Trash2, Send } from "lucide-react";
import { toast } from "sonner";

const AREA_LABELS = {
  fleet: "Fleet (MOT/CVRT, Tax, Service)",
  drivers: "Drivers (Licence, CPC)",
  tacho: "Tacho",
  pmi: "PMI Inspections",
  insurance: "Insurance",
  training: "Training",
  documents: "Documents",
  defects: "Defects",
};
const ALL_AREAS = Object.keys(AREA_LABELS);
const PRESETS = {
  "Transport Manager": [...ALL_AREAS],
  Driver: ["drivers", "tacho", "training"],
  Maintenance: ["fleet", "pmi", "defects"],
};

export default function Reminders() {
  const [recipients, setRecipients] = useState([]);
  const [newEmail, setNewEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    api.get("/reminders/settings").then((r) => setRecipients(r.data.recipients || []));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const isValidEmail = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);

  const addEmail = () => {
    const e = newEmail.trim().toLowerCase();
    if (!isValidEmail(e)) return toast.error("Enter a valid email address");
    if (recipients.some((r) => r.email === e)) return toast.error("Email already added");
    setRecipients([...recipients, { email: e, areas: [...ALL_AREAS], frequency: "daily" }]);
    setNewEmail("");
  };

  const removeEmail = (email) => setRecipients(recipients.filter((r) => r.email !== email));

  const updateRecipient = (email, patch) =>
    setRecipients(recipients.map((r) => (r.email === email ? { ...r, ...patch } : r)));

  const toggleArea = (email, area) => {
    const r = recipients.find((x) => x.email === email);
    const areas = r.areas.includes(area) ? r.areas.filter((a) => a !== area) : [...r.areas, area];
    updateRecipient(email, { areas });
  };

  const applyPreset = (email, preset) => updateRecipient(email, { areas: [...PRESETS[preset]] });

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/reminders/settings", { recipients });
      toast.success("Preferences saved");
    } catch { toast.error("Could not save preferences"); }
    finally { setSaving(false); }
  };

  const sendNow = async () => {
    if (recipients.length === 0) return toast.error("Add at least one recipient first");
    setSending(true);
    try {
      await api.put("/reminders/settings", { recipients });
      const r = await api.post("/reminders/send");
      toast.success(`Reminder sent to ${r.data.recipient_count} recipient(s)`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not send reminder");
    } finally { setSending(false); }
  };

  return (
    <div data-testid="reminders-page">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance · Notifications</p>
          <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Email Reminders</h1>
          <p className="text-slate-500 text-sm mt-1">Choose who gets which compliance alerts, and how often.</p>
        </div>
        <Button data-testid="send-reminder-button" onClick={sendNow} disabled={sending} className="bg-black hover:bg-slate-800 rounded-md gap-2">
          <Send size={16} /> {sending ? "Sending…" : "Send reminder now"}
        </Button>
      </div>

      <div className="bg-white border border-slate-200 rounded-md p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Mail size={18} className="text-slate-900" />
          <h3 className="font-heading font-bold text-lg tracking-tight">Add recipient</h3>
        </div>
        <div className="flex gap-2">
          <Input
            data-testid="recipient-email-input"
            type="email"
            placeholder="name@company.com"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } }}
          />
          <Button data-testid="add-recipient-button" onClick={addEmail} variant="outline" className="rounded-md gap-1 shrink-0">
            <Plus size={16} /> Add
          </Button>
        </div>
        <p className="text-xs text-slate-400 mt-2">New recipients receive all areas as a daily 30-day alert by default.</p>
      </div>

      {recipients.length === 0 ? (
        <p className="text-sm text-slate-400 py-10 text-center border border-dashed border-slate-200 rounded-md" data-testid="no-recipients">
          No recipients yet. Add one above to start sending compliance reminders.
        </p>
      ) : (
        <div className="space-y-4" data-testid="recipient-list">
          {recipients.map((r) => (
            <div key={r.email} className="bg-white border border-slate-200 rounded-md p-5" data-testid={`recipient-card-${r.email}`}>
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div className="flex items-center gap-2">
                  <span className="w-8 h-8 rounded-full bg-slate-900 text-white text-xs flex items-center justify-center font-bold uppercase">{r.email[0]}</span>
                  <span className="text-sm font-semibold text-slate-800">{r.email}</span>
                </div>
                <div className="flex items-center gap-3">
                  <Select value={r.frequency} onValueChange={(v) => updateRecipient(r.email, { frequency: v })}>
                    <SelectTrigger data-testid={`frequency-${r.email}`} className="w-[180px] h-9"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="daily">Daily 30-day alerts</SelectItem>
                      <SelectItem value="weekly">Weekly summary</SelectItem>
                    </SelectContent>
                  </Select>
                  <button data-testid={`remove-recipient-${r.email}`} onClick={() => removeEmail(r.email)} className="text-slate-400 hover:text-red-600 transition-colors">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className="text-xs text-slate-500 font-semibold mr-1">Presets:</span>
                {Object.keys(PRESETS).map((p) => (
                  <button
                    key={p}
                    data-testid={`preset-${p}-${r.email}`}
                    onClick={() => applyPreset(r.email, p)}
                    className="text-xs px-2.5 py-1 rounded-full border border-slate-300 text-slate-600 hover:bg-slate-900 hover:text-white hover:border-slate-900 transition-colors"
                  >{p}</button>
                ))}
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2.5 pt-3 border-t border-slate-100">
                {ALL_AREAS.map((area) => (
                  <label key={area} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                    <Checkbox
                      data-testid={`area-${area}-${r.email}`}
                      checked={r.areas.includes(area)}
                      onCheckedChange={() => toggleArea(r.email, area)}
                    />
                    <span>{AREA_LABELS[area]}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}

          <Button data-testid="save-recipients-button" onClick={save} disabled={saving} className="w-full bg-slate-900 hover:bg-slate-700 rounded-md">
            {saving ? "Saving…" : "Save preferences"}
          </Button>
        </div>
      )}

      <div className="bg-slate-50 border border-slate-200 rounded-md p-5 mt-6">
        <div className="flex items-center gap-2 mb-2">
          <Bell size={16} className="text-slate-900" />
          <h3 className="font-heading font-bold text-sm tracking-tight">How reminders work</h3>
        </div>
        <p className="text-xs text-slate-500 leading-relaxed">
          <strong>Daily</strong> recipients get an email once when an item enters the 30-day window (no repeats). <strong>Weekly</strong> recipients get a full summary every Monday. Each recipient only receives the compliance areas ticked above. Use <strong>Send reminder now</strong> to email everyone their current digest immediately.
        </p>
      </div>
    </div>
  );
}
