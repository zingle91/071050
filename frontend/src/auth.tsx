import React, { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api/client";
import type { Employee } from "./api/types";

interface AuthCtx {
  user: Employee | null;
  loading: boolean;
  login: (employeeId: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Employee | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api<Employee>("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(employeeId: string, password: string) {
    const data = await api<{ access_token: string }>("/api/auth/login/json", {
      method: "POST",
      body: JSON.stringify({ employee_id: employeeId, password }),
    });
    setToken(data.access_token);
    const me = await api<Employee>("/api/auth/me");
    setUser(me);
  }

  function logout() {
    setToken(null);
    setUser(null);
  }

  return (
    <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
