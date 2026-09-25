# TestLogica Feedback

Servizio autonomo che riceve i report finali del quiz, conserva il payload JSON
storico senza rinominare o normalizzare i dati inviati e pubblica, a intervalli
configurabili, 22 grafici aggregati consumati da `Webpage_Logica`.

Questo componente appartiene al repository unico TestLogica. Salvo un percorso
esplicito, eseguire i comandi di questo README da `feedback/`.
Il servizio non contiene account, ruoli o aggregazioni dedicate ai docenti.

## Prerequisito: dati eliminabili senza amministratore

Il clone mantiene i tre componenti nella stessa radice:

```text
<radice-repository>/
├── API_Logica/
├── Webpage_Logica/
└── feedback/
```

Lo storage e un **bind mount** della directory `feedback/data`, non un volume Docker
anonimo. I processi girano con lo stesso UID/GID dell'utente host; database, backup,
heartbeat e grafici possono quindi essere copiati, spostati o cancellati senza
`sudo`. Preparare i percorsi prima dell'avvio, come utente normale, partendo
dalla radice del repository:

```bash
cd feedback
./scripts/prepare-data.sh --write-env
```

Se lo stack viene avviato dal componente Web, riportare gli stessi valori di
`FEEDBACK_UID` e `FEEDBACK_GID` anche in `Webpage_Logica/.env`. Docker ha
`create_host_path: false`: se `feedback/data` manca, l'avvio fallisce invece di
crearla come `root`.

Su host SELinux (per esempio Fedora), lo stesso script controlla anche il bind
mount e applica ricorsivamente il tipo `container_file_t` senza `sudo`. Questo
preflight e necessario anche se `docker compose config` mostra l'opzione `z`:
alcune combinazioni Compose/Engine non propagano il relabel dei bind dichiarati
con sintassi estesa. `./scripts/prepare-data.sh --check` verifica UID/GID,
proprietario di tutti gli elementi, permessi, accesso e contesto senza modificare
nulla. La preparazione imposta `0700` sulle directory private.

Lo script usa `FEEDBACK_DATA_DIR` dall'ambiente o da `.env`, risolvendo i percorsi
relativi rispetto alla directory `feedback/`, come Compose. Percorsi che attraversano
symlink e destinazioni troppo ampie vengono rifiutati prima di creare directory o
applicare contesti. Alla prima preparazione viene creato un marker privato: una
directory esistente senza marker viene accettata solo se contiene esclusivamente
`.gitkeep`, `receipts`, `charts` e `backups`.

Per eliminare tutti i dati, arrestare lo stesso progetto Compose usato all'avvio:
per lo stack integrato eseguire `cd ../Webpage_Logica && docker compose down`,
mentre per lo standalone eseguire `docker compose down` da `feedback`. Rimuovere
quindi con il normale utente le sottodirectory `data/receipts` e `data/charts` (da
file manager o shell). Il successivo avvio le ricrea con permessi privati. Questa
operazione e irreversibile; creare prima un backup se necessario.

## Architettura

Il runtime contiene due processi distinti che condividono solo `/app/data`:

- `feedback`: FastAPI riceve i POST e serve manifest/PNG; non genera grafici;
- `feedback-worker`: applica retention e pubblicazione periodica, con lock di
  istanza e heartbeat usato dalla readiness HTTP.

Nel Compose integrato di `Webpage_Logica` entrambi sono sulla rete Docker
`feedback-internal`, dichiarata `internal: true`, e non pubblicano la porta `5555`.
Soltanto Nginx Web li raggiunge tramite DNS `http://feedback:5555`. Il Compose di
questo componente pubblica opzionalmente `5555` sul solo loopback `127.0.0.1` per
sviluppo locale; la rete del servizio resta privata.

La ricezione e il rendering sono disaccoppiati: un POST valido viene sincronizzato
nel database e riceve `201` senza attendere Matplotlib. Il worker elabora il nuovo
dataset soltanto dopo `FEEDBACK_PUBLISH_INTERVAL_SECONDS`; la retention ha un ciclo
separato e piu frequente.

## Storage, quote e migrazione

Le ricevute sono memorizzate in `data/receipts/feedback.sqlite3` con WAL,
`synchronous=FULL`, transazioni concorrenti e hash SHA-256 per ogni payload. Il JSON
logico salvato resta deep-equal al body ricevuto. `Idempotency-Key`, quando presente,
deve essere un UUIDv4 canonico: un retry con lo stesso body non crea duplicati; la
stessa chiave con un body diverso restituisce `409`.

