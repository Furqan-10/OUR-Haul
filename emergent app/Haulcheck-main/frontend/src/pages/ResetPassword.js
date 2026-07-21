import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Truck, ShieldCheck, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();

  const [state, setState] = useState("verifying"); // verifying | valid | invalid | done
  const [info, setInfo] = useState({ email: "" });
  const [error, setError] = useState("");
  const [form, setForm] = useState({ password: "", confirm: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) { setState("invalid"); setError("Missing reset token."); return; }
    api.get("/auth/reset-password/verify", { params: { token } })
      .then((r) => { setInfo(r.data); setState("valid"); })
      .catch((err) => { setState("invalid"); setError(err.response?.data?.detail || "This reset link is invalid or has expired."); });
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (form.password.length < 6) { toast.error("Password must be at least 6 characters"); return; }
    if (form.password !== form.confirm) { toast.error("Passwords do not match"); return; }
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, password: form.password });
      setState("done");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not reset your password");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2" data-testid="reset-password-page">
      {/* Left brand panel */}
      <div className="relative hidden lg:flex flex-col justify-between bg-slate-900 text-white p-12 overflow-hidden">
        <div className="absolute inset-0 opacity-25 bg-cover bg-center"
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1766561993607-58d30bf6b86f?crop=entropy&cs=srgb&fm=jpg&q=85&w=1400')" }} />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-slate-900/70 to-slate-900/40" />
        <div className="relative flex items-center gap-2">
          <Truck size={28} />
          <span className="font-heading font-black text-xl tracking-tight">HAULCHECK</span>
        </div>
        <div className="relative">
          <h1 className="font-heading text-4xl sm:text-5xl font-black tracking-tight leading-[1.05]">
            Back to<br />bulletproof.
          </h1>
          <p className="mt-5 text-slate-300 max-w-md text-base">
            Choose a new password and get straight back to keeping your fleet compliant.
          </p>
          <div className="mt-8 flex items-center gap-2 text-sm text-slate-400">
            <ShieldCheck size={18} /> DVSA &amp; RSA-aligned compliance tracking
          </div>
        </div>
        <div className="relative text-xs text-slate-500 tracking-widest uppercase">Fleet Compliance Control Room</div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-6 sm:p-10 bg-white">
        <div className="w-full max-w-md animate-in-up">
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <Truck size={26} className="text-slate-900" />
            <span className="font-heading font-black text-lg tracking-tight">HAULCHECK</span>
          </div>

          {state === "verifying" && (
            <div className="text-slate-500 flex flex-col items-center gap-3 py-16" data-testid="reset-verifying">
              <Truck className="animate-pulse" size={32} />
              <p className="text-sm tracking-widest uppercase">Verifying link…</p>
            </div>
          )}

          {state === "invalid" && (
            <div data-testid="reset-invalid" className="text-center py-10">
              <AlertTriangle size={40} className="text-amber-500 mx-auto" />
              <h2 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mt-4">Link unavailable</h2>
              <p className="text-slate-500 mt-2 text-sm">{error}</p>
              <Button data-testid="reset-goto-login-button" onClick={() => navigate("/login")} variant="outline" className="mt-6 rounded-md">Back to sign in</Button>
            </div>
          )}

          {state === "done" && (
            <div data-testid="reset-done" className="text-center py-10">
              <CheckCircle2 size={40} className="text-emerald-500 mx-auto" />
              <h2 className="font-heading text-2xl font-bold tracking-tight text-slate-900 mt-4">Password updated</h2>
              <p className="text-slate-500 mt-2 text-sm">Your password has been reset. You can now sign in with your new password.</p>
              <Button data-testid="reset-signin-button" onClick={() => navigate("/login")} className="mt-6 rounded-md bg-black hover:bg-slate-800 text-white">Go to sign in</Button>
            </div>
          )}

          {state === "valid" && (
            <>
              <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Set a new password</h2>
              <p className="text-slate-500 mt-2 text-sm">
                For <span className="font-semibold text-slate-700">{info.email}</span>. Choose a password you'll remember.
              </p>
              <form onSubmit={submit} className="space-y-4 mt-6">
                <div>
                  <Label htmlFor="rp-password">New password</Label>
                  <Input data-testid="reset-password-input" id="rp-password" type="password" required value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="At least 6 characters" className="mt-1.5" />
                </div>
                <div>
                  <Label htmlFor="rp-confirm">Confirm password</Label>
                  <Input data-testid="reset-confirm-input" id="rp-confirm" type="password" required value={form.confirm}
                    onChange={(e) => setForm({ ...form, confirm: e.target.value })} placeholder="Re-enter password" className="mt-1.5" />
                </div>
                <Button data-testid="reset-submit-button" type="submit" disabled={busy}
                  className="w-full bg-black hover:bg-slate-800 text-white py-2.5 rounded-md font-semibold">
                  {busy ? "Saving…" : "Reset password"}
                </Button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
