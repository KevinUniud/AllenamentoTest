# TestLogica Web

Frontend didattico di TestLogica con Next.js App Router, React e TypeScript,
esportato in file statici e servito da Nginx. Offre lezioni, quiz generati dall'API, progressi personali,
quaderno degli errori, grafici, modalita parlata e un Laboratorio di logica.

Questa directory e la radice del repository **Webpage**. Il codice e i test Web
restano autonomi; il Compose integrato si aspetta invece il repository `feedback`
come cartella sorella. L'API logica resta esterna ed e raggiunta tramite un
upstream configurabile.

## Funzionalita e confini

- Lezioni ed esercizi su logica proposizionale e dei predicati.
- Configuratore di sessione, ripresa, scadenze e adattamento locale spiegabile.
- Forma parlata testuale delle formule, senza lettura vocale o sintesi audio delle domande.
- Percorsi di trasformazione dalla formula della domanda alla risposta corretta:
  ogni passaggio mostra legge generale, applicazione locale e formula ottenuta.
- Dashboard, quaderno errori ed export JSON/CSV basati sui dati del browser.
- Impostazioni accessibili per tema, dimensione testo e daltonismo.

Una sessione quiz puo contenere al massimo 100 domande. Il browser legge da
`/api/capabilities` il limite del singolo batch e suddivide automaticamente la
sessione in piu richieste senza modificare i payload delle domande; con il
deployment standard vengono inviati al massimo 50 elementi per richiesta.
- Laboratorio per comporre formule con simboli logici, costruirle collegando nodi
  nell'albero e richiedere analisi, tabella di verita e confronti all'API.
- Feedback senza nome o account e dati demografici opzionali con consensi separati.

## Requisiti

- Browser moderno con JavaScript, IndexedDB e SVG.
- Node.js 24 e npm per sviluppo, controlli e build.
- Docker con Compose v2 per l'avvio containerizzato.
- Un'istanza separata di TestLogica API per quiz e analisi del Laboratorio.
- Il repository `feedback` collocato accanto a `Webpage_Logica` per l'avvio Compose.

Installare le dipendenze bloccate in `package-lock.json` con `npm ci`.
Tutti i percorsi sono case-sensitive su
Linux; in particolare `Immagini/` usa la `I` maiuscola.

## Avvio rapido

La struttura prevista e:

```text
Progetti/
├── Webpage_Logica/
└── feedback/
```

Creare la directory persistente come utente normale **prima** dell'avvio. In
questo modo Docker non la crea come `root` e ricevute e grafici restano cancellabili
senza permessi amministrativi:

```bash
cd Progetti/feedback
./scripts/prepare-data.sh --write-env
cd ../Webpage_Logica
cp .env.example .env
docker compose up --build
```

Prima di `docker compose up`, riportare nel file `Webpage_Logica/.env` i valori
mostrati da `id -u` e `id -g` se sono diversi da `1000`. La preparazione va
eseguita senza `sudo`: le directory e tutti i file creati dai container avranno
così la stessa identità dell'utente host e potranno essere rimossi normalmente.
Lo script gestisce anche il contesto del bind mount sugli host SELinux senza usare
`sudo`. Il suo `--write-env` aggiorna `feedback/.env`, non il file `.env` usato da
questo Compose Web: riportare quindi in quest'ultimo i due valori UID/GID generati.

Aprire quindi <http://localhost:12345>. I processi `feedback`
e `feedback-worker` non pubblicano la porta `5555`: soltanto Nginx Web raggiunge
il processo HTTP come `http://feedback:5555` sulla rete Docker interna. Non e quindi necessario renderlo
raggiungibile dalla LAN o configurare una porta feedback nel firewall.

L'API logica resta configurabile con `API_UPSTREAM`. Il valore predefinito usa il
mapping Linux `host.docker.internal:host-gateway` per raggiungere la porta `5000`
dell'host.

Controlli utili:

```bash
npm ci
npm run verify
npm run build
npm run typecheck
docker compose config
docker build .
```

`/web-health` controlla soltanto Nginx e viene usato dall'healthcheck del container.
`/health` e invece inoltrato all'API e ne riflette la disponibilita.

## Sviluppo Next.js

