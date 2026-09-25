# TestLogica API

Backend autonomo di TestLogica per generare e verificare esercizi di logica. Il
servizio combina un dominio Python, un motore SWI-Prolog e un adattatore HTTP
FastAPI con contratto OpenAPI 3.1.

Questa directory contiene il componente API del repository unico TestLogica.
Il frontend `../Webpage_Logica` comunica con il servizio via HTTP. La build
dell'API usa questa directory come contesto e non incorpora Web o feedback.
Salvo un percorso esplicito, eseguire i comandi di questo README da `API_Logica/`.

## Funzionalità

- valutazione, tabelle di verità, modelli e contromodelli;
- equivalenza, soddisfacibilità, conseguenza logica e mutua esclusione;
- riscrittura verso NNF, CNF e DNF e percorsi di trasformazione verificabili;
- generazione di formule, distractor e domande riproducibili tramite `seed`;
- esercizi di equivalenza, valore di verità, conseguenza logica e traduzione;
- generazione batch e modalità parlata;
- trace versionate di costruzione e di trasformazione;
- errori HTTP uniformi, request ID, CORS e controlli di health/readiness.

## Architettura e responsabilità

```text
client HTTP
    |
server/                 FastAPI, Pydantic, OpenAPI, middleware ed errori
    |
testlogica/             dominio, AST, generatori e orchestrazione
    |
testlogica/prolog/      codec RPC, eccezioni e readiness lato Python
    |
prolog/                 regole e processo persistente SWI-Prolog
```

| Percorso | Contenuto |
| --- | --- |
| [`../.github/workflows/api.yml`](../.github/workflows/api.yml) | CI centralizzata per qualità Python, test SWI-Prolog e build Docker. |
| `server/` | Factory FastAPI, route, schemi Pydantic, esempi OpenAPI, CORS, request ID e traduzione degli errori. Non contiene algoritmi di generazione. |
| `testlogica/` | AST, validazione, metriche, configurazione, facciata del generatore e orchestrazione del dominio. Non dipende dal frontend. |
| `testlogica/questions/` | Builder distinti per equivalenza, valore di verità, conseguenza logica e traduzione. |
| `testlogica/prolog/` | Infrastruttura Python per comunicare in JSON con SWI-Prolog. Non contiene regole `.pl`. |
| `prolog/` | Valutazione, equivalenza, rewrite, template, distractor e server RPC in Prolog. `templates.pl` è l'entry point caricato dal bridge. |
| `prolog/tests/` | Suite `plunit` e relativo entry point. |
| `tests/` | Test unitari, d'integrazione e del contratto HTTP/OpenAPI. |
| `scripts/` | Preflight, deploy, smoke test e rollback del solo servizio API sul server Linux. |

Il flusso principale è `server -> testlogica -> PrologBridge -> SWI-Prolog`. Il
bridge usa un processo persistente e stream standard con messaggi JSON; il
dominio non importa FastAPI e i builder delle domande non implementano il
trasporto Prolog.

### Capacità pubbliche del motore

| Area | Operazioni principali |
| --- | --- |
| Logica | assegnazioni, `eval`, estrazione delle variabili e tabelle di verità |
| Equivalenza | equivalenza/non equivalenza, modelli, contromodelli, tautologie, contraddizioni, soddisfacibilità e implicazione logica |
| Rewrite | riscritture equivalenti, eliminazione delle implicazioni, NNF, CNF, DNF e percorsi di rewrite |
| Template | formule a profondità esatta, filtri sulle variabili e campionamento limitato |
| Distractor | mutazioni a uno o più passi, trace e filtro dei risultati non equivalenti |
| Generatore Python | metriche, payload formula, esercizi, traduzioni, conseguenze logiche e batch di domande |

L'elenco esatto delle funzioni esposte via HTTP, con schemi ed esempi aggiornati,
è generato dal codice ed è disponibile in Swagger UI e in `openapi.json`.

