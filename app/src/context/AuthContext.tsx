import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { authApi, clearAuthState } from '@/services/api';

export interface AuthUser {
  id: number;
  uuid: string;
  full_name: string;
  phone: string;
  role: string;
  name: string;
  avatar: string;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: AuthUser | null;
  login: (phone: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function userFromStorage(): AuthUser | null {
  try {
    const saved = localStorage.getItem('auth_user');
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Optimistic: show cached user so there's no flash to login on page reload.
  // The /me call below validates the session and corrects state if the cookie expired.
  const [user, setUser] = useState<AuthUser | null>(userFromStorage);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!userFromStorage());

  const applyUser = (me: { id: number; uuid: string; full_name: string; phone: string; user_role: string }) => {
    const userData: AuthUser = {
      id: me.id,
      uuid: me.uuid,
      full_name: me.full_name,
      phone: me.phone,
      role: me.user_role,
      name: me.full_name,
      avatar: '/avatar.jpg',
    };
    setUser(userData);
    setIsAuthenticated(true);
    localStorage.setItem('auth_user', JSON.stringify(userData));
    return userData;
  };

  const clearSession = useCallback(() => {
    clearAuthState();
    setIsAuthenticated(false);
    setUser(null);
  }, []);

  // Validate the session cookie on mount
  useEffect(() => {
    authApi.me().then(applyUser).catch(clearSession);
  }, []);

  // Handle session expiry events dispatched by apiFetch when refresh fails
  useEffect(() => {
    const handler = () => clearSession();
    window.addEventListener('auth:expired', handler);
    return () => window.removeEventListener('auth:expired', handler);
  }, [clearSession]);

  const login = useCallback(async (phone: string, password: string): Promise<boolean> => {
    try {
      const data = await authApi.login({ phone, password });
      // Tokens are set as httpOnly cookies by the server.
      // Build the user object from the response body.
      const userData: AuthUser = {
        id: data.user_id,
        uuid: data.uuid,
        full_name: data.full_name,
        phone: data.phone,
        role: data.role,
        name: data.full_name,
        avatar: '/avatar.jpg',
      };
      setUser(userData);
      setIsAuthenticated(true);
      localStorage.setItem('auth_user', JSON.stringify(userData));
      return true;
    } catch {
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout(); // server clears httpOnly cookies
    } catch {
      // Proceed even if the API call fails
    }
    clearSession();
  }, [clearSession]);

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