Le quote `FEEDBACK_MAX_RECEIPTS` e `FEEDBACK_MAX_STORAGE_BYTES` limitano
rispettivamente il numero di report e sia i byte JSON logici sia l'occupazione
fisica prudenziale del database. Una riserva minima di filesystem evita di arrivare
a disco completamente pieno; dopo la retention il worker esegue checkpoint e
compattazione. A quota esaurita il POST restituisce `507` senza inserimenti parziali.
Il limite Nginx del Web protegge le
raffiche, ma quote e rate limit non sostituiscono autenticazione o protezioni
anti-Sybil in una distribuzione pubblica.

I vecchi file per-ricevuta non sono importati automaticamente. Eseguire prima una
simulazione e poi la migrazione esplicita, mantenendo la sorgente fuori da Git:

```bash
python -m feedback_service.migrate_legacy /percorso/dump --dry-run
python -m feedback_service.migrate_legacy /percorso/dump
```

La migrazione valida il contratto, conserva l'orario del file, assegna UUID
deterministici ai nomi legacy e non modifica la sorgente.

## Pubblicazione e metodologia

Uno snapshot viene pubblicato solo con almeno
`FEEDBACK_MIN_AGGREGATE_SESSIONS` report. Etichette libere vengono mappate in un
insieme limitato di categorie **solo durante l'analisi**; il dato grezzo non cambia.
In particolare, istituto e indirizzo sono ricondotti alle opzioni chiuse del Web e
gli eventuali valori sconosciuti confluiscono in `altro`. Tempi non finiti, negativi
o superiori a 24 ore vengono ignorati nella vista analitica, senza riscrivere il
report conservato. Questi limiti impediscono che un singolo valore anomalo blocchi
la pubblicazione periodica o diventi un'etichetta nei PNG.
Le coorti sotto soglia producono segnaposto neutri. I grafici di accuratezza mostrano
anche intervalli di confidenza Wilson al 95% e non espongono righe o timestamp della
singola sessione.

Ogni pubblicazione viene costruita in staging e resa corrente atomicamente. Manifest
e asset sono allow-listed, versionati e verificati tramite SHA-256. Per normali
aggiunte si conservano poche generazioni, cosi il lazy-loading Web resta stabile; una
retention o riduzione del dataset invalida subito tutte le generazioni. Il worker
rigenera automaticamente uno snapshot corrente mancante o corrotto.

La soglia `k` non fornisce differential privacy e non impedisce, da sola, invii
sintetici, inferenza per differenza o data poisoning. L'assetto raccomandato e quello
privato tra i due servizi; per un'esposizione Internet diretta servono
autenticazione, quota operativa e una policy statistica piu forte.

## Contratto HTTP

- `POST /api/revisione`: salva il report e risponde `201`; non renderizza;
- `GET /api/feedback/charts/manifest`: manifest dello snapshot corrente o `404`;
- `GET /api/feedback/charts/{generation_id}/{category}/{filename}`: PNG allow-listed;
- `GET /health`: liveness del processo HTTP;
- `GET /ready`: database, snapshot e heartbeat worker;
- `GET /metrics`: metriche Prometheus private e prive di payload/etichette utente;
- `/docs`, `/redoc`, `/openapi.json`: contratto OpenAPI.

`/metrics` e la porta diretta non devono essere pubblicati dalla Webpage. I log HTTP
strutturati contengono metodo, path, stato, durata e request ID, mai body o dati
demografici.

## Configurazione