## Sintassi delle formule

Gli endpoint proposizionali accettano termini compatti in sintassi Prolog:

| Costrutto | Sintassi | Esempio |
| --- | --- | --- |
| atomo | identificatore che inizia con una lettera minuscola | `p`, `premessa_1` |
| negazione | `not(F)` | `not(p)` |
| congiunzione | `and(F1,F2)` | `and(p,q)` |
| disgiunzione | `or(F1,F2)` | `or(p,q)` |
| implicazione | `imp(F1,F2)` | `imp(p,q)` |
| bicondizionale | `iff(F1,F2)` | `iff(p,q)` |

Sono ammessi solo identificatori `[a-z][A-Za-z0-9_]*` e i cinque funtori
elencati; una stringa come `p),halt,(` viene rifiutata prima dell'esecuzione di
Prolog. Le valutazioni HTTP usano oggetti come
`{"name":"p","value":true}`; il formato Prolog equivalente è `p-true`.

Le domande di traduzione possono inoltre produrre termini didattici con
predicati e quantificatori, per esempio `forall(x,imp(A(x),B(x)))`. Questi
termini alimentano la trace di traduzione, ma non ampliano la grammatica
proposizionale eseguibile dal bridge.

## Trace: costruzione e trasformazione

I due contratti hanno scopi diversi e non sono intercambiabili:

- `construction` versione 1 descrive come un AST o un termine è composto dal
  basso verso l'alto (`ast_postorder` o `term_postorder`). È utile per mostrare
  la struttura di formule e traduzioni.
- `transformation` versione 1 descrive **come una formula è stata raggiunta da
  un'altra formula**. Ogni passaggio continuo contiene formula prima/dopo,
  sottoformula modificata, posizione e legge applicata. Le strategie sono
  `equivalence_rewrite`, che preserva il significato, e
  `distractor_mutation`, che non lo preserva.

Per una spiegazione del tipo “Come è stata raggiunta la formula” i consumer
devono usare `transformation`, non `construction`. Esempio abbreviato:

```json
{
  "version": 1,
  "strategy": "equivalence_rewrite",
  "source_formula_prolog": "imp(p,q)",
  "final_formula_prolog": "or(not(p),q)",
  "preserves_meaning": true,
  "steps": [
    {
      "index": 1,
      "kind": "rewrite",
      "rule": "implication_elimination",
      "before_prolog": "imp(p,q)",
      "after_prolog": "or(not(p),q)",
      "before_subformula_prolog": "imp(p,q)",
      "after_subformula_prolog": "or(not(p),q)",
      "location": "root"
    }
  ]
}
```

## Requisiti e avvio locale

- Python 3.11 o successivo;
- SWI-Prolog disponibile come `swipl`;
- ambiente Linux/macOS oppure un ambiente equivalente capace di eseguire i
  comandi indicati.

Dalla directory `API_Logica/` del clone:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
swipl --version
python -m uvicorn server.server:app --host 127.0.0.1 --port 5000
```

Il servizio risponde su `http://127.0.0.1:5000`. Una verifica minima:

```bash
curl --fail http://127.0.0.1:5000/health
curl --fail http://127.0.0.1:5000/ready
curl --fail http://127.0.0.1:5000/api/capabilities
```

## Configurazione

La configurazione è letta dall'ambiente del processo. Docker Compose carica
automaticamente un file `.env`; per l'esecuzione locale occorre invece
esportare le variabili nella shell. Copiare `.env.example` in `.env` solo se si
usa Compose.

