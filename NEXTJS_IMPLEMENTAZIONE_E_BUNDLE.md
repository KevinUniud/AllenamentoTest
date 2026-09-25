# Implementazione di Next.js e bundle TestLogica

Aggiornamento: 25 settembre 2026. Questa guida descrive l'integrazione ora
presente nei sorgenti e i passi per proseguire la migrazione. I percorsi sono
relativi alla radice del repository unico, che contiene `API_Logica`,
`Webpage_Logica` e `feedback`. Gli esiti dello snapshot del 24 settembre sono
in [VERIFICHE_RELEASE.md](VERIFICHE_RELEASE.md); quel rapporto e il relativo
bundle restano invariati e precedono la centralizzazione della CI.

Le vecchie directory `.git` dei tre componenti sono state rimosse, come
richiesto, senza creare ulteriori copie. Il confezionamento funziona senza
Git. Il versionamento appartiene alla sola radice del repository; gli ignore
e gli attributi dei componenti restano utili alle rispettive build.

GitHub Actions usa i workflow centralizzati in `.github/workflows/`:
`api.yml`, `web.yml`, `feedback.yml` e `bundle.yml`. I primi tre lavorano nella
directory del componente, il quarto nella radice. Gli aggiornamenti delle
dipendenze sono configurati in `.github/dependabot.yml`.

## 1. Stato dell'implementazione

Il Web usa **Next.js 16.3.6, React 19.3.0, TypeScript e Node 24**. Le versioni
npm sono esatte e il lockfile è incluso. Tutte le 21 pagine sono generate da
Next App Router con `output: 'export'` e `trailingSlash: true`.

La migrazione è incrementale:

| Parte | Implementazione attuale |
| --- | --- |
| Home | Componente React `HomeContent.tsx`, con riepilogo progressi locali. |
| Impostazioni | Componente React `SiteSettings.tsx`: tema, testo, daltonismo, opzioni esercizi, consensi ed esportazione/cancellazione dati. |
| Layout e runtime | Layout Next, provider React e caricamento unico dei servizi esistenti. |
| Altre 20 pagine | HTML locale adattato durante la build; controller JavaScript caricati dopo il runtime condiviso. |
| Routing | Home più route `[...slug]` con `generateStaticParams()` e inventario esplicito. |
| Produzione | Export statico servito da Nginx, senza processo Node. |
| Sicurezza | Hash CSP e manifest verificati in build; export e configurazione distribuiti insieme. |
| Bundle | Utility Python autonoma, snapshot SHA-256, inventario e checksum, senza dipendenza da Git. |

La conversione di tutti i controller in componenti React rimane un lavoro
successivo. La navigazione usa normali link `<a>` e ricarica il documento:
timer, listener e controller legacy terminano con quel documento. Non
introdurre `Link` o `router.push` nelle pagine adattate prima di convertirne
e verificare il ciclo di vita.

I confini tra componenti rimangono quelli dei
[README Web](Webpage_Logica/README.md), [API](API_Logica/README.md) e
[feedback](feedback/README.md). La modalità docente resta esclusa.

## 2. Architettura e struttura

~~~text
Sorgenti Next/React + HTML didattico + CSS/script locali
                  |
                  | npm run build
                  v
        out/ + .build/{csp-map,legacy-routes}.conf
                  |
                  v
