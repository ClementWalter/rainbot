import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";

// The session context tracks the authenticated user plus a `needs_bootstrap`
// hint so the Login page knows whether to show the bootstrap admin form. All
// pages rely on `useSession()` to gate their own data loads.

type SessionState = {
  user: User | null;
  needsBootstrap: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
  setUser: (user: User | null) => void;
};

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const me = await api.me();
      setUser(me.user);
      setNeedsBootstrap(me.needs_bootstrap);
    } catch (error) {
      if (error instanceof ApiError) {
        setUser(null);
      } else {
        throw error;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionState>(
    () => ({ user, needsBootstrap, loading, refresh, setUser }),
    [user, needsBootstrap, loading, refresh],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (ctx === null) {
    throw new Error("useSession must be used inside <SessionProvider>.");
  }
  return ctx;
}