| Variabile | Default | Significato |
| --- | --- | --- |
| `API_PORT` | `5000` | Porta pubblicata da Docker Compose; non cambia la porta interna `5000`. |
| `LOG_LEVEL` | `INFO` | Uno tra `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`. |
| `DEFAULT_TIMEOUT` | `10` | Timeout predefinito delle operazioni, da 1 a 120 secondi. |
| `MAX_BATCH_SIZE` | `50` | Numero massimo di domande in una singola richiesta batch, configurabile da 1 a 1000. È distinto dal limite di 100 domande di una sessione client. |
| `CORS_ORIGINS` | localhost e 127.0.0.1 sulla porta 12345 | Origini HTTP/HTTPS separate da virgola; wildcard non ammessa. |
| `SWI_PROLOG_PATH` | `swipl` | Eseguibile SWI-Prolog; utile per installazioni non standard. |
| `PROLOG_DIR` | directory `API_Logica/prolog/` | Percorso assoluto alternativo dei sorgenti Prolog. |

Esempio locale:

```bash
export LOG_LEVEL=DEBUG
export CORS_ORIGINS=http://localhost:12345
python -m uvicorn server.server:app --host 127.0.0.1 --port 5000
```

## Docker

```bash
cp .env.example .env
docker compose up --detach --build
docker compose ps
docker compose logs --follow testlogica-api
```

Il Compose di questo componente avvia esclusivamente l'API, pubblica
`${API_PORT:-5000}` e considera pronto il container solo quando `/ready`
conferma la disponibilità di SWI-Prolog. Il container usa un utente non root,
filesystem in sola lettura e capability ridotte. L'immagine installa il runtime
CLI `swi-prolog-nox`, senza dipendenze grafiche non necessarie sul server.

Per arrestarlo:

```bash
docker compose down
```

### Deployment sul server Linux

Il deployment effettivo usa [compose.server.yml](compose.server.yml), separato
dal Compose locale. L'API non pubblica porte host: e raggiungibile con l'alias
`api-logica` soltanto dai container collegati alla rete Docker esterna e
`internal` configurata in `BACKEND_NETWORK_NAME`. Il reverse proxy Web deve
usare `http://api-logica:5000` e collegarsi alla stessa rete.

Prerequisiti:

- Docker Engine con un plugin Compose che supporti `up --wait`;
- un utente di deployment autorizzato a usare Docker;
- checkout e configurazione non modificabili da altri utenti;
- una nuova `RELEASE_TAG` immutabile per ogni rilascio.

Preparazione iniziale:

```bash
cp .env.server.example .env.server
chmod 600 .env.server
# Modificare almeno RELEASE_TAG, RELEASE_REVISION e CORS_ORIGINS.
./scripts/preflight-server.sh .env.server
```

Il preflight rifiuta `latest`, domini di esempio, origini non HTTPS, permessi
insicuri e una rete omonima che non sia `internal`. Il deploy crea la rete
privata se ancora assente, costruisce e tagga l'immagine, attende l'healthcheck
e prova health, readiness, capabilities, OpenAPI e una generazione reale:

```bash
./scripts/deploy-server.sh .env.server
docker compose --env-file .env.server -f compose.server.yml ps
docker compose --env-file .env.server -f compose.server.yml logs --tail 200 testlogica-api
```

Un tag immagine gia presente non viene mai ricostruito o sovrascritto: anche
dopo un build interrotto occorre scegliere un nuovo `RELEASE_TAG`. Questo rende
il riferimento usato dal rollback immutabile sul server.

Se avvio o smoke falliscono, lo script ripristina la release precedente. Al
primo deploy, quando un rollback non esiste ancora, arresta invece il container
non validato. `/ready` esegue anche una query minima sulla sessione RPC
persistente: la sola presenza del binario e dei sorgenti SWI-Prolog non basta.

`DEPLOY_PULL_BASE_IMAGES=1` mantiene aggiornate le immagini base durante il
build server. Impostarlo a `0` soltanto per un collaudo isolato/offline che usa
una cache Docker gia verificata.

Il profilo server avvia per default due worker Uvicorn, ciascuno con il proprio
processo SWI-Prolog, e limita concorrenza e backlog (`API_WORKERS`,
`API_CONCURRENCY_LIMIT`, `API_BACKLOG`). I valori evitano una coda illimitata sul
bridge Prolog serializzato e vanno tarati con un test di carico sul server senza
superare CPU e memoria configurate.