`npm run dev` prepara gli asset pubblici e avvia Next sulla porta 3000. Questa
porta serve l'interfaccia; per usare le API same-origin e verificare CSP e redirect
di produzione utilizzare il Compose su 12345. Il proxy di sviluppo con HMR non e
ancora predisposto. Dopo modifiche a `scripts/`, `styles/` o immagini riavviare
`npm run dev` per rigenerare `public/`.

La migrazione e incrementale: home e impostazioni globali sono React; le altre
20 pagine provengono dagli HTML locali tramite `src/lib/pages.mjs`. L'adattatore
riscrive URL e asset, rimuove gli script dal markup e fornisce un `main`.
`LegacyContent` carica i controller dopo il runtime condiviso. I normali link
`<a>` ricaricano il documento; i controller esistenti durano fino alla sua chiusura.
Non usare navigazione SPA prima di averne convertito e verificato il ciclo di vita.

`npm run build` genera `out/`, redirect per i 21 URL `.html` precedenti e hash CSP
per ogni documento. `public/`, `.next/`, `out/` e `.build/` sono rigenerabili.
L'immagine finale contiene solo l'export e le configurazioni Nginx della stessa
build; Node e le dipendenze di sviluppo rimangono nello stage di compilazione.

## Deploy sul server effettivo

Il deploy di produzione usa `compose.server.yml`, separato dal Compose di
sviluppo. Le immagini Web e feedback ricevono lo stesso `RELEASE_TAG`; feedback
resta su una rete dedicata `internal` senza porte host, mentre il Web raggiunge
l'API tramite la rete esterna `testlogica-backend` e l'alias `api-logica`. Anche
tale rete deve avere `Internal=true`: i preflight API e Web la creano in modo
idempotente e rifiutano una rete omonima non privata.

Il layout server consigliato separa release e stato persistente:

```text
/srv/testlogica/
├── releases/<release-id>/{API_Logica,Webpage_Logica,feedback}
└── shared/{feedback-data,state}
```

Una sola volta, l'amministratore del server deve creare `/srv/testlogica/shared`
e `/srv/testlogica/shared/state` con proprietario l'utente/gruppo di deployment e
modo `0700`. In alternativa usare percorsi assoluti equivalenti gia posseduti da
quell'utente e riportarli nei due `.env.server`. Da quel momento preparazione,
backup, deploy, rollback e cancellazione dei dati si eseguono senza `sudo`; i
container feedback usano lo stesso UID/GID dell'utente host.

Preparazione di ogni release, come utente di deployment non amministratore:

```bash
cd Progetti/Webpage_Logica
cp .env.server.example .env.server
chmod 600 .env.server
# Impostare RELEASE_TAG, WEB_RELEASE_REVISION, FEEDBACK_RELEASE_REVISION,
# FEEDBACK_UID=$(id -u), FEEDBACK_GID=$(id -g), i percorsi assoluti shared
# e, quando l'edge e attivo, PUBLIC_BASE_URL=https://dominio-effettivo.
# Per un bundle senza commit usare gli identificatori del manifest come revisioni.

cd ../API_Logica
cp .env.server.example .env.server
chmod 600 .env.server
# Impostare RELEASE_TAG, RELEASE_REVISION, CORS_ORIGINS HTTPS e
# DEPLOY_STATE_DIR=/srv/testlogica/shared/state/api.
./scripts/deploy-server.sh

cd ../Webpage_Logica
./ops/server-deploy.sh
```

Il deploy Web verifica repository e percorsi case-sensitive, configurazione,
UID/GID, porta, rete privata e presenza dell'API; prepara il bind feedback con
permessi privati; crea immagini locali taggate; esegue `compose up --wait` e smoke
test senza inserire report feedback. Per default rifiuta worktree sporchi e tag
`latest` o di esempio.

Se avvio o smoke falliscono durante un aggiornamento, il deploy verifica ID e
revisioni delle immagini registrate e ripristina automaticamente la release
precedente. Al primo deploy arresta lo stack non validato; se anche il recupero
fallisce arresta lo stack in modalita fail-closed. Lo stato attivo viene scritto
soltanto dopo uno smoke completo. Anche il puntatore alla penultima release viene
promosso solo dopo lo smoke: una release candidata rifiutata non altera il target
di rollback gia verificato.

Il preflight rifiuta percorsi relativi, symlink, directory condivise troppo
ampie, sorgenti modificabili da gruppo/altri e variazioni accidentali di project
name, storage, UID/GID, porta o rete rispetto alla release attiva. I tag immagine
sono immutabili: un tag gia presente non viene ricostruito.