| Variabile | Default | Significato |
| --- | ---: | --- |
| `FEEDBACK_UID` / `FEEDBACK_GID` | `1000` | Proprietario numerico dei file nel bind mount. |
| `FEEDBACK_DATA_DIR` | `./data` | Directory host del bind mount standalone. |
| `FEEDBACK_PORT` | `5555` | Porta di sviluppo pubblicata esclusivamente su `127.0.0.1` dal Compose standalone. |
| `FEEDBACK_STORAGE_DIR` | Compose: `/app/data/receipts`; Python locale: `./data/receipts` | Database privato delle ricevute. |
| `FEEDBACK_CHARTS_DIR` | Compose: `/app/data/charts`; Python locale: `./data/charts` | Snapshot, lock e heartbeat. |
| `FEEDBACK_RETENTION_DAYS` | `365` | Durata massima dei report. |
| `FEEDBACK_MAX_BODY_BYTES` | `2097152` | Limite del body HTTP. |
| `FEEDBACK_MAX_RECEIPTS` | `100000` | Quota logica di ricevute. |
| `FEEDBACK_MAX_STORAGE_BYTES` | `1073741824` | Quota logica e fisica prudenziale del database. |
| `FEEDBACK_MIN_FREE_BYTES` | `67108864` | Spazio libero da preservare sul filesystem. |
| `FEEDBACK_MIN_AGGREGATE_SESSIONS` | `10` | Soglia globale e per coorte. |
| `FEEDBACK_SNAPSHOTS_TO_KEEP` | `3` | Generazioni mantenute per normali aggiunte. |
| `FEEDBACK_PUBLISH_INTERVAL_SECONDS` | `86400` | Cadenza di pubblicazione. |
| `FEEDBACK_RETENTION_INTERVAL_SECONDS` | `3600` | Cadenza della retention indipendente. |
| `FEEDBACK_WORKER_HEARTBEAT_SECONDS` | `15` | Frequenza heartbeat worker. |
| `FEEDBACK_WORKER_STALE_SECONDS` | `60` | Eta massima dell'heartbeat per `/ready`. |
| `FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS` | `900` | Durata massima di un tick prima del riavvio del worker. |
| `FEEDBACK_STOP_GRACE_SECONDS` | `960` | Tempo di arresto Docker, maggiore di timeout job + heartbeat per non troncare un'elaborazione valida. |

`FEEDBACK_WORKER_MODE=external` e fissato nei Compose. La modalita `embedded` esiste
solo per sviluppo e test in-process.

## Operazioni senza root

Con un ambiente Python locale:

```bash
python -m feedback_service.admin status
python -m feedback_service.admin check
python -m feedback_service.admin purge
python -m feedback_service.admin backup data/backups/feedback-2026-08-22.sqlite3
python -m feedback_service.admin restore data/backups/feedback-2026-08-22.sqlite3
```

`status` e intenzionalmente osservativo e non modifica il database. Se trova uno
schema legacy prima del primo avvio, eseguire una volta `admin check` oppure avviare
il servizio: l'inizializzazione applica automaticamente la migrazione supportata.

Con i container gia avviati, `status`, `check`, `purge` e `backup` possono essere
eseguiti con `docker compose exec feedback python -m feedback_service.admin ...`.
Il backup usa l'API SQLite, include i commit presenti nel WAL, viene sincronizzato
su disco con permesso `0600` e non sovrascrive mai un file esistente. I grafici sono
derivati e possono essere rigenerati dal database.

Per lo stack server integrato usare lo script dedicato dalla directory `feedback/`:

```bash
./scripts/server-backup.sh --env-file ../Webpage_Logica/.env.server
```

Lo script esegue l'API SQLite dentro il container non-root, verifica proprietario
e modo del file host, controlla che resti la riserva `FEEDBACK_MIN_FREE_BYTES` e
scrive un file `.sha256` privato. Il risultato resta nella sottodirectory
`backups` del bind persistente, quindi sopravvive a deploy e rollback delle release ma
non a un guasto del disco host: copiare periodicamente backup e checksum su uno
storage esterno cifrato, con accesso limitato e retention definita dal gestore.
Monitorare spazio e inode; quando si applica la retention, eliminare soltanto
coppie `.sqlite3`/`.sha256` gia copiate e verificate fuori server. Il deploy non
cancella automaticamente backup o immagini senza una policy esplicita.
Non copiare direttamente `feedback.sqlite3` mentre il servizio e attivo, perche i
commit piu recenti possono trovarsi nel WAL.

Il restore rifiuta un database attivo. Verificare prima il checksum, arrestare lo
stesso Compose server usato all'avvio e spostare l'intera directory `receipts`
in una posizione di quarantena sul medesimo filesystem. Creare poi una nuova
`receipts` privata, senza cancellare la quarantena finche il collaudo non e
concluso. Per lo stack server integrato i comandi devono specificare sempre il
file e il Compose di produzione:

