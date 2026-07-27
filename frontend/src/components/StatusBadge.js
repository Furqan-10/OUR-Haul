import { cn } from "@/lib/utils";

const MAP = {
  valid: { label: "Valid", cls: "bg-green-100 text-green-700" },
  due_soon: { label: "Due Soon", cls: "bg-yellow-100 text-yellow-800" },
  expired: { label: "Expired", cls: "bg-red-100 text-red-700" },
  unknown: { label: "Not Set", cls: "bg-slate-100 text-slate-500" },
  open: { label: "Open", cls: "bg-red-100 text-red-700" },
  monitoring: { label: "Monitoring", cls: "bg-yellow-100 text-yellow-800" },
  resolved: { label: "Resolved", cls: "bg-green-100 text-green-700" },
  minor: { label: "Minor", cls: "bg-slate-100 text-slate-600" },
  major: { label: "Major", cls: "bg-orange-100 text-orange-700" },
  safety_critical: { label: "Safety Critical", cls: "bg-red-100 text-red-700" },
};

export const StatusBadge = ({ status, testid }) => {
  const s = MAP[status] || MAP.unknown;
  return (
    <span data-testid={testid} className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", s.cls)}>
      {s.label}
    </span>
  );
};
