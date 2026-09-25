'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  applyDisplayPreferences,
  loadSiteRuntime,
  publishExercisePreferences,
  readDisplayPreferences,
  retireLegacyPwa,
  type SiteRuntime,
} from '../services/site-runtime';

interface RuntimeState {
  runtime: SiteRuntime | null;
  error: string | null;
}

const SiteRuntimeContext = createContext<RuntimeState>({ runtime: null, error: null });

export function SiteRuntimeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<RuntimeState>({ runtime: null, error: null });

  useEffect(() => {
    let cancelled = false;
    let removeStorageListener = () => {};
    retireLegacyPwa();
    loadSiteRuntime().then((runtime) => {
      if (cancelled) return;
      const refreshPreferences = () => {
        const values = readDisplayPreferences(runtime);
        applyDisplayPreferences(runtime, values);
        publishExercisePreferences(values);
      };
      refreshPreferences();
      window.addEventListener('storage', refreshPreferences);
      removeStorageListener = () => window.removeEventListener('storage', refreshPreferences);
      setState({ runtime, error: null });
      // Retention is unchanged and does not enable storage without consent.
      void runtime.storage.purgeExpired().catch(() => {});
    }).catch(() => {
      if (!cancelled) setState({ runtime: null, error: 'Impostazioni e dati locali non disponibili. Ricarica la pagina per riprovare.' });
    });
    return () => {
      cancelled = true;
      removeStorageListener();
    };
  }, []);

  return <SiteRuntimeContext.Provider value={state}>{children}</SiteRuntimeContext.Provider>;
}

export function useSiteRuntime(): RuntimeState {
  return useContext(SiteRuntimeContext);
}