`active.env` e `rollback.env` vengono conservati in `DEPLOY_STATE_DIR`, che deve
essere persistente e stare fuori da entrambe le directory release.
`DEPLOY_PULL_BASE_IMAGES=1` aggiorna le immagini base in produzione; `0` e
riservato ai collaudi offline con cache gia validata. Il flag `--allow-dirty`
esiste per collaudi isolati, non per una release reale. `--skip-backup` va usato
soltanto al primo avvio senza database. Gli script non eseguono commit o push.

Il Web ascolta esclusivamente su `127.0.0.1:12345`. Un reverse proxy sull'host
deve terminare TLS, redirigere HTTP a HTTPS e aggiungere HSTS. L'esempio
`deploy/nginx-edge.example.conf` applica inoltre il rate limit per indirizzo
client a `/api/revisione` e limiti distinti di frequenza/connessioni alle altre
route `/api/`. Il container API mantiene anche una soglia globale di concorrenza,
indipendente dagli indirizzi condivisi dietro NAT. Il limite non va applicato nel Nginx interno: dietro
un edge Docker vedrebbe l'indirizzo del proxy e diventerebbe involontariamente
globale. L'edge inoltra gli header al Web, ma la route interna continua a
cancellare `X-Real-IP` e `X-Forwarded-For` prima del servizio feedback.

Nel Compose server il Web e l'unico servizio collegato anche alla rete bridge
`web-loopback`: Docker Linux richiede un gateway non-`internal` per attivare il
binding su `127.0.0.1`. API e feedback non appartengono a questa rete e non
pubblicano porte; continuano a essere raggiungibili soltanto sulle rispettive
reti applicative `internal`.

Dopo avere sostituito dominio e percorsi dei certificati nell'esempio edge:

```bash
nginx -t
./ops/server-smoke.sh
# Con PUBLIC_BASE_URL=https://dominio.example in .env.server lo smoke
# verifica anche HTTPS e Strict-Transport-Security.
```

La porta indicata nei tre `proxy_pass` dell'edge deve coincidere con `WEB_PORT`;
l'esempio usa il valore predefinito `12345`. Il virtual host di default rifiuta
Host sconosciuti e il redirect HTTP usa sempre il nome canonico configurato.

Un rollback applicativo richiede che le immagini della release precedente siano
ancora presenti localmente:

```bash
./ops/server-rollback.sh
```

Prima del cambio immagine viene creato un backup SQLite consistente. Il rollback
non ripristina mai automaticamente il database: in caso di migrazione
incompatibile occorre fermare lo stack e seguire la procedura di restore del
README `feedback` usando un backup scelto esplicitamente.
Se il processo feedback e guasto e non consente il backup, `--skip-backup` e
ammesso soltanto dopo avere verificato checksum e disponibilita di un backup
recente esterno al server.

Sul firewall pubblico devono restare aperte soltanto le porte dell'edge (in
genere `80/tcp` e `443/tcp`); `5000` e `5555` non vanno esposte. Verificare anche
il rinnovo automatico del certificato con il sistema scelto dall'host.

## Configurazione

Copiare `.env.example` in `.env` e modificare solo i valori necessari:

