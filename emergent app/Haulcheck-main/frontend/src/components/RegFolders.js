import { Folder, Layers } from "lucide-react";
import { cn } from "@/lib/utils";

// Normalise a registration for grouping/matching: uppercase + strip all whitespace.
// So "AB12 CDE", "ab12cde" and "AB12  CDE" all collapse to one folder.
export const normReg = (r) => (r || "").toString().toUpperCase().replace(/\s+/g, "");
export const matchesReg = (value, reg) => !value || normReg(reg) === value;

// Registration-number "folder" filter used across all Maintenance tabs.
// `value`/`onChange` operate on the NORMALISED registration key.
export function RegFolders({ items, field = "vehicle_reg", value, onChange, className = "" }) {
  // Group by normalised key, keep the first-seen display label for each.
  const groups = new Map();
  for (const it of items || []) {
    const raw = it[field];
    if (!raw) continue;
    const key = normReg(raw);
    if (!groups.has(key)) groups.set(key, { label: raw, count: 0 });
    groups.get(key).count += 1;
  }
  if (groups.size === 0) return null;
  const entries = [...groups.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label));

  const Pill = ({ v, label, count, icon: Icon }) => (
    <button
      type="button"
      data-testid={`reg-folder-${v || "all"}`}
      onClick={() => onChange(v)}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors",
        value === v
          ? "bg-slate-900 text-white border-slate-900"
          : "bg-white text-slate-600 border-slate-200 hover:border-slate-400 hover:text-slate-900"
      )}
    >
      <Icon size={13} /> {label}
      <span className={cn("ml-0.5 rounded px-1", value === v ? "bg-white/20" : "bg-slate-100 text-slate-500")}>{count}</span>
    </button>
  );

  return (
    <div className={cn("flex flex-wrap gap-2 mb-5", className)} data-testid="reg-folders">
      <Pill v="" label="All vehicles" count={(items || []).filter((i) => i[field]).length} icon={Layers} />
      {entries.map(([key, g]) => (
        <Pill key={key} v={key} label={g.label} count={g.count} icon={Folder} />
      ))}
    </div>
  );
}
