/**
 * Session Context - Manages current session state
 * Tracks conversation ID, agent ID, and session metadata
 */

import React, { createContext, useContext, useState, ReactNode } from 'react';
import type { Session } from '../../core/types';

interface SessionContextValue {
  currentSession: Session;
  setSession: (session: Session) => void;
  updateSession: (updates: Partial<Session>) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export interface SessionProviderProps {
  children: ReactNode;
  initialSession?: Partial<Session>;
}

export function SessionProvider({
  children,
  initialSession = {},
}: SessionProviderProps) {
  const [currentSession, setCurrentSession] = useState<Session>({
    id: Date.now().toString(),
    createdAt: Date.now(),
    updatedAt: Date.now(),
    ...initialSession,
  });

  const setSession = (session: Session) => {
    setCurrentSession(session);
  };

  const updateSession = (updates: Partial<Session>) => {
    setCurrentSession((prev) => ({
      ...prev,
      ...updates,
      updatedAt: Date.now(),
    }));
  };

  return (
    <SessionContext.Provider
      value={{ currentSession, setSession, updateSession }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
}