| Variabile | Default | Responsabilita |
| --- | --- | --- |
| `WEB_PORT` | `12345` | Porta HTTP pubblicata dal container web. |
| `API_UPSTREAM` | `http://host.docker.internal:5000` | Origine dell'API logica usata dal proxy `/api/*` e da `/health`. |
| `API_PROXY_TIMEOUT_SECONDS` | `125` | Timeout del proxy logico, con margine sul massimo API di 120 secondi. |
| `FEEDBACK_UID` / `FEEDBACK_GID` | `1000` | Identita non amministrativa usata dal container feedback sul bind mount. |
| `FEEDBACK_DATA_DIR` | `../feedback/data` | Directory host privata condivisa dai due processi feedback. |
| `FEEDBACK_RETENTION_DAYS` | `365` | Durata massima dei report ricevuti. |
| `FEEDBACK_MAX_BODY_BYTES` | `2097152` | Dimensione massima del report accettata dal servizio. |
| `FEEDBACK_MAX_RECEIPTS` | `100000` | Quota globale del numero di ricevute persistite. |
| `FEEDBACK_MAX_STORAGE_BYTES` | `1073741824` | Quota globale in byte dello storage delle ricevute. |
| `FEEDBACK_MIN_FREE_BYTES` | `67108864` | Spazio libero minimo preservato sul filesystem. |
| `FEEDBACK_MIN_AGGREGATE_SESSIONS` | `10` | Campione minimo per pubblicare dati aggregati. |
| `FEEDBACK_SNAPSHOTS_TO_KEEP` | `3` | Snapshot pubblicati conservati. |
| `FEEDBACK_PUBLISH_INTERVAL_SECONDS` | `86400` | Cadenza di elaborazione e pubblicazione. |
| `FEEDBACK_RETENTION_INTERVAL_SECONDS` | `3600` | Cadenza indipendente di retention e compattazione. |
| `FEEDBACK_WORKER_HEARTBEAT_SECONDS` | `15` | Frequenza del segnale del worker. |
| `FEEDBACK_WORKER_STALE_SECONDS` | `60` | Eta massima del segnale accettata dalla readiness; deve superare il doppio dell'heartbeat. |
| `FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS` | `900` | Durata massima di un ciclo del worker prima del riavvio. |
| `FEEDBACK_STOP_GRACE_SECONDS` | `960` | Tempo concesso da Docker per terminare un ciclo: deve essere almeno timeout job + heartbeat + 1 secondo. |
| `FEEDBACK_CHARTS_REFRESH_SECONDS` | `300` | Intervallo della galleria visibile, limitato dal browser tra 30 secondi e 24 ore. |

`FEEDBACK_UPSTREAM` non e un'opzione esposta in `.env`: nel Compose e fissato al
DNS privato `http://feedback:5555`. I due container feedback non hanno `ports`,
appartengono solo alla rete `feedback-internal` e condividono il bind mount
`FEEDBACK_DATA_DIR`, per impostazione predefinita `../feedback/data`.
Il processo HTTP salva e serve gli asset, mentre il worker applica retention e
pubblicazione senza rallentare il POST. Non viene
creato alcun volume Docker con file posseduti da root. `create_host_path: false`
fa fallire esplicitamente l'avvio se la directory non e stata preparata dall'utente.

`POST /api/revisione` viene inoltrato al servizio feedback senza trasformare il
corpo JSON e senza inoltrare `X-Real-IP` o `X-Forwarded-For`. Le altre route
`/api/*` restano di proprieta dell'API logica. Nginx non memorizza il body in un
file temporaneo. In produzione l'edge TLS limita la submission a 60 richieste al
minuto per indirizzo, con un burst di 60, e disattiva l'access log della route.
Il margine permette a una classe dietro un unico IP NAT di inviare
contemporaneamente; l'indirizzo non viene inoltrato al feedback. Eventuali error
log tecnici e la loro retention dipendono dalla configurazione operativa
dell'edge e non contengono il body JSON.

Il browser usa URL relativi `/api/...`: Nginx evita CORS e mixed content e inoltra
le richieste all'origine configurata. La Content Security Policy consente soltanto
risorse locali e connessioni alla stessa origine web.

## Struttura del repository

| Percorso | Contenuto e responsabilita esclusiva |
| --- | --- |
| `.github/` | Workflow CI: verifica Node e build dell'immagine Docker. |
| `src/app/` | Layout, home, route statica parametrica e pagina 404 Next. |
| `src/components/` | Home, impostazioni, provider condiviso e adattatore dei contenuti HTML. |
| `src/services/`, `src/lib/` | Accesso al runtime browser e inventario/trasformazione delle pagine. |
| `deploy/` | Esempi per l'edge TLS esterno; non viene incluso nell'immagine Web. |
| `Errori_comuni/` | Schede editoriali statiche sugli errori ricorrenti; non contiene gli errori personali. |
| `Immagini/` | Immagini semantiche e diagrammi usati nelle domande visuali. |
| `esercizi/` | Configurazione, esecuzione, correzione e risultato delle sessioni quiz. |
| `grafici/` | Pagina della galleria e unico SVG neutro privo di dati; tutti i grafici sono pubblicati a runtime dal servizio feedback. |
| `lezioni/` | Sei contenuti didattici sequenziali con verifiche locali. |
| `nginx/` | Template del server statico, proxy API, header di sicurezza e healthcheck. |
| `ops/` | Preflight, deploy, smoke test e rollback del server; non e contenuto pubblico. |
| `progressi/` | Dashboard personale calcolata da IndexedDB con filtri ed export. |
| `ripasso/` | Quaderno personale e deduplicato degli errori salvati. |
| `scripts/` | Codice runtime del browser: storage, quiz, lezioni, rendering e servizi pagina. |
| `strumenti/` | Laboratorio di logica interattivo; non contiene il flusso quiz. |
| `styles/` | Token, componenti storici e fogli specifici per quiz, strumenti e grafici. |
| `tests/` | Test Node di contratti, storage, sicurezza, accessibilita e regressione. |
| `tools/` | Preparazione asset, generazione redirect/CSP e verifiche; non viene pubblicato da Nginx. |

