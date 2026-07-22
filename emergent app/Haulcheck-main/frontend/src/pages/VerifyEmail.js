import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { CheckCircle2, XCircle, Loader2, Truck } from "lucide-react";

/**
 * Confirms an email address from the link in the verification email.
 * Public route: the token in the URL is the credential, no login required.
 */
export default function VerifyEmail() {
  const navigate = useNavigate();
  const [state, setState] = useState("verifying"); // verifying | ok | error

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setState("error");
      return;
    }
    api
      .post("/auth/verify-email", { token })
      .then(() => setState("ok"))
      .catch(() => setState("error"));
  }, []);

  return (
    <div data-testid="verify-email-page" className="min-h-screen flex flex-col items-center justify-center gap-4 p-6 text-center">
      {state === "verifying" && (
        <>
          <Loader2 className="animate-spin text-slate-400" size={36} />
          <p className="text-sm uppercase tracking-widest text-slate-400">Confirming your email…</p>
        </>
      )}
      {state === "ok" && (
        <>
          <CheckCircle2 className="text-emerald-500" size={44} />
          <h1 className="font-heading text-2xl font-black text-slate-900">Email confirmed</h1>
          <p className="text-slate-500 text-sm">Your address is verified. You're all set.</p>
          <button
            data-testid="verify-continue"
            onClick={() => navigate("/dashboard")}
            className="mt-2 bg-black text-white px-5 py-2.5 rounded-md font-semibold text-sm"
          >
            Continue to dashboard
          </button>
        </>
      )}
      {state === "error" && (
        <>
          <XCircle className="text-red-500" size={44} />
          <h1 className="font-heading text-2xl font-black text-slate-900">Link invalid or expired</h1>
          <p className="text-slate-500 text-sm max-w-sm">
            This confirmation link is no longer valid. Sign in and use “Resend link” from the banner to get a new one.
          </p>
          <button
            onClick={() => navigate("/login")}
            className="mt-2 flex items-center gap-2 bg-black text-white px-5 py-2.5 rounded-md font-semibold text-sm"
          >
            <Truck size={16} /> Go to sign in
          </button>
        </>
      )}
    </div>
  );
}
