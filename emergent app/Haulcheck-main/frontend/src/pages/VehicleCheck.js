import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ExternalLink, Car, ShieldCheck, Gauge, AlertTriangle, Copy } from "lucide-react";
import { toast } from "sonner";

// Official government checkers (open in a new tab — no API key needed).
const CHECKERS = {
  UK: [
    { key: "mot", label: "MOT history & expiry", icon: Gauge, desc: "DVSA — check-mot.service.gov.uk", url: () => "https://www.check-mot.service.gov.uk/" },
    { key: "tax", label: "Vehicle tax & SORN", icon: Car, desc: "DVLA — vehicleenquiry.service.gov.uk", url: () => "https://vehicleenquiry.service.gov.uk/" },
    { key: "recall", label: "Safety recalls", icon: AlertTriangle, desc: "DVSA — check-vehicle-recalls", url: () => "https://www.check-vehicle-recalls.service.gov.uk/" },
  ],
  IE: [
    { key: "cvrt", label: "CVRT / CRW expiry", icon: ShieldCheck, desc: "RSA — operator.cvrt.ie", url: () => "https://operator.cvrt.ie/Vehicle/CRWExpiryTestReminder" },
    { key: "motortax", label: "Motor tax status", icon: Car, desc: "motortax.ie", url: () => "https://www.motortax.ie/OMT/omt.do" },
  ],
};

export function VehicleCheckPanel() {
  const { user } = useAuth();
  const [region, setRegion] = useState(user?.region === "IE" ? "IE" : "UK");
  const [reg, setReg] = useState("");

  const checkers = CHECKERS[region] || CHECKERS.UK;
  const copyReg = () => {
    if (!reg.trim()) return;
    navigator.clipboard?.writeText(reg.trim().toUpperCase());
    toast.success("Registration copied — paste it into the checker");
  };
  const open = (c) => {
    if (reg.trim()) copyReg();
    window.open(c.url(), "_blank", "noopener");
  };

  return (
    <div data-testid="vehicle-check-page" className="max-w-3xl">
      <div className="mb-6">
        <p className="text-sm text-slate-500 leading-relaxed">
          Check <span className="font-semibold text-slate-700">any</span> vehicle's roadworthiness before using a third-party / subcontractor's truck.
          Enter the registration, then open the official government checker. We'll copy the reg to your clipboard so you can paste it straight in.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-md p-5 sm:p-6 animate-in-up">
        <div className="flex gap-2 mb-4">
          {["UK", "IE"].map((r) => (
            <button key={r} data-testid={`vcheck-region-${r}`} onClick={() => setRegion(r)}
              className={`px-4 py-2 rounded-md text-sm font-semibold transition-all ${region === r ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
              {r === "UK" ? "🇬🇧 UK (DVSA)" : "🇮🇪 Ireland (RSA)"}
            </button>
          ))}
        </div>

        <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Vehicle registration</label>
        <div className="flex gap-2 mt-1.5">
          <Input data-testid="vcheck-reg-input" value={reg} onChange={(e) => setReg(e.target.value.toUpperCase())}
            placeholder={region === "IE" ? "e.g. 231-D-12345" : "e.g. AB12 CDE"} className="font-mono tracking-widest text-lg" />
          <Button data-testid="vcheck-copy" onClick={copyReg} variant="outline" className="rounded-md gap-1.5 shrink-0"><Copy size={15} /> Copy</Button>
        </div>

        <div className="grid sm:grid-cols-2 gap-3 mt-5">
          {checkers.map((c) => {
            const Icon = c.icon;
            return (
              <button key={c.key} data-testid={`vcheck-open-${c.key}`} onClick={() => open(c)}
                className="text-left border border-slate-200 rounded-md p-4 hover:border-slate-900 hover:shadow-sm transition-all group">
                <div className="flex items-center justify-between">
                  <Icon size={20} className="text-slate-700" />
                  <ExternalLink size={15} className="text-slate-300 group-hover:text-slate-900" />
                </div>
                <p className="font-semibold text-slate-900 mt-2 text-sm">{c.label}</p>
                <p className="text-xs text-slate-400 mt-0.5">{c.desc}</p>
              </button>
            );
          })}
        </div>

        <div className="mt-5 flex items-start gap-2 rounded-md bg-amber-50 border border-amber-200 px-4 py-2.5 text-xs text-amber-800">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span><span className="font-semibold">Insurance can't be checked online by plate</span> — the Motor Insurance Database (askMID) is not publicly searchable. Always ask a subcontractor for a current certificate/cover note.</span>
        </div>
      </div>
    </div>
  );
}

export default function VehicleCheck() { return <VehicleCheckPanel />; }
