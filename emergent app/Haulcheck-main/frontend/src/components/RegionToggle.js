import { useAuth } from "@/context/AuthContext";
import { Globe } from "lucide-react";
import { toast } from "sonner";

// Prominent UK/Ireland region switcher for use on Dashboard, Operator, etc.
export function RegionToggle({ className = "" }) {
  const { user, updateRegion } = useAuth();
  const current = user?.region || "UK";
  const opts = [
    { c: "UK", label: "UK · DVSA" },
    { c: "IE", label: "IE · RSA" },
  ];
  const switchTo = async (c) => {
    if (c === current) return;
    try {
      await updateRegion(c);
      toast.success(`Switched to ${c === "UK" ? "United Kingdom (DVSA)" : "Ireland (RSA)"}`);
    } catch { toast.error("Could not switch region"); }
  };
  return (
    <div data-testid="region-toggle" className={`inline-flex items-center gap-2 ${className}`}>
      <Globe size={15} className="text-slate-400" />
      <div className="inline-flex rounded-md border border-slate-200 bg-white p-0.5">
        {opts.map((o) => (
          <button
            key={o.c}
            type="button"
            data-testid={`region-toggle-${o.c}`}
            onClick={() => switchTo(o.c)}
            className={`px-3 py-1.5 rounded text-xs font-semibold transition-colors ${
              current === o.c ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-900"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
