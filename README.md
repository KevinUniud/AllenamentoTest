# TestLogica - workspace di integrazione

Questa directory e soltanto il workspace locale usato per collaudare insieme i
tre componenti TestLogica. Non deve essere pubblicata come un ulteriore
repository e nessun file qui presente e richiesto dalle build autonome. Il
workspace non contiene un Compose aggregato: si usano esclusivamente i Compose
canonici dei repository autonomi.

I tre componenti autonomi da aggiornare sono:

| Directory del componente | Responsabilita | Documentazione canonica |
| --- | --- | --- |
| `API_Logica/` | API e generatore degli esercizi logici, senza dati o codice feedback | [TestLogica API](API_Logica/README.md) |
| `Webpage_Logica/` | Next.js/React, contenuti didattici, Nginx e dati locali del browser | [TestLogica Web](Webpage_Logica/README.md) |
| `feedback/` | Ricezione dei report, conservazione, elaborazione periodica e pubblicazione dei grafici | [TestLogica Feedback](feedback/README.md) |

Le tre directory contengono il proprio Dockerfile, Compose, esempio delle
variabili d'ambiente, ignore Git, attributi Linux, CI e istruzioni di
pubblicazione. Possono quindi essere copiate separatamente nella radice dei tre
repository, includendo i rispettivi file nascosti.

Le vecchie directory `.git` dei tre componenti sono state rimosse senza creare
altre copie. Sorgenti, `.gitignore`, `.gitattributes` e workflow `.github` restano
disponibili. La procedura del bundle usa snapshot dei file identificati tramite
checksum e non richiede uno storico Git locale.

## Confini

- L'API non contiene pagine o stato del browser.
- Il Web non contiene codice Python o regole Prolog e raggiunge l'API via HTTP.
- `feedback` e l'unico componente responsabile della ricezione di
  `/api/revisione`, della conservazione dei report e della generazione periodica
  dei grafici. L'API logica non importa, configura o conserva feedback.
- I percorsi sono case-sensitive: usare esattamente `API_Logica`,
  `Webpage_Logica`, `feedback`, `Errori_comuni` e `Immagini`.
- Il punto 15, modalita docente, resta escluso da tutti i componenti.

La ricerca globale, l'indicatore Online/Offline e la PWA sono stati rimossi dal
repository Web. Un tombstone temporaneo del service worker resta distribuito
senza cache o handler `fetch` unicamente per disattivare le installazioni delle
release precedenti.

## Avvio locale

Per eseguire insieme i componenti:

- avviare l'API con il Compose di `API_Logica/`;
- avviare Web, feedback HTTP e feedback worker con il Compose di
  `Webpage_Logica/`, mantenendo `feedback/` come cartella sorella;
- seguire i controlli e le impostazioni descritti nei rispettivi README.

I due comandi completi sono mantenuti, senza istruzioni aggiuntive, in
`fast_test.md`. Per il server si usano gli script di deploy contenuti nei singoli
componenti. Il piano di
[implementazione Next.js e creazione del bundle](NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md)
descrive l'integrazione statica realizzata, i passi per proseguire la conversione
dei controller in React e la preparazione di un archivio sorgenti completo dei
tre componenti, con manifest, checksum e istruzioni di installazione.
Il confezionamento e automatizzato da `tools/build-bundle.py`; gli esiti del
collaudo sono riportati in [VERIFICHE_RELEASE.md](VERIFICHE_RELEASE.md).
La consegna sorgenti e `dist/bundles/testlogica-20260924-nextjs.tar.gz`,
affiancata dal checksum SHA-256. Non include immagini Docker per uso offline.

## Documenti storici del workspace

`FEATURE_BACKLOG.md`, `FEATURE_IMPLEMENTATION_ROADMAP.md`,
`FORMULA_CONSTRUCTION_PLAN.md` e `MIGRATION.md` restano materiale storico o di
pianificazione del workspace. Non vengono copiati automaticamente nei tre
repository e non sono fonti operative: i contratti correnti sono documentati nei
README autonomi e nell'OpenAPI generata dal codice.