Per una diagnosi temporanea dall'host impostare `API_ENABLE_LOOPBACK=1`: gli
script aggiungono [compose.server.loopback.yml](compose.server.loopback.yml),
che pubblica esclusivamente `${API_LOOPBACK_ADDRESS:-127.0.0.1}`. Non impostare
mai `0.0.0.0` sul server pubblico.

Gli script conservano solo i tag delle due release più recenti. Su un server
che sostituisce l'intera directory dei sorgenti a ogni rilascio, configurare
`DEPLOY_STATE_DIR` con un percorso persistente assoluto esterno, di proprieta
dell'utente di deployment e con permessi `0700`. Se la variabile e omessa viene
usata `.deploy/` nel checkout. Il preflight rifiuta link simbolici e directory
scrivibili dal gruppo o da altri utenti. Il rollback usa esclusivamente
immagini gia presenti sull'host e non esegue pull:

```bash
# Torna alla release precedente registrata.
./scripts/rollback-server.sh .env.server

# Oppure seleziona esplicitamente un tag locale.
./scripts/rollback-server.sh .env.server 2026.09.01-1
```

L'API non conserva stato o volumi. Il backup operativo comprende quindi il
file `.env.server` custodito fuori dal repository e i riferimenti ai tag
immagine; i dati persistenti appartengono agli altri servizi. Gli script non
eseguono `git push`, non eliminano immagini e non effettuano pruning.

## HTTP e OpenAPI

| Risorsa | URL |
| --- | --- |
| Informazioni servizio | `GET /` |
| Liveness, senza interrogare Prolog | `GET /health` |
| Readiness di SWI-Prolog | `GET /ready` |
| Capacità e limiti del configuratore | `GET /api/capabilities` |
| Swagger UI | `GET /docs` |
| ReDoc | `GET /redoc` |
| Specifica OpenAPI 3.1 | `GET /openapi.json` |

Le operazioni `POST` sono organizzate sotto:

- `/api/prolog-bridge/logic/`
- `/api/prolog-bridge/equivalence/`
- `/api/prolog-bridge/rewrite/`
- `/api/prolog-bridge/templates/`
- `/api/prolog-bridge/distractions/`
- `/api/generator/`

Swagger UI è la reference canonica per endpoint, vincoli e payload. Esempio:

```bash
curl --fail-with-body -X POST \
  http://127.0.0.1:5000/api/generator/build-exercise \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: example-1' \
  -d '{"expr":"imp(p,q)","wrong_answers_count":3,"seed":42}'
```

Le risposte operative dell'API logica hanno forma
`{"operation":"...","result":...}`. Gli errori applicativi hanno forma
`{"code":"...","message":"...","request_id":"..."}`; ogni risposta
espone inoltre `X-Request-ID`, conservando un identificatore client valido o
generandone uno nuovo.

## Test e qualità

### Limiti operativi verificati

Gli endpoint `/api/generator/*`, i relativi schemi HTTP e
`/api/capabilities` espongono i limiti protetti dai builder Python. I vincoli
che dipendono dalla somma di più campi sono descritti anche tramite estensioni
OpenAPI e restano applicati dalla validazione runtime:

- formule campionate: da 1 a 5 variabili;
- conseguenze logiche: da 2 a 5 variabili e da 2 a 8 opzioni complessive,
  sempre in numero pari;
- equivalenze generate automaticamente: da 1 a 21 distractor; per
  `build-exercise` con formula esplicita il massimo affidabile è 3. La formula
  esplicita deve contenere almeno 2 atomi, non più di 2 operatori binari e
  nessuna coppia di atomi uguali direttamente adiacenti. Le formule generate,
  le opzioni e i passaggi delle trasformazioni non contengono mai più di due
  negazioni consecutive;
