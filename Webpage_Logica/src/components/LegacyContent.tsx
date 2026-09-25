'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSiteRuntime } from './SiteRuntimeProvider';
import { loadBrowserScript } from '../services/site-runtime';
import './legacy-content.css';

interface LegacyContentProps {
  html: string;
  scripts: string[];
  bodyAttributes: Record<string, string>;
}

/** Apply page metadata without replacing classes owned by settings or dialogs. */
function applyBodyAttributes(attributes: Record<string, string>): () => void {
  const body = document.body;
  const addedClasses: string[] = [];
  const changedData: Array<{ name: string; previous: string | null; value: string }> = [];

  for (const [name, value] of Object.entries(attributes)) {
    if (name === 'class') {
      for (const token of value.split(/\s+/).filter(Boolean)) {
        // Theme and accessibility classes belong to SiteRuntimeProvider.
        if (token === 'day-mode' || token.startsWith('daltonism-') || token.startsWith('font-size-')) continue;
        if (!body.classList.contains(token)) {
          body.classList.add(token);
          addedClasses.push(token);
        }
      }
    } else if (/^data-[a-z0-9_.:-]+$/i.test(name)) {
      const previous = body.getAttribute(name);
      if (previous !== value) {
        body.setAttribute(name, value);
        changedData.push({ name, previous, value });
      }
    }
  }

  return () => {
    for (const token of addedClasses) body.classList.remove(token);
    for (const { name, previous, value } of changedData) {
      // A controller may have updated this attribute after initialization.
      if (body.getAttribute(name) !== value) continue;
      if (previous === null) body.removeAttribute(name);
      else body.setAttribute(name, previous);
    }
  };
}

/**
 * html comes only from the local source adapter, which removes script elements
 * and supplies a main landmark. React owns the outer node, never its children.
 * All page navigation must remain ordinary document-loading <a> links: legacy
 * controllers live until document unload and do not support SPA remounts yet.
 */
export function LegacyContent({ html, scripts, bodyAttributes }: LegacyContentProps) {
  const { runtime, error: runtimeError } = useSiteRuntime();
  const [scriptError, setScriptError] = useState<string | null>(null);
  const markup = useMemo(() => ({ __html: html }), [html]);

  useEffect(() => applyBodyAttributes(bodyAttributes), [bodyAttributes]);

  useEffect(() => {
    if (!runtime) return;
    let cancelled = false;
    let removeReadyListener = () => {};
    const ready = document.readyState === 'loading'
      ? new Promise<void>((resolve) => {
        const onReady = () => resolve();
        document.addEventListener('DOMContentLoaded', onReady, { once: true });
        removeReadyListener = () => document.removeEventListener('DOMContentLoaded', onReady);
      })
      : Promise.resolve();

    void (async () => {
      await ready;
      // The shared loader deduplicates both pending and completed scripts.
      // Strict Mode replay resumes this sequence without executing them twice.
      for (const source of scripts) {
        if (cancelled) return;
        await loadBrowserScript(source);
      }
    })().catch(() => {
      if (!cancelled) {
        setScriptError('Non è stato possibile caricare tutte le funzioni della pagina.');
      }
    });

    return () => {
      cancelled = true;
      removeReadyListener();
      // Do not remove loaded scripts or restart document-lifetime controllers.
    };
  }, [runtime, scripts]);

  const error = runtimeError || scriptError;
  return <>
    {error && <p className="legacy-content-error" role="alert">
      {error} <a href="">Ricarica la pagina</a>.
    </p>}
    <div className="legacy-content" data-legacy-content="" dangerouslySetInnerHTML={markup} />
  </>;
}
