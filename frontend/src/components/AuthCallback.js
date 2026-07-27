import { useEffect, useRef } from "react";
import api from "@/lib/api";
import { Truck } from "lucide-react";

export default function AuthCallback() {
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const run = async () => {
      const hash = window.location.hash;
      const match = hash.match(/session_id=([^&]+)/);
      const sessionId = match ? match[1] : null;
      if (!sessionId) {
        window.location.href = "/login";
        return;
      }
      try {
        // Clear any stale email/password bearer token so the Google session
        // cookie is the only credential in play for this login.
        localStorage.removeItem("token");
        await api.post("/auth/session", {}, { headers: { "X-Session-ID": sessionId } });
        window.location.href = "/dashboard";
      } catch (e) {
        window.location.href = "/login";
      }
    };
    run();
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-900 text-white gap-4">
      <Truck className="animate-pulse" size={40} />
      <p className="text-sm tracking-[0.2em] uppercase">Signing you in…</p>
    </div>
  );
}