- traduzioni: esattamente 3 distractor. I pool devono contenere abbastanza
  azioni distinte per i predicati quantificati e almeno due coppie
  nome/azione distinte per ogni subtype proposizionale che la modalità scelta
  può produrre;
- sessioni client: `/api/capabilities` espone un massimo di 100 domande. Quando
  supera `MAX_BATCH_SIZE`, il client deve suddividere la generazione in più
  richieste batch;
- singola richiesta batch: al massimo `MAX_BATCH_SIZE` elementi, 50 per default.
  Anche i payload annidati sono validati con il contratto dell'operazione
  corrispondente;
- `use_all=true` è ammesso soltanto quando la stima preventiva non supera
  50.000 formule. Per i quiz usare normalmente `use_all=false`;
- il timeout minimo accettato è un secondo; il valore operativo consigliato e
  usato dalla Webpage è 10 secondi.

Un `seed` assegnato al batch produce una finestra deterministica diversa per
ogni elemento. Un eventuale `seed` esplicito del singolo payload mantiene
invece la precedenza. I limiti evitano di presentare come supportate richieste
che lo stress test ha dimostrato combinatorie o non generabili.

Installare prima le dipendenze di sviluppo con `python -m pip install -e
".[dev]"`, quindi eseguire:

```bash
python -m pytest
python -m ruff check server testlogica tests
python -m mypy server testlogica
swipl -q -s prolog/tests/run_tests.pl
docker build --tag testlogica-api:local .
```

Per collaudare in modo riproducibile la generazione usata dalla Webpage:

```bash
python scripts/stress_generation.py
```

Il comando genera 100 esercizi per ognuna delle cinque tipologie, verifica
struttura, risposta corretta, semantica proposizionale e regole attese per
traduzioni e quantificatori. Per gli esercizi di equivalenza controlla inoltre
il limite delle negazioni su domanda, opzioni e ogni formula dei trace. Conta
anche i percorsi di emergenza usati durante la generazione e considera il test
fallito se ne rileva almeno uno. Richiede infine almeno il 95% di fingerprint
distinti senza contare come differenza il solo riordino delle risposte. Le
cinque tipologie sono equivalenza, valore di verità, conseguenza logica,
traduzione e negazione dei quantificatori: con i valori predefiniti vengono
quindi controllati 500 esercizi e altre 300 formule nella pipeline parlata,
anch'esse senza fallback. Usa `--count`,
`--minimum-unique-ratio` e `--seed` per variare quantità per tipologia, soglia
semantica (default `0.95`) e sequenza deterministica; restituisce un codice di
uscita diverso da zero quando un controllo non viene superato.

Lo stress test completo è un collaudo manuale e non è invocato separatamente
dal workflow CI. [Il workflow API](../.github/workflows/api.yml), nella radice
del repository, lavora da `API_Logica/` ed esegue su Python 3.11 pytest (compresi i test di
regressione versionati), Ruff, mypy, i test SWI-Prolog e la build Docker. I test
HTTP coprono anche OpenAPI, validazione preventiva delle formule, compatibilità
dei payload e request ID.

## Componenti e compatibilità

- API, Web e feedback condividono un repository; i rispettivi Dockerfile,
  test e runtime mantengono responsabilità separate.
- Il punto 15 della roadmap (modalità docente) resta intenzionalmente escluso:
  non sono presenti endpoint, dati o ruoli dedicati.
- `docker-compose.yml` avvia soltanto l'API. Per lo stack completo avviare poi
  il Compose di `../Webpage_Logica`, che include Web e feedback.
- Il componente Web configura l'upstream verso questa API e deve includere la
  propria origine in `CORS_ORIGINS` quando non usa un reverse proxy same-origin.
- I consumer devono verificare `version` in `/api/capabilities` e il contratto
  OpenAPI della release; distribuire versioni compatibili dei componenti.


## Licenza

Il repository non contiene ancora un file `LICENSE`.
Questo README non ne presume né ne inventa una.
