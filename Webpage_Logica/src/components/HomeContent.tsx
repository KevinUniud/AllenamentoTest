'use client';

import { useEffect, useState } from 'react';
import { useSiteRuntime } from './SiteRuntimeProvider';

interface Bookmark { url: string; title: string }
interface LessonProgress { manuallyCompleted?: boolean; bookmarks?: Bookmark[] }

const sections = [
  { href: '/lezioni/lezione-1/', label: 'Apri Lezioni', text: 'Una raccolta di lezioni organizzate in modo progressivo, pensate per spiegare i concetti principali passo dopo passo, con esempi e contenuti di supporto.' },
  { href: '/esercizi/esercitazione/', label: 'Apri Esercizi', text: "Esercitazioni utili per verificare la propria comprensione in modo attivo con l'ausilio di strumenti didattici." },
  { href: '/Errori_comuni/', label: 'Errori Comuni', text: 'Sezione con esempi di esercizi e spiegazioni di errori comuni di logica, diagrammi e tabelle di verità.' },
  { href: '/strumenti/sandbox/', label: 'Laboratorio di logica', text: "Costruisci formule, osserva i passaggi e l'albero, genera tabelle di verita e confronta espressioni." },
  { href: '/ripasso/errori/', label: 'Quaderno degli errori', text: 'Ritrova le risposte errate, filtra gli argomenti e organizza il ripasso.' },
  { href: '/progressi/', label: 'I miei progressi', text: 'Consulta accuratezza, tempi e risultati per tipologia, tutti calcolati localmente.' },
  { href: '/privacy/', label: 'Dati e privacy', text: 'Scopri quali dati possono essere salvati, inviati, esportati o eliminati.' },
  { href: '/grafici/grafici/', label: 'Apri Grafici', text: 'Una galleria di grafici generati tramite feedback degli utenti, organizzati per area tematica e consultabili rapidamente.' },
];

function localBookmark(bookmark: Bookmark | undefined): Bookmark | undefined {
  if (!bookmark || typeof bookmark.url !== 'string') return undefined;
  try {
    const url = new URL(bookmark.url, window.location.origin);
    if (url.origin !== window.location.origin || !/^\/lezioni\/lezione-[1-6](?:\.html|\/)$/.test(url.pathname)) return undefined;
    return { url: url.pathname.replace(/\.html$/, '/') + url.search + url.hash, title: String(bookmark.title || 'Lezione') };
  } catch {
    return undefined;
  }
}

export function HomeContent() {
  const { runtime, error } = useSiteRuntime();
  const [progress, setProgress] = useState<{ completed: number; bookmark?: Bookmark } | null>(null);
  const [progressError, setProgressError] = useState(false);

  useEffect(() => {
    if (!runtime) return;
    let generation = 0;
    const clear = () => {
      generation += 1;
      setProgress({ completed: 0 });
      setProgressError(false);
    };
    const reload = () => {
      const request = ++generation;
      void runtime.storage.list<LessonProgress>('lessonProgress').then((items) => {
        if (request !== generation) return;
        const bookmarks = items.flatMap((item) => item.bookmarks || []);
        setProgress({
          completed: items.filter((item) => item.manuallyCompleted).length,
          bookmark: localBookmark(bookmarks.at(-1)),
        });
        setProgressError(false);
      }).catch(() => {
        if (request === generation) setProgressError(true);
      });
    };
    const unsubscribe = [
      runtime.events.on('privacy:data-clearing', clear),
      runtime.events.on('privacy:progress-clearing', clear),
      runtime.events.on('privacy:data-cleared', reload),
      runtime.events.on('privacy:progress-cleared', reload),
      runtime.events.on('privacy:changed', reload),
    ];
    window.addEventListener('storage', reload);
    reload();
    return () => {
      generation += 1;
      unsubscribe.forEach((remove) => remove());
      window.removeEventListener('storage', reload);
    };
  }, [runtime]);

  return <main id="main-content" tabIndex={-1}>
    <h1>Indice</h1>
    <div className="index-boxes">
      {sections.map((section, index) => <div className="rounded-box index-actions-box" key={section.href}>
        <div className="index-actions">
          <a className="btn-wide" href={section.href}>{section.label}</a>
          <p className="index-intro-text">{section.text}</p>
          {index === 0 && <p id="indexLessonProgress" className="index-intro-text" aria-live="polite">
            {error || progressError ? 'Progresso locale non disponibile.' : progress ? <>
              Lezioni completate: {progress.completed} su 6.
              {progress.bookmark && <a href={progress.bookmark.url}> Riprendi dall’ultimo segnalibro: {progress.bookmark.title}</a>}
            </> : 'Caricamento del progresso…'}
          </p>}
        </div>
      </div>)}
    </div>
    <div className="index-corner index-corner-left">
      <p>Marzo 2026,</p>
      <p>Lavoro di tirocinio e tesi di Kevin Pescarollo</p>
    </div>
    <div className="index-corner index-corner-right">
      <p>Contatti:</p>
      <p><a href="mailto:pescarollo.kevin@spes.uniud.it">pescarollo.kevin@spes.uniud.it</a></p>
    </div>
  </main>;
}
