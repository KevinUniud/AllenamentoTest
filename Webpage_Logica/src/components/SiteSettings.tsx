'use client';

import { useEffect, useRef, useState } from 'react';
import {
  applyDisplayPreferences,
  DEFAULT_DISPLAY_PREFERENCES,
  publishExercisePreferences,
  readDisplayPreferences,
  readPrivacyPreferences,
  type Daltonism,
  type DisplayPreferences,
  type PrivacyPreferences,
  type Theme,
} from '../services/site-runtime';
import { useSiteRuntime } from './SiteRuntimeProvider';

const DEFAULT_PRIVACY: PrivacyPreferences = {
  version: 1, localData: false, anonymousFeedback: false, includeDemographics: false, updatedAt: 0,
};

function clearLegacyDemographics(): void {
  ['logDataAge', 'logDataInstitution', 'logDataStem'].forEach((key) => window.localStorage.removeItem(key));
}

type DataAction = 'export' | 'data' | 'sessions' | 'progress';

export function SiteSettings() {
  const { runtime, error } = useSiteRuntime();
  const [values, setValues] = useState<DisplayPreferences>(DEFAULT_DISPLAY_PREFERENCES);
  const [privacy, setPrivacy] = useState<PrivacyPreferences>(DEFAULT_PRIVACY);
  const [fontInput, setFontInput] = useState('16');
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const mountedRef = useRef(false);
  const busyRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!runtime) return;
    const refresh = () => {
      const next = readDisplayPreferences(runtime);
      setValues(next);
      setFontInput(String(next.font));
      setPrivacy(readPrivacyPreferences(runtime));
    };
    refresh();
    const unsubscribe = runtime.events.on('privacy:changed', () => setPrivacy(readPrivacyPreferences(runtime)));
    window.addEventListener('storage', refresh);
    return () => {
      unsubscribe();
      window.removeEventListener('storage', refresh);
    };
  }, [runtime]);

  useEffect(() => {
    if (!open) return;
    const modal = modalRef.current;
    if (!modal) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const main = document.getElementById('main-content');
    const previousInert = main?.inert ?? false;
    if (main && !main.contains(modal)) main.inert = true;
    const focusables = () => Array.from(modal.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.hidden && element.offsetParent !== null);
    (focusables()[0] || modal).focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key !== 'Tab') return;
      const elements = focusables();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) {
        event.preventDefault();
        modal.focus();
        return;
      }
      if (!modal.contains(document.activeElement) || document.activeElement === modal) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (main) main.inert = previousInert;
      if (previousFocus?.isConnected) previousFocus.focus();
      else triggerRef.current?.focus();
    };
  }, [open]);

  function saveDisplay(patch: Partial<DisplayPreferences>) {
    if (!runtime) return;
    const next = { ...values, ...patch };
    setValues(next);
    applyDisplayPreferences(runtime, next);
    if ('highlightAtoms' in patch || 'differentiateParens' in patch) publishExercisePreferences(next);
    try {
      for (const key of Object.keys(patch) as (keyof DisplayPreferences)[]) {
        const value = next[key];
        window.localStorage.setItem(runtime.preferences.KEYS[key], typeof value === 'boolean' ? (value ? '1' : '0') : String(value));
      }
    } catch {
      setStatus('Preferenza applicata, ma non è stato possibile salvarla in questo browser.');
    }
  }

  function commitFont() {
    if (!runtime) return;
    const font = runtime.preferences.parsePxValue(fontInput, 12, 28, 16);
    if (font === null) {
      setFontInput(String(values.font));
      return;
    }
    setFontInput(String(font));
    saveDisplay({ font });
  }

  function changePrivacy(patch: Partial<PrivacyPreferences>, message: string) {
    if (!runtime) return;
    try {
      if (patch.anonymousFeedback === false || patch.includeDemographics === false) clearLegacyDemographics();
      setPrivacy(runtime.privacy.update(patch));
      setStatus(message);
    } catch {
      setPrivacy(readPrivacyPreferences(runtime));
      setStatus('Non è stato possibile aggiornare il consenso in questo browser. Riprova.');
    }
  }

  async function runDataAction(action: DataAction) {
    if (!runtime || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setStatus('Operazione in corso…');
    if (action !== 'export') runtime.events.emit(`privacy:${action}-clearing`);
    try {
      let message: string;
      if (action === 'export') {
        const records = await runtime.storage.exportAll();
        if (!mountedRef.current) return;
        const blob = new Blob([JSON.stringify({ version: 1, exportedAt: Date.now(), records }, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        try {
          link.href = url;
          link.download = 'testlogica-dati.json';
          document.body.appendChild(link);
          link.click();
        } finally {
          link.remove();
          URL.revokeObjectURL(url);
        }
        message = 'Dati esportati.';
      } else if (action === 'data') {
        clearLegacyDemographics();
        await runtime.storage.clearAll();
        message = 'Sessioni, progressi e dati demografici locali eliminati.';
      } else if (action === 'sessions') {
        await runtime.storage.clearType('sessions');
        await runtime.storage.clearType('sessionHistory');
        message = 'Sessioni attive e concluse eliminate.';
      } else {
        await runtime.storage.clearType('attempts');
        await runtime.storage.clearType('errors');
        await runtime.storage.clearType('lessonProgress');
        message = 'Tentativi, errori e progresso delle lezioni eliminati.';
      }
      if (mountedRef.current) setStatus(message);
    } catch {
      if (mountedRef.current) setStatus(action === 'export'
        ? 'Non è stato possibile esportare i dati locali. Riprova.'
        : 'Non è stato possibile eliminare tutti i dati richiesti. Riprova.');
    } finally {
      if (action !== 'export') runtime.events.emit(`privacy:${action}-cleared`);
      busyRef.current = false;
      if (mountedRef.current) setBusy(false);
    }
  }

  return <>
    <button ref={triggerRef} id="settings-trigger" type="button" className="btn-wide settings-trigger"
      aria-label="Apri impostazioni" aria-haspopup="dialog" aria-expanded={open} aria-controls="settings-overlay"
      onClick={() => setOpen(true)}>⚙</button>
    <div id="settings-overlay" className="settings-overlay" hidden={!open}
      onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div ref={modalRef} id="settings-modal" className="settings-modal" role="dialog" aria-modal="true"
        aria-labelledby="settings-title" aria-describedby="settings-description" tabIndex={-1}>
        <h2 id="settings-title">Impostazioni globali</h2>
        <p id="settings-description" className="sr-only">Pannello impostazioni globali del sito e opzioni di accessibilita.</p>
        <h3>Opzioni globali:</h3>
        <div className="settings-row">
          <label htmlFor="fontScaleInput">Dimensione font:</label>
          <input id="fontScaleInput" type="text" className="settings-input" inputMode="numeric" aria-label="Dimensione font in pixel"
            disabled={!runtime} value={fontInput} onChange={(event) => setFontInput(event.target.value)} onBlur={commitFont}
            onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); commitFont(); } }} />
          <span>px</span>
        </div>
        <div className="settings-row">
          <label htmlFor="themeSelect">Tema:</label>
          <select id="themeSelect" className="settings-input" disabled={!runtime} value={values.theme}
            onChange={(event) => saveDisplay({ theme: event.target.value as Theme })}>
            <option value="night">Night</option><option value="day">Day</option>
          </select>
        </div>
        <div className="settings-row">
          <label htmlFor="daltonismSelect">Daltonismo:</label>
          <select id="daltonismSelect" className="settings-input settings-input-wide" aria-describedby="daltonism-help"
            disabled={!runtime} value={values.daltonism} onChange={(event) => saveDisplay({ daltonism: event.target.value as Daltonism })}>
            <option value="none">Nessuno</option><option value="protanopia">Protanopia</option>
            <option value="deuteranopia">Deuteranopia</option><option value="tritanopia">Tritanopia</option>
            <option value="achromatopsia">Acromatopsia</option>
          </select>
        </div>
        <p id="daltonism-help" className="sr-only">Seleziona una palette alternativa per migliorare la leggibilita dei colori semantici.</p>
        <h3>Opzioni esercitazione:</h3>
        <div className="settings-row">
          <input id="settingsHighlightAtoms" type="checkbox" disabled={!runtime} checked={values.highlightAtoms}
            onChange={(event) => saveDisplay({ highlightAtoms: event.target.checked })} />
          <label htmlFor="settingsHighlightAtoms">Evidenzia atomi</label>
        </div>
        <div className="settings-row">
          <input id="settingsDifferentiateParens" type="checkbox" disabled={!runtime} checked={values.differentiateParens}
            onChange={(event) => saveDisplay({ differentiateParens: event.target.checked })} />
          <label htmlFor="settingsDifferentiateParens">Differenzia parentesi</label>
        </div>
        <h3>Dati e privacy:</h3>
        <div className="settings-row">
          <input id="settingsLocalData" type="checkbox" disabled={!runtime || busy} checked={privacy.localData}
            onChange={(event) => changePrivacy({ localData: event.target.checked }, event.target.checked
              ? 'Salvataggio locale attivato.' : 'Salvataggio locale disattivato. I dati esistenti non sono stati eliminati.')} />
          <label htmlFor="settingsLocalData">Salva localmente sessioni e progressi</label>
        </div>
        <div className="settings-row">
          <input id="settingsAnonymousFeedback" type="checkbox" disabled={!runtime || busy} checked={privacy.anonymousFeedback}
            onChange={(event) => changePrivacy({ anonymousFeedback: event.target.checked, includeDemographics: event.target.checked && privacy.includeDemographics },
              event.target.checked ? 'Invio feedback senza nome o account consentito.' : 'Invio feedback disattivato.')} />
          <label htmlFor="settingsAnonymousFeedback">Consenti invio feedback senza nome o account</label>
        </div>
        <div className="settings-row">
          <input id="settingsIncludeDemographics" type="checkbox" disabled={!runtime || busy || !privacy.anonymousFeedback} checked={privacy.includeDemographics}
            onChange={(event) => changePrivacy({ includeDemographics: event.target.checked }, event.target.checked
              ? 'I dati demografici saranno inclusi nel feedback.' : 'I dati demografici saranno esclusi dal feedback.')} />
          <label htmlFor="settingsIncludeDemographics">Includi dati demografici nel feedback</label>
        </div>
        <p className="settings-help">I dati locali restano in questo browser. Nessun feedback viene inviato senza consenso.
          <a href="/privacy/"> Leggi l’informativa completa.</a>
        </p>
        <div className="settings-actions settings-privacy-actions" aria-busy={busy}>
          <button type="button" className="btn-wide" disabled={!runtime || busy} onClick={() => { void runDataAction('export'); }}>Esporta dati</button>
          <button type="button" className="btn-wide" disabled={!runtime || busy} onClick={() => { void runDataAction('sessions'); }}>Elimina sessioni</button>
          <button type="button" className="btn-wide" disabled={!runtime || busy} onClick={() => { void runDataAction('progress'); }}>Elimina progressi</button>
          <button type="button" className="btn-wide" disabled={!runtime || busy} onClick={() => { void runDataAction('data'); }}>Elimina dati locali</button>
        </div>
        <p className="settings-help" aria-live="polite">{error || status || (!runtime ? 'Caricamento impostazioni…' : '')}</p>
        <div className="settings-actions">
          <button type="button" className="btn-wide" disabled={!runtime} onClick={() => {
            setFontInput('16');
            saveDisplay({ font: 16, theme: 'night', daltonism: 'none' });
          }}>Reset</button>
          <button type="button" className="btn-wide" onClick={() => setOpen(false)}>Chiudi</button>
        </div>
      </div>
    </div>
  </>;
}
