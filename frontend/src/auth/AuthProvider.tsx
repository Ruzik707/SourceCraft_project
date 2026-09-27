import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { IS_AUTH_MOCK, api, getToken, setToken } from '@/api';
import type { User } from '@/api/types';

interface AuthState {
  user: User | null;
  status: 'loading' | 'authenticated' | 'anonymous';
  /** Уводит пользователя на страницу согласия Я ID (в mock-режиме — вход сразу). */
  login: (redirectPath?: string) => void;
  logout: () => Promise<void>;
  /** Вызывается со страницы /auth/callback после возврата от Я ID. */
  completeLogin: (token: string) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthState['status']>('loading');

  const loadUser = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setStatus('anonymous');
      return;
    }
    try {
      const me = await api.getMe();
      setUser(me);
      setStatus('authenticated');
    } catch {
      setToken(null);
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const login = useCallback(
    (redirectPath = '/dashboard') => {
      if (IS_AUTH_MOCK) {
        // Демо-режим: настоящего редиректа в Я ID нет, но путь пользователя
        // повторяет боевой — через /auth/callback.
        window.location.assign(`/auth/callback?token=mock-yandex-id-token&next=${encodeURIComponent(redirectPath)}`);
        return;
      }
      window.location.assign(api.loginUrl(redirectPath));
    },
    [],
  );

  const completeLogin = useCallback(
    async (token: string) => {
      setToken(token);
      await loadUser();
    },
    [loadUser],
  );

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setStatus('anonymous');
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, status, login, logout, completeLogin }),
    [user, status, login, logout, completeLogin],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth вызван вне AuthProvider');
  return ctx;
}
