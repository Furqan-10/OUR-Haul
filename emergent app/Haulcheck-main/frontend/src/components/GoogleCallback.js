import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Truck, AlertTriangle } from "lucide-react";

/**
 * Landing point for the standard Google OAuth flow (`/auth/google/callback`).
 *
 * Distinct from AuthCallback.js, which handles the older Emergent-hosted
 * exchange and its `#session_id=` hash. Both can be present in one deployment
 * during migration, so they are kept as separate components rather than one
 * branching on URL shape.
 */
export default function GoogleCallback() {
  const ran = useRef(false);
  const [error, setError] = useState("");
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    // React 18 StrictMode double-invokes effects in development. The
    // authorization code is single-use, so a second exchange would always fail
    // and show a spurious error.
    if (ran.current) return;
    ran.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const denied = params.get("error");

    if (denied) {
      setError(denied === "access_denied"
        ? "Sign-in was cancelled."
        : "Google could not complete the sign-in.");
      return;
    }
    if (!code || !state) {
      navigate("/login", { replace: true });
      return;
    }

    (async () => {
      try {
        // Drop any stale bearer token before the new one lands.
        localStorage.removeItem("token");
        const res = await api.post("/auth/google/callback", { code, state });
        loginWithToken(res.data.token, res.data.user);
        // replace: the callback URL holds a spent code and must not be
        // reachable with the back button.
        navigate("/dashboard", { replace: true });
      } catch (err) {
        setError(err.response?.data?.detail || "Google sign-in could not be completed.");
      }
    })();
  }, [loginWithToken, navigate]);

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-900 text-white gap-4 px-6">
        <AlertTriangle size={40} className="text-amber-400" />
        <p data-testid="google-callback-error" className="text-sm text-center max-w-sm text-slate-200">{error}</p>
        <a data-testid="google-callback-retry" href="/login"
           className="text-sm font-semibold underline underline-offset-4">
          Back to sign in
        </a>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-900 text-white gap-4">
      <Truck className="animate-pulse" size={40} />
      <p data-testid="google-callback-pending" className="text-sm tracking-[0.2em] uppercase">Signing you in…</p>
    </div>
  );
}
