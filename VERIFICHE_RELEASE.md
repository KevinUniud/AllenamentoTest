# Verifiche della release TestLogica Next.js

Release: `testlogica-20260924-nextjs`.
Controlli eseguiti il 23–24 settembre 2026 (Europe/Rome).

## Risultato e ambito

Next.js App Router esporta tutte le 21 pagine applicative. Home e impostazioni
sono React; le altre pagine usano l'adattatore dei contenuti HTML e i controller
esistenti. La navigazione ricarica il documento. Questa release non completa
la riscrittura di tutti i controller in React e non attiva una SPA.

Il collaudo Web usa Nginx reale su loopback, con API simulate in Playwright.
Non sono stati inviati report a servizi reali, usati database di produzione,
pubblicati repository o eseguiti deploy sul server.

## Controlli superati

| Controllo | Esito |
| --- | --- |
| Frontend `npm run verify` | 51 script con sintassi valida; 184 test Node superati in 29 file, zero skip/failure. |
| `npm run build` | Export riuscito: 21 pagine applicative e documenti tecnici/404; CSP generata e verificata per 24 HTML. |
| `npm run typecheck` | Superato con TypeScript e tipi Next generati. |
| Build Docker Web | Superata da Node 24.13.0 Alpine; runtime Nginx con solo export e configurazioni della stessa build. |
| Chromium / Playwright | 34 test superati: tutte le route, redirect/query/frammento, 404, impostazioni, persistenza e cancellazione, lezioni, laboratorio, quiz, grafici e mobile. |
| CSP nel browser | Nessuna violazione inattesa o errore di idratazione; uno script inline estraneo viene bloccato nella prova negativa dedicata. |
| API pytest | Suite finale: 192 test superati, zero skip/failure. |
| SWI-Prolog | Runner `prolog/tests/run_tests.pl` superato: 14 test. |
| Build Docker API | Superata; test Prolog rieseguiti nell'immagine senza rete. |
| Feedback pytest | 64 test superati in container isolato, senza rete o dati reali. |
| Build Docker feedback | Target test e immagine runtime costruiti; controlli Ruff/mypy del target test soddisfatti anche tramite cache Docker. |
| Utility bundle | 21 test Python superati; snapshot, filtri, checksum, rifiuto symlink/file speciali e sovrascritture. |
| Inventario sorgenti | 81 file API, 191 Web e 36 feedback; documentazione e utility aggiunte alla radice del bundle. |
| Vecchie directory Git | Assenti nei tre componenti; nessuna nuova copia o cronologia creata. |

L'ultima suite browser completa è terminata con `34 passed (24.1s)`.
Le API simulate permettono di verificare il quiz fino al riepilogo, senza
submission di feedback. Le prove mobile usano viewport 390 × 844 e coprono
home e lezione con impostazioni, focus e larghezza dei contenuti.

## Osservazioni emerse dal collaudo

I redirect Nginx ora mantengono origine e porta del browser. Per gli index,
la verifica di `request_uri` evita di redirigere la risoluzione interna di
Nginx e impedisce cicli sulla home e sugli indici delle sezioni.

Nel primo giro API un caso Prolog a cinque atomi ha superato il proprio limite
di tempo: 191 test passati e un timeout. I due casi mirati sono poi passati
senza modifiche; una seconda suite completa ha superato tutti i 192 test
in 36,60 secondi. Non sono state cambiate soglie o logica API. Il test può
risentire del carico della macchina.

## Limiti della consegna

Il bundle contiene i sorgenti dei tre componenti, asset originali, configurazioni,
lockfile Web, test e istruzioni. Non include dipendenze installate o immagini
Docker esportate: la ricostruzione richiede accesso ai registry. Le dipendenze
Python mantengono i vincoli dei componenti esistenti, senza un nuovo lockfile.

Non è stato collaudato un deployment pubblico con TLS, carico reale, un invio
feedback attraverso l'intero stack o un rollback sul server. I contratti
backend e la conservazione feedback sono verificati dalle rispettive suite.
Non sono stati misurati miglioramenti prestazionali rispetto al sito precedente.

Il manifest CSP rimane un artefatto di build; l'immagine contiene le mappe CSP,
i redirect e l'export corrispondente. Non modificare l'HTML compilato dopo la
generazione degli hash.

Il confezionamento rilegge e verifica i byte archiviati. `SHA256SUMS` consente
la verifica dei file estratti; il file `.tar.gz.sha256` verifica l'archivio intero.
Le revisioni in `REVISIONI.env` identificano gli alberi sorgente senza Git.