Gli HTML sono sorgenti della transizione: `index.html` fornisce metadata e stili
della home, il cui contenuto e in `HomeContent.tsx`; `privacy.html` contiene
l'informativa. Le impostazioni e i consensi sono in `SiteSettings.tsx`.
`service-worker.js` non e una
funzione PWA: e un tombstone temporaneo, privo di handler `fetch`, che cancella le
cache `testlogica-*` e si deregistra sui browser controllati da release precedenti.
Il codice attuale non registra alcun service worker e non cancella IndexedDB o
`localStorage` durante questa migrazione.

### Cartelle con nomi o dati affini

- `Errori_comuni/` e materiale pubblico uguale per tutti; `ripasso/` legge soltanto
  gli errori personali del browser.
- `grafici/` contiene soltanto la vista pubblica e il segnaposto neutro, mentre il
  servizio feedback possiede gli output aggregati; `progressi/` calcola dal vivo
  indicatori ed SVG dai tentativi locali.
- `Immagini/` contiene asset didattici delle domande; `styles/` non deve incorporare
  dati o logica applicativa.
- `scripts/` e runtime servito al browser; `tools/` e tooling di sviluppo.
- `esercizi/` possiede la sessione guidata; `strumenti/` offre analisi libera di una
  formula e non salva risultati del quiz.

Questi confini evitano duplicazioni senza rinominare URL pubblici gia usati dal
progetto precedente.

## Moduli principali

- `scripts/app.js`: bootstrap globale e rimozione selettiva delle vecchie cache PWA.
- `scripts/app-storage.js`, `privacy-controls.js`, `data-contracts.js`: IndexedDB,
  consensi e contratti versionati.
- `scripts/quiz.js` e moduli `quiz-*`: configurazione, richieste batch, stato,
  rendering, timer, ripresa, feedback e report.
- `scripts/formula-transformation*.js`: valida e rende la derivazione autentica
  dalla formula iniziale alla risposta; non la confonde con la costruzione AST.
- `scripts/formula-syntax.js`: conversione rigorosa tra simboli visuali e sintassi
  funzionale inviata all'API.
- `scripts/formula-construction*.js` e `formula-tree.js`: struttura sintattica e
  rendering accessibile degli alberi, con operandi ordinati e formule complete.
- `scripts/logic-tree-builder.js`: stato del costruttore visuale a nodi, separato
  dal rendering e dal trasporto HTTP.
- `scripts/logic-sandbox.js`: controller del Laboratorio e confine dei payload API.
- `scripts/dashboard.js`, `error-notebook*.js`, `results-export.js`: viste personali
  ed export dei dati autorizzati.
- `scripts/feedback-charts.js`: valida il manifest pubblico e il numero aggregato
  di sessioni, accetta soltanto i 22 ID previsti e gestisce aggiornamento manuale,
  polling moderato e sospensione quando la pagina non e visibile.

Gli stili globali sono in `styles/base.css` e `styles/components.css`; ogni area
aggiunge un foglio dedicato. Il Laboratorio riusa token, tipografia monospaziata,
box arrotondati e stati focus del sito invece di introdurre un design separato.

## Dati, privacy e scadenze

I consensi per salvataggio locale, invio del feedback e dati demografici sono
indipendenti e inizialmente disattivati. Prima del consenso non vengono creati
record applicativi in IndexedDB. Sessioni incomplete scadono dopo 30 giorni;
tentativi, errori e sessioni concluse dopo un anno. Le impostazioni permettono
cancellazione selettiva e totale ed emettono eventi che aggiornano le viste aperte.

