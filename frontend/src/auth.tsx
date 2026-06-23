import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, tokens, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean; // initial bootstrap
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (body: { email: string; full_name: string; password: string }) => Promise<void>;
  signOut: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Bootstrap: if we have a stored access token, validate it via /auth/me
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!tokens.access) { setLoading(false); return; }
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch {
        tokens.clear();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { user, tokens: t } = await api.login(email, password);
    tokens.set(t.access_token, t.refresh_token);
    setUser(user);
  }, []);

  const signUp = useCallback(
    async (body: { email: string; full_name: string; password: string }) => {
      const { user, tokens: t } = await api.register(body);
      tokens.set(t.access_token, t.refresh_token);
      setUser(user);
    },
    [],
  );

  const signOut = useCallback(() => {
    tokens.clear();
    setUser(null);
  }, []);

  return (
    <AuthCtx.Provider value={{ user, loading, signIn, signUp, signOut }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
