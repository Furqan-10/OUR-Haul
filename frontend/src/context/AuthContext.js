import { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import api from "@/lib/api";

const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
    } catch (e) {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // CRITICAL: If returning from OAuth callback, skip the /me check.
    if (window.location.hash?.includes("session_id=")) {
      setLoading(false);
      return;
    }
    checkAuth();
  }, [checkAuth]);

  const loginWithToken = useCallback((token, userData) => {
    localStorage.setItem("token", token);
    setUser(userData);
  }, []);

  const updateRegion = useCallback(async (region) => {
    await api.put("/settings/region", { region });
    setUser((prev) => (prev ? { ...prev, region } : prev));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      console.error("Logout request failed", e);
    }
    localStorage.removeItem("token");
    setUser(null);
    window.location.href = "/login";
  }, []);

  // Organisation role, derived once here so no component has to know the
  // ranking. `canWrite` is the flag almost every screen actually wants: viewers
  // are read-only, and the backend enforces the same rule in get_current_user,
  // so this only decides whether a control is shown -- never whether it is safe.
  const orgRole = user?.org_role || null;
  const isOwner = orgRole === "owner";
  const canWrite = Boolean(user) && orgRole !== "viewer" && !user?.impersonated_by;
  const isPlatformAdmin = user?.platform_role === "platform_admin";

  const value = useMemo(
    () => ({
      user, setUser, loading, loginWithToken, logout, checkAuth, updateRegion,
      orgRole, isOwner, canWrite, isPlatformAdmin,
    }),
    [user, loading, loginWithToken, logout, checkAuth, updateRegion,
     orgRole, isOwner, canWrite, isPlatformAdmin]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