Con il consenso al feedback, la conferma finale invia al servizio feedback lo stesso report
JSON storico, senza aggiungere nome o account: `Initial Data` contiene data e ora
d'inizio, durata, conteggi di domande corrette ed errate e opzioni attive; ogni
elemento di `Domande` contiene tipologia, tempo di risposta, esito, testo della
domanda, opzioni mostrate, risposta dell'utente e risposta corretta; `Feedback`
contiene le cinque valutazioni da 1 a 5 (`Aspettative test`, `Utilità ausili`,
`Utilità lezioni`, `Difficoltà test` e `Controllo`). Se autorizzati separatamente,
in `Initial Data` vengono inclusi anche `Età`, `Istituto di appartenenza` e
`Indirizzo` dichiarati.
I nomi effettivi delle chiavi mantengono accenti e maiuscole definiti dal contratto
storico del quiz.

La singola submission usa inoltre un UUIDv4 casuale nell'header HTTP
`Idempotency-Key`, mai nel JSON. In caso di timeout o retry la pagina riutilizza
la stessa chiave e lo stesso body gia costruito; una modifica della valutazione o
dei dati demografici e l'avvio di una nuova sessione generano invece una nuova
chiave. Questo evita duplicati senza cambiare il payload storico.

Il feedback non va considerato anonimo in senso assoluto: timestamp, contenuto
del quiz e dati demografici eventualmente autorizzati possono rendere un report
distinguibile. Nginx disattiva il log di accesso per questa route e non inoltra
gli header con l'indirizzo IP del browser. L'indirizzo viene usato in memoria
esclusivamente dall'edge TLS per applicare il limite antiabuso alla submission;
eventuali log tecnici di errore o di superamento del limite dipendono dalla
configurazione e dalla retention applicate dal gestore dell'installazione.

Il servizio feedback conserva i report per 365 giorni per impostazione
predefinita; il gestore puo modificare la durata con
`FEEDBACK_RETENTION_DAYS` e i report scaduti vengono eliminati automaticamente.
La ricezione non genera grafici: uno scheduler del servizio li elabora e li
pubblica alla cadenza `FEEDBACK_PUBLISH_INTERVAL_SECONDS`, pari a 86400 secondi
(un giorno) per impostazione predefinita. Revocare il consenso blocca gli invii
successivi, ma non richiama ne cancella retroattivamente i report gia trasmessi.

La galleria interroga soltanto `GET /api/feedback/charts/manifest` e scarica PNG
aggregati versionati. Il browser ignora campi sconosciuti e URL forniti dal
manifest, costruendo i percorsi da una lista chiusa e case-sensitive di 22 ID. I
report individuali e i JSON grezzi non vengono richiesti ne esposti dalla pagina.
Se il servizio non e disponibile o pubblica un manifest parziale, le card mancanti
mostrano un unico SVG neutro. Il repository e l'immagine Docker Web non contengono
PNG storici, inclusi quelli demografici.

La pagina mostra ultimo tentativo, data dell'ultima pubblicazione e numero di
sessioni aggregate dichiarato dal manifest validato. Il pulsante «Aggiorna grafici»
permette un retry esplicito; il controllo automatico avviene ogni 300 secondi per
impostazione predefinita soltanto mentre la pagina e visibile. Un `404` viene
descritto come attesa del campione minimo o della finestra di pubblicazione,
mentre indisponibilita di rete e manifest non valido hanno messaggi distinti.

## Verifica e CI

`npm run verify` esegue il controllo sintattico di tutti gli script e l'intera suite
Node. Eseguire poi `npm run build` e `npm run typecheck`; la build verifica anche
gli hash CSP dell'export. La CI usa Node 24 e costruisce l'immagine Docker.
I test includono percorsi Linux case-sensitive, CSP, contratti
API, storage, cancellazione, flussi quiz, trace delle formule e dismissione PWA.

Per il collaudo browser installare Chromium con `npx playwright install chromium`,
servire l'immagine Nginx e usare `TEST_BASE_URL=http://127.0.0.1:18080 npm run test:browser`.
I test intercettano le API con risposte di prova; non inviano feedback reali.

Il punto 15 della roadmap (modalità docente) resta intenzionalmente escluso:
la Webpage non contiene viste, ruoli o flussi dedicati.

## Licenza

Nel materiale ricevuto non e presente una licenza.