Browser <-----> Nginx
                  |-- /api/revisione ----------> feedback HTTP
                  |-- /api/feedback/charts/* --> feedback HTTP
                  |-- altre /api/* -----------> API_Logica
                  |-- /health ----------------> API_Logica
                  `-- /web-health ------------> salute del solo Web
~~~

La scelta è coerente con il modello di
[esportazione statica di Next](https://nextjs.org/docs/app/guides/static-exports).
Redirect, header e proxy sono responsabilità di Nginx.

~~~text
Webpage_Logica/
├── src/
│   ├── app/{layout,page,not-found}.tsx
│   ├── app/[...slug]/page.tsx
│   ├── components/
│   │   ├── HomeContent.tsx
│   │   ├── SiteSettings.tsx
│   │   ├── SiteRuntimeProvider.tsx
│   │   ├── LegacyContent.tsx
│   │   └── PageStyles.tsx
│   ├── lib/pages.mjs
│   └── services/site-runtime.ts
├── lezioni/, Errori_comuni/, esercizi/, ...  # sorgenti HTML
├── scripts/, styles/, Immagini/            # sorgenti riutilizzati
├── tools/{prepare-public,generate-routes,generate-csp}.mjs
├── tests/                                 # test Node e browser
├── nginx/, ops/, deploy/
├── next.config.mjs, tsconfig.json
├── package.json, package-lock.json
└── Dockerfile
~~~

`src/lib/pages.mjs` contiene l'elenco delle 21 pagine. Legge soltanto i file
locali previsti, estrae titoli e CSS, riscrive link/asset, elimina gli script
dal markup e rifiuta handler e stili inline nei sorgenti. Le pagine adattate
hanno un `main` accessibile e un contenitore gestito da React; i controller
operano soltanto nel contenuto storico.

`SiteRuntimeProvider` carica in sequenza preferenze, eventi, contratti,
privacy e storage. Gli stessi moduli mantengono nomi del database, chiavi e
formati dei dati esistenti. `LegacyContent` carica poi gli script specifici
della pagina, senza simulare eventi `DOMContentLoaded` e senza duplicare
l'esecuzione durante Strict Mode.

`public/` è **generata**, non va modificata manualmente: `prepare-public.mjs`
la ricrea da una lista esplicita. Include asset, script e il tombstone del
service worker, senza HTML, database, configurazioni private o grafici utenti.
Anche `.next/`, `out/` e `.build/` sono artefatti rigenerabili.

## 3. Installazione, sviluppo e build

Dalla radice del repository:

~~~bash
cd Webpage_Logica
npm ci
npm run verify
npm run build
npm run typecheck
~~~

`npm ci` usa le versioni del lockfile. Per una nuova release aggiornare le
dipendenze in una modifica separata e ricollaudare: non sostituire il lockfile
con una risoluzione implicita delle versioni correnti.

Per lavorare sull'interfaccia:

~~~bash
npm run dev
~~~

La porta predefinita è 3000. Il comando prepara `public/` prima dell'avvio;
riavviarlo dopo modifiche ai sorgenti in `scripts/`, `styles/` o alle
immagini. La porta Next di sviluppo non fornisce automaticamente i proxy
same-origin delle API. Per il collaudo integrato usare i Compose canonici,
come descritto in [GUIDA_PROGETTO.md](GUIDA_PROGETTO.md) e `fast_test.md`.
Un override Nginx/HMR per `next dev` resta un'estensione facoltativa.

La pipeline `npm run build` esegue:

1. Preparazione degli asset pubblici.
2. `next build`, compreso il controllo dei componenti TypeScript.
3. Generazione dei redirect dai vecchi URL.
4. Generazione delle mappe CSP e del manifest.
5. Verifica che HTML, mappe e manifest corrispondano.

Eseguire `npm run typecheck` dopo la build, quando i tipi Next sono presenti.
`npm run verify` controlla la sintassi degli script e la suite Node.
`npm run verify:export` ricontrolla un export esistente.

La build Docker usa Node nello stage di compilazione e Nginx nello stage
finale. Il contesto è una allow-list; `.env`, dipendenze locali e dati non
entrano nell'immagine. Il runtime riceve solo `out/` e le configurazioni
prodotte dalla stessa build.

## 4. URL e compatibilità

| Vecchio URL | URL canonico |
| --- | --- |
| `/index.html` | `/` |
| `/privacy.html` | `/privacy/` |
| `/lezioni/lezione-N.html` | `/lezioni/lezione-N/`, N da 1 a 6 |
| `/Errori_comuni/index.html` | `/Errori_comuni/` |
| `/Errori_comuni/Implica.html`, altre schede | `/Errori_comuni/Implica/`, stesso nome e maiuscole |
| `/esercizi/esercitazione.html` | `/esercizi/esercitazione/` |
| `/strumenti/sandbox.html` | `/strumenti/sandbox/` |
| `/progressi/index.html` | `/progressi/` |
| `/ripasso/errori.html` | `/ripasso/errori/` |
| `/grafici/grafici.html` | `/grafici/grafici/` |

`generate-routes.mjs` produce 21 location Nginx esplicite con redirect 308.
I redirect degli index verificano la richiesta originale per non intercettare
la risoluzione interna di Nginx. `absolute_redirect off` mantiene origine e
porta del browser. La query è preservata con `$is_args$args`; il browser conserva il frammento
quando il redirect non ne fornisce uno nuovo. Gli ID delle sezioni rimangono
nei contenuti, e i segnalibri già salvati restano raggiungibili.

Per aggiungere una pagina durante la transizione, aggiungere il sorgente
all'inventario, verificare asset e collegamenti, ricostruire e collaudare il
percorso diretto e l'eventuale URL precedente. Non copiare manualmente HTML
in `public/`, perché creerebbe collisioni con le route.

## 5. CSP e distribuzione dell'export

Next produce script inline necessari all'idratazione. La build calcola
SHA-256 sul testo esatto di ciascuno script e stile nell'HTML finale.
`generate-csp.mjs` produce:

- `.build/csp-map.conf`: mappe Nginx per URI e relativi hash autorizzati.
- `.build/csp-manifest.json`: file, URL, hash degli inline e checksum HTML.

La direttiva script mantiene `'self'` e aggiunge solo gli hash della pagina;
non usa `'unsafe-inline'` o `'unsafe-eval'`. Eventuali attributi CSS generati
richiedono hash e `'unsafe-hashes'` limitati alla direttiva stile. Gli handler
inline sono rifiutati. Gli asset fingerprintati `/_next/static/` possono
essere conservati con cache immutable; gli script/CSS storici devono essere
rivalidati e il service worker di dismissione ha `no-store`.

Non modificare `out/` dopo aver generato la CSP. HTML e configurazione devono
essere distribuiti atomicamente nella stessa immagine. Il comando
`npm run verify:export` rileva HTML aggiunti, rimossi o cambiati e mappe
manomesse. La prova browser deve verificare sia il funzionamento normale sia
il blocco di uno script inline estraneo.

Gli hash statici sono una scelta specifica di questa integrazione.
La [guida CSP di Next](https://nextjs.org/docs/app/guides/content-security-policy)
descrive anche i nonce, che richiedono rendering dinamico e quindi
un'architettura di distribuzione diversa.

## 6. Come proseguire la conversione in React

Procedere per funzionalità, mantenendo gli stessi contratti HTTP e storage.

1. **Contenuti e lezioni:** trasformare gli HTML in componenti o dati locali;
   convertire navigazione, segnalibri e completamento in hook con cleanup.
2. **Laboratorio:** separare parser/formule dai controlli DOM e gestire gli
   editor e le richieste API nello stato React.
3. **Progressi e quaderno:** riutilizzare `app-storage.js`, migrare rendering,
   filtri ed export; verificare eventi di cancellazione e risposte asincrone.
4. **Grafici:** convertire polling e lightbox; interrompere timer/richieste
   alla chiusura e ripristinare focus e `inert`.
5. **Quiz:** isolare configurazione, sessione, timer, domande, correzione e
   feedback in componenti; mantenere serializzazione e payload verificati.

Per ogni passaggio verificare accesso diretto, refresh, tema/testo, tastiera,
consenso negato/concesso/revocato, cancellazione mentre una richiesta è
pendente, offline e ripresa della sessione. Un effetto deve annullare timer,
listener e richieste alla dismissione; considerare il doppio avvio di Strict
Mode. Rimuovere HTML/controller dall'adattatore solo quando la funzione
React sostitutiva è collaudata.

Passare alla navigazione SPA soltanto tra pagine convertite e verificate.
Non introdurre un secondo database, rinominare le chiavi locali o spostare
nel Web la generazione logica di `API_Logica`. Misurare peso del JavaScript
e tempi di caricamento prima di dichiarare miglioramenti prestazionali.

## 7. Collaudo browser

I test Playwright usano un export reale servito da Nginx. Non usano
`next dev`, perché non eserciterebbe CSP e redirect di produzione.
Il blocco seguente parte dalla radice del repository.

~~~bash
cd Webpage_Logica
npm ci
npx playwright install chromium
docker build --tag testlogica-web:next-check .
docker run --detach --rm --name testlogica-next-check \
  --publish 127.0.0.1:18080:80 \
  --env API_UPSTREAM=http://127.0.0.1:9 \
  --env FEEDBACK_UPSTREAM=http://127.0.0.1:9 \
  testlogica-web:next-check
curl --fail --retry 30 --retry-connrefused --retry-delay 1 \
  http://127.0.0.1:18080/web-health
TEST_BASE_URL=http://127.0.0.1:18080 npm run test:browser
docker stop testlogica-next-check
~~~

Usare un nome e una porta liberi. Su Linux privo delle librerie richieste,
Playwright offre `npx playwright install --with-deps chromium`, che installa
anche dipendenze di sistema e può richiedere privilegi amministrativi. I test intercettano le API con risposte
sintetiche e isolano i dati browser: questo collaudo non valida un deployment
reale di API e feedback. Per il controllo integrato usare uno stack di prova
con una directory dati vuota, mai i dati di produzione.

Il rapporto della release deve distinguere test automatici, prove integrate,
controlli non eseguiti e risultati. Non equivale a una pubblicazione sul server.

## 8. Creare il bundle completo senza Git

### Contenuto e prerequisiti

Il bundle standard contiene tutto **a livello di sorgenti** per costruire e
avviare i tre componenti. Servono Python 3.11+ su Linux per confezionarlo;
Docker/Compose e accesso ai registry per ricostruire le immagini.

~~~text
testlogica-<release>/
├── .github/{workflows/,dependabot.yml}
├── API_Logica/
├── Webpage_Logica/
├── feedback/
├── tools/build-bundle.py
├── tools/test_build_bundle.py
├── README.md, GUIDA_PROGETTO.md, fast_test.md
├── NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md
├── VERIFICHE_RELEASE.md
├── REVISIONI.env
├── MANIFEST.txt
└── SHA256SUMS
~~~

Sono inclusi sorgenti, asset originali, lockfile, test, Dockerfile, Compose,
workflow centralizzati, esempi env e operazioni di deploy. Sono esclusi cronologia Git, dipendenze,
build, cache, `public/` generata del Web, risultati Playwright, env reali,
database, report/grafici utenti e credenziali note. I filtri sono espliciti
in `tools/build-bundle.py`; non dipendono da `.gitignore`. Eventuali segreti
salvati con nomi imprevisti richiedono una revisione dei sorgenti.

I file `feedback/data/.gitkeep` e gli esempi env sono mantenuti. Non occorre
creare altre copie delle vecchie directory Git. I dati di produzione e i
backup operativi del database restano esterni alla release.

### Comando di confezionamento

Congelare le modifiche ai sorgenti, completare i controlli e creare un nuovo
rapporto `VERIFICHE_NUOVA_RELEASE.md` con gli esiti reali. Conservare il rapporto
storico del 24 settembre; il nuovo rapporto verra inserito nel bundle con il
nome canonico `VERIFICHE_RELEASE.md`. Dalla directory di questa guida:

~~~bash
python3 -m unittest discover -s tools -p 'test_build_bundle.py'
python3 tools/build-bundle.py \
  --release testlogica-20260925-monorepo \
  --output dist/bundles \
  --verification-report VERIFICHE_NUOVA_RELEASE.md \
  --release-ready
~~~

Usare un identificativo nuovo per ogni consegna: l'utility rifiuta
sovrascritture, link simbolici e file speciali. Lo staging temporaneo viene
eliminato automaticamente al termine. Non vengono create copie permanenti
oltre all'archivio richiesto e al suo checksum.

Gli output sono `dist/bundles/<release>.tar.gz` e `.tar.gz.sha256`.
Il programma rilegge i byte archiviati e verifica che corrispondano
all'inventario e ai checksum. `--release-ready` richiede un rapporto non
vuoto, ma **non esegue né certifica i test applicativi**. Senza rapporto il
manifest indica `not_verified`.

`REVISIONI.env` contiene `RELEASE_TAG`, `RELEASE_REVISION`,
`WEB_RELEASE_REVISION` e `FEEDBACK_RELEASE_REVISION`. Le revisioni sono
`sha256-<digest>` dell'albero canonico di ciascun componente: percorso,
tipo, permesso normalizzato e hash dei file. Identificano i sorgenti senza
commit Git. Il checksum del tar identifica l'intera consegna.

### Verificare una consegna

~~~bash
cd dist/bundles
sha256sum --check testlogica-20260925-monorepo.tar.gz.sha256
tar --list --gzip --file testlogica-20260925-monorepo.tar.gz
mkdir verifica-nextjs
tar --extract --gzip --no-same-owner \
  --file testlogica-20260925-monorepo.tar.gz --directory verifica-nextjs
cd verifica-nextjs/testlogica-20260925-monorepo
sha256sum --check SHA256SUMS
cd Webpage_Logica
npm ci
npm run verify
npm run build
npm run typecheck
~~~

Usare una directory di verifica nuova. Controllare una sola radice release,
presenza dei tre componenti e assenza dei file esclusi. Ripetere il collaudo
browser sull'immagine costruita dai sorgenti estratti. Se occorre correggere
un sorgente, confezionare una release nuova e verificarla di nuovo. La copia
estratta serve al collaudo e può essere eliminata dopo l'uso.

### Installazione sul server

1. Verificare il checksum esterno prima dell'estrazione e quello interno dopo.
2. Estrarre in `/srv/testlogica/releases/<release>`, separato da
   `/srv/testlogica/shared/{feedback-data,state}`.
3. Creare gli env reali dagli esempi solo se assenti, con permessi `0600`.
   Riportare i valori di `REVISIONI.env` negli env API/Web pertinenti;
   configurare UID/GID, percorsi persistenti, URL pubblico, CORS e rete.
4. Seguire i README canonici: deploy API con `scripts/deploy-server.sh`,
   poi Web/feedback con `ops/server-deploy.sh`.
5. Verificare health, readiness, vecchi URL, route Next, CSP, un quiz e i
   flussi feedback nel contesto previsto. Non usare report reali per smoke.
6. Conservare immagini e stato della release precedente per il rollback
   gestito dagli script. Non sovrascrivere il database con il contenuto del bundle.

I deploy script accettano le revisioni basate su checksum e non richiedono
la ricreazione di Git. Un rollback applicativo e un restore del database
sono operazioni distinte; seguire le procedure feedback per i dati.
Non è stato eseguito alcun deploy sul server come parte del confezionamento.

### Estensione per un bundle offline

Il tar standard non include immagini Docker o dipendenze già installate.
Per una consegna senza accesso ai registry costruire e collaudare prima
le tre immagini per l'architettura di destinazione, taggate con la release.
Esportarle, per esempio:

~~~bash
mkdir artifacts
docker image save --output artifacts/testlogica-images.tar \
  testlogica-api:RELEASE testlogica-web:RELEASE testlogica-feedback:RELEASE
sha256sum artifacts/testlogica-images.tar > artifacts/testlogica-images.tar.sha256
~~~

`RELEASE` va sostituito con il tag effettivo. Costruire un pacchetto esterno
che includa bundle sorgenti, tar immagini, checksum, architettura, ID/digest
e istruzioni `docker image load --input ...`. La utility sorgenti non
incorpora automaticamente `artifacts/`.

Per usare gli script server esistenti con immagini preimportate verificare
il loro comportamento sui tag già presenti: i tag release sono immutabili
e un percorso che tenta di ricostruirli viene rifiutato. Documentare e
collaudare una procedura di avvio con `--no-build` o un'estensione esplicita
dei deploy script prima di consegnare un bundle dichiarato offline.