```bash
cd /srv/testlogica/shared/feedback-data/backups
sha256sum -c feedback-2026-08-22.sqlite3.sha256

cd /srv/testlogica/releases/RELEASE_ID/Webpage_Logica
docker compose --env-file .env.server -f compose.server.yml stop \
  webpage-logica feedback feedback-worker

# Come utente di deployment, senza sudo:
mv /srv/testlogica/shared/feedback-data/receipts \
  /srv/testlogica/shared/feedback-data/receipts.quarantine-before-restore
install -d -m 0700 /srv/testlogica/shared/feedback-data/receipts
docker compose --env-file .env.server -f compose.server.yml run --rm --no-deps feedback \
  python -m feedback_service.admin restore /app/data/backups/feedback-2026-08-22.sqlite3
docker compose --env-file .env.server -f compose.server.yml run --rm --no-deps feedback \
  python -m feedback_service.admin check
docker compose --env-file .env.server -f compose.server.yml up \
  --detach --no-build --wait
```

Il backup viene ricontrollato, ripulito secondo la retention corrente e installato
senza sovrascrivere file.

Il rollback di `Webpage_Logica/ops/server-rollback.sh` cambia soltanto le immagini
applicative e crea prima un nuovo backup. Non seleziona e non ripristina mai un
database automaticamente. Un restore e una decisione separata, esplicita e con
stack arrestato.

## Avvio

Avvio integrato raccomandato, dalla radice del repository:

```bash
cd feedback
./scripts/prepare-data.sh
cd ../Webpage_Logica
cp .env.example .env
docker compose up --build
```

Sul server effettivo non usare il Compose standalone di questo componente. Copiare
`Webpage_Logica/.env.server.example` in `.env.server`, valorizzare UID/GID e un
tag release univoco, le due revisioni sorgente e i percorsi assoluti sotto una
directory persistente posseduta dall'utente di deployment. Distribuire prima
`API_Logica`, quindi eseguire dalla directory `feedback/`:

```bash
cd ../Webpage_Logica
./ops/server-preflight.sh --prepare-data --create-network --require-api
./ops/server-deploy.sh
```

`compose.server.yml` non pubblica la porta feedback, usa root filesystem read-only,
capability azzerate e limiti di processi, memoria, CPU e log. Il solo Web e legato
a `127.0.0.1`; TLS, HSTS e rate limit per client appartengono all'edge descritto
nel README Web. Lo stato di rollback resta in `DEPLOY_STATE_DIR`, fuori dalle
directory release, mentre database e backup restano sempre nel bind persistente.

Avvio standalone di sviluppo dalla radice del repository (porta disponibile soltanto su loopback):

```bash
cd feedback
cp .env.example .env
./scripts/prepare-data.sh --write-env
docker compose up --build
```

## Sviluppo, test e struttura

Eseguire da `feedback/`. [Il workflow feedback](../.github/workflows/feedback.yml)
nella radice del repository usa la stessa directory di lavoro.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check feedback_service tests
.venv/bin/mypy feedback_service
docker compose config --quiet
docker build .
```

| Percorso | Responsabilita |
| --- | --- |
| `feedback_service/app.py` | HTTP, OpenAPI, request ID e metriche. |
| `feedback_service/storage.py` | SQLite, idempotenza, retention, quote e backup. |
| `feedback_service/worker.py` | Scheduler esterno, lock singola istanza e heartbeat. |
| `feedback_service/coordinator.py` | Coordinamento atomico tra ricevute e snapshot. |
| `feedback_service/data_processor.py` | Derivazione di metriche e categorie limitate. |
| `feedback_service/chart_generator.py` | Generazione Agg dei 22 grafici aggregati. |
| `feedback_service/snapshots.py` | Staging, manifest, hash, versioni e self-healing. |
| `feedback_service/migrate_legacy.py` | Import esplicito dei JSON legacy. |
| `feedback_service/admin.py` | Check, statistiche, purge e backup non-root. |
| `scripts/prepare-data.sh` | Preparazione sicura del bind mount e UID/GID. |
| `scripts/server-backup.sh` | Backup server consistente con verifica host e checksum SHA-256. |
| `tests/` | Regressioni storage, HTTP, worker, privacy e grafici. |
| [`../.github/workflows/feedback.yml`](../.github/workflows/feedback.yml) | CI centralizzata del servizio. |
| [`../.github/dependabot.yml`](../.github/dependabot.yml) | Aggiornamenti dipendenze dei componenti del repository. |

Gli script Python storici della radice sono stati rimossi: package, immagine e CI
usano soltanto `feedback_service`. I dump e i grafici generati non vanno
committati. Le precedenti directory Git dei componenti sono state rimosse;
il versionamento corrente appartiene alla radice del repository unico.
