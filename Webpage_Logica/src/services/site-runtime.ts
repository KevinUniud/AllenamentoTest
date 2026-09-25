/** The existing storage modules remain the single source of truth during migration. */
export type Theme = 'night' | 'day';
export type Daltonism = 'none' | 'protanopia' | 'deuteranopia' | 'tritanopia' | 'achromatopsia';

export interface PrivacyPreferences {
  version: number;
  localData: boolean;
  anonymousFeedback: boolean;
  includeDemographics: boolean;
  updatedAt: number;
}

export interface DisplayPreferences {
  font: number;
  theme: Theme;
  daltonism: Daltonism;
  highlightAtoms: boolean;
  differentiateParens: boolean;
}

interface LogicPreferences {
  KEYS: Record<keyof DisplayPreferences, string>;
  DALTONISM_MODES: readonly Daltonism[];
  clampFontPx(value: unknown, minimum: number, maximum: number, fallback: number): number;
  parsePxValue(value: string, minimum: number, maximum: number, fallback: number): number | null;
  applyTheme(document: Document, mode: string): Theme;
  applyDaltonism(document: Document, mode: string): Daltonism;
  readBool(storage: Storage, key: string): boolean;
  writeBool(storage: Storage, key: string, value: boolean): void;
}

interface LogicPrivacy {
  DEFAULTS: PrivacyPreferences;
  STORAGE_KEY: string;
  read(): PrivacyPreferences;
  update(patch: Partial<PrivacyPreferences>): PrivacyPreferences;
  canPersist(): boolean;
  canSendFeedback(): boolean;
  includeDemographics(): boolean;
}

export interface AppEvents {
  on(name: string, listener: (detail?: unknown) => void): () => void;
  emit(name: string, detail?: unknown): void;
}

export interface AppStorage {
  available: boolean;
  put<T>(type: string, id: string, value: T): Promise<boolean>;
  get<T>(type: string, id: string): Promise<T | null>;
  list<T>(type: string): Promise<T[]>;
  remove(type: string, id: string): Promise<boolean | void>;
  clearType(type: string): Promise<void>;
  clearAll(): Promise<void>;
  purgeExpired(now?: number): Promise<number>;
  exportAll(): Promise<unknown[]>;
}

export interface SiteRuntime {
  preferences: LogicPreferences;
  privacy: LogicPrivacy;
  storage: AppStorage;
  events: AppEvents;
}

declare global {
  interface Window {
    LogicPreferences?: LogicPreferences;
    LogicPrivacy?: LogicPrivacy;
    LogicAppStorage?: { instance: AppStorage };
    LogicAppEvents?: AppEvents;
    LogicDataContracts?: object;
    __logicSiteRuntimePromise?: Promise<SiteRuntime>;
    __logicBrowserScripts?: Map<string, Promise<void>>;
  }
}

export const DEFAULT_DISPLAY_PREFERENCES: DisplayPreferences = {
  font: 16,
  theme: 'night',
  daltonism: 'none',
  highlightAtoms: false,
  differentiateParens: false,
};

/** External scripts are deduplicated across React Strict Mode mounts. */
export function loadBrowserScript(source: string): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('Il runtime richiede il browser.'));
  const url = new URL(source, window.location.origin).href;
  const scripts = window.__logicBrowserScripts ??= new Map<string, Promise<void>>();
  const existing = scripts.get(url);
  if (existing) return existing;
  const pending = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.async = false;
    script.dataset.logicRuntime = source;
    script.onload = () => {
      script.onload = script.onerror = null;
      resolve();
    };
    script.onerror = () => {
      script.onload = script.onerror = null;
      script.remove();
      scripts.delete(url);
      reject(new Error(`Caricamento non riuscito: ${source}`));
    };
    document.head.appendChild(script);
  });
  scripts.set(url, pending);
  return pending;
}

/** Called only after React mounts, never during static rendering. */
export function loadSiteRuntime(): Promise<SiteRuntime> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Il runtime richiede il browser.'));
  }
  if (window.__logicSiteRuntimePromise) return window.__logicSiteRuntimePromise;

  const modules = [
    ['settings-preferences.js', 'LogicPreferences'],
    ['app-events.js', 'LogicAppEvents'],
    ['data-contracts.js', 'LogicDataContracts'],
    ['privacy-controls.js', 'LogicPrivacy'],
    ['app-storage.js', 'LogicAppStorage'],
  ] as const;

  window.__logicSiteRuntimePromise = (async () => {
    for (const [filename, globalName] of modules) {
      if (window[globalName]) continue;
      await loadBrowserScript(`/scripts/${filename}`);
      if (!window[globalName]) throw new Error(`Modulo non disponibile: ${filename}`);
    }
    return {
      preferences: window.LogicPreferences!,
      privacy: window.LogicPrivacy!,
      storage: window.LogicAppStorage!.instance,
      events: window.LogicAppEvents!,
    };
  })().catch((error: unknown) => {
    delete window.__logicSiteRuntimePromise;
    throw error;
  });
  return window.__logicSiteRuntimePromise;
}

/** Matches the former app.js retirement without touching unrelated caches or scopes. */
export function retireLegacyPwa(): void {
  const scope = new URL('/', window.location.origin).href;
  if ('serviceWorker' in navigator) {
    void navigator.serviceWorker.getRegistrations().then((registrations) => Promise.all(
      registrations.filter((registration) => registration.scope === scope)
        .map((registration) => registration.unregister()),
    )).catch(() => {});
  }
  if ('caches' in window) {
    void window.caches.keys().then((names) => Promise.all(
      names.filter((name) => name.startsWith('testlogica-')).map((name) => window.caches.delete(name)),
    )).catch(() => {});
  }
}

export function readDisplayPreferences(runtime: SiteRuntime): DisplayPreferences {
  const prefs = runtime.preferences;
  try {
    const storage = window.localStorage;
    const daltonism = storage.getItem(prefs.KEYS.daltonism) as Daltonism | null;
    return {
      font: prefs.clampFontPx(storage.getItem(prefs.KEYS.font) || 16, 12, 28, 16),
      theme: storage.getItem(prefs.KEYS.theme) === 'day' ? 'day' : 'night',
      daltonism: daltonism && prefs.DALTONISM_MODES.includes(daltonism) ? daltonism : 'none',
      highlightAtoms: prefs.readBool(storage, prefs.KEYS.highlightAtoms),
      differentiateParens: prefs.readBool(storage, prefs.KEYS.differentiateParens),
    };
  } catch {
    return { ...DEFAULT_DISPLAY_PREFERENCES };
  }
}

export function applyDisplayPreferences(runtime: SiteRuntime, values: DisplayPreferences): void {
  for (let value = 12; value <= 28; value += 1) {
    document.documentElement.classList.remove(`font-size-${value}`);
  }
  document.documentElement.classList.add(`font-size-${values.font}`);
  runtime.preferences.applyTheme(document, values.theme);
  runtime.preferences.applyDaltonism(document, values.daltonism);
}

export function publishExercisePreferences(values: DisplayPreferences): void {
  window.dispatchEvent(new CustomEvent('logicExerciseSettingsChanged', {
    detail: {
      highlightAtoms: values.highlightAtoms,
      differentiateParens: values.differentiateParens,
    },
  }));
}

export function readPrivacyPreferences(runtime: SiteRuntime): PrivacyPreferences {
  try {
    return runtime.privacy.read();
  } catch {
    return { ...runtime.privacy.DEFAULTS };
  }
}
