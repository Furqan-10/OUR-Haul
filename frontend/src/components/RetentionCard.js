import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Archive, ShieldCheck, Clock } from "lucide-react";

export function RetentionCard() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);

  const load = async () => { try { const { data } = await api.get("/records-retention"); setData(data); } catch { /* noop */ } };
  useEffect(() => { load(); }, []);

  if (!data) return null;
  const { total_eligible, total_approaching, categories } = data;
  const flagged = total_eligible + total_approaching;

  return (
    <>
      <div data-testid="retention-card" className="bg-white border border-slate-200 rounded-md p-5 mb-6 animate-in-up">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${flagged ? "bg-amber-100 text-amber-600" : "bg-green-100 text-green-600"}`}>
              {flagged ? <Archive size={22} /> : <ShieldCheck size={22} />}
            </div>
            <div className="min-w-0">
              <h3 className="font-heading font-bold tracking-tight">Records Retention</h3>
              <p className="text-sm text-slate-500">
                {flagged ? (
                  <span data-testid="retention-summary">
                    <span className="text-amber-600 font-semibold">{total_eligible} past retention</span>
                    {total_approaching ? ` · ${total_approaching} approaching disposal` : ""}
                  </span>
                ) : (
                  <span data-testid="retention-summary">All records within their retention period</span>
                )}
              </p>
            </div>
          </div>
          <Button data-testid="retention-view-button" variant="outline" onClick={() => setOpen(true)} className="border-slate-300 rounded-md">View schedule</Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[92vh] overflow-y-auto" data-testid="retention-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Records retention schedule</DialogTitle>
            <DialogDescription>DVSA/RSA minimum retention periods. Records past their keep-until date can be archived; those due within 60 days are flagged.</DialogDescription>
          </DialogHeader>
          <div className="space-y-5 mt-2">
            {categories.map((c) => (
              <div key={c.label} data-testid="retention-category">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="font-semibold text-slate-900 text-sm">{c.label} <span className="text-slate-400 font-normal">· keep {c.retention_months} months</span></p>
                  <span className="text-xs text-slate-400">{c.total} on file</span>
                </div>
                {c.items.length === 0 ? (
                  <p className="text-xs text-slate-400">Nothing due — all within retention.</p>
                ) : (
                  <div className="space-y-1.5">
                    {c.items.map((it, i) => (
                      <div key={i} data-testid="retention-item" className="flex items-center gap-3 border border-slate-100 rounded-md px-3 py-2 text-sm">
                        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full shrink-0 ${it.state === "eligible" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`}>{it.state === "eligible" ? "Archive" : "Soon"}</span>
                        <span className="min-w-0 flex-1 truncate text-slate-700">{it.vehicle_reg} <span className="text-slate-400">· {it.record_date}</span></span>
                        <span className="text-xs text-slate-400 shrink-0 flex items-center gap-1"><Clock size={12} /> keep until {it.keep_until}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
