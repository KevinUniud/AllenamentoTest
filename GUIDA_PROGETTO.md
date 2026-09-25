# Guida operativa e mappa del codice di TestLogica

Questa guida descrive come orientarsi nel workspace, quali file modificare per
ogni responsabilità, come avviare l'intero progetto e come usare il servizio
feedback.

Il workspace contiene tre componenti autonomi:

| Directory | Responsabilità |
| --- | --- |
| API_Logica/ | API FastAPI, dominio Python, generatore e motore SWI-Prolog. |
| Webpage_Logica/ | Next.js/React con export statico, contenuti HTML e proxy Nginx. |
| feedback/ | Ricezione dei report, database SQLite, elaborazione periodica e grafici. |

I nomi dei percorsi sono case-sensitive su Linux. Usare esattamente
API_Logica, Webpage_Logica, Errori_comuni e Immagini.

## Come comunicano i componenti

Il browser apre il Web su http://localhost:12345. Nginx serve i file statici e
inoltra le richieste:

~~~text
browser
  |
  v
Webpage_Logica / Nginx
  |-- /api/revisione ----------------------> feedback:5555
  |-- /api/feedback/charts/... ------------> feedback:5555
  |-- le altre /api/... e /health ---------> API_Logica:5000
                                                   |
                                                   v
                                      Python -> bridge -> SWI-Prolog
~~~

I confini da mantenere sono:

- API_Logica non deve contenere, ricevere o conservare dati feedback.
- Webpage_Logica comunica con API e feedback esclusivamente via HTTP.
- feedback è l'unico componente che riceve i report, li conserva e genera i
  grafici aggregati.
- Il payload storico costruito dal Web deve arrivare a feedback senza modifiche.
- Nell'interfaccia si mostrano i simboli logici; l'API usa la sintassi funzionale
  not(...), and(...), or(...), imp(...) e iff(...).
- La modalità docente indicata come punto 15 della roadmap resta esclusa.

## Da quale file partire

| Modifica desiderata | File principali | Verifica minima |
| --- | --- | --- |
| Aggiungere o cambiare un endpoint API | API_Logica/server/routes.py, schemas.py e openapi_docs.py | tests/test_api_contract.py |
| Cambiare la generazione delle formule | API_Logica/testlogica/generator.py, orchestrator.py o questions/ | test_question_modules.py e test_truth_value_regressions.py |
| Cambiare semantica o riscritture logiche | API_Logica/prolog/*.pl e relativo adattatore Python | test Prolog e pytest |
| Cambiare una pagina | Home/impostazioni in src/components; altre pagine nel relativo HTML, controller scripts/ e CSS | npm run verify, build, typecheck e browser |
| Cambiare il quiz | Webpage_Logica/scripts/quiz-*.js | test quiz e test del payload |
| Cambiare il payload inviato | Webpage_Logica/scripts/quiz-report.js e quiz-payloads.js | quiz-report.test.js e quiz-payloads.test.js |
| Cambiare ricezione o validazione feedback | feedback/feedback_service/app.py e schemas.py | test_feedback_service.py |
| Cambiare conservazione feedback | feedback/feedback_service/storage.py | test_sqlite_storage.py e test_storage_maintenance.py |
| Cambiare i grafici | feedback/feedback_service/data_processor.py, chart_generator.py e snapshots.py | test_external_worker.py e test_snapshot_cleanup.py |
| Cambiare la galleria dei grafici | Webpage_Logica/scripts/feedback-charts.js e grafici/grafici.html | feedback-charts.test.js |
| Cambiare Docker o deploy | I Compose, Dockerfile e script ops del singolo repository | compose config, build e smoke test |

## Avvio completo in locale

### Prerequisiti

- Docker Engine e Docker Compose v2, utilizzabili dall'utente corrente.
- Le tre directory sorelle presenti con i nomi indicati sopra.
- Le porte 5000 e 12345 libere.

Non servono permessi amministrativi. Non usare sudo per preparare feedback o
avviare i container, così i dati restano di proprietà dell'utente e possono
essere cancellati normalmente.

### Prima configurazione

Dalla radice di questo workspace:

~~~bash
cp API_Logica/.env.example API_Logica/.env
cp Webpage_Logica/.env.example Webpage_Logica/.env
cp feedback/.env.example feedback/.env
cd feedback
./scripts/prepare-data.sh --write-env
cd ..
~~~

Non sovrascrivere un file .env già configurato. Lo script aggiorna
feedback/.env; riportare anche in Webpage_Logica/.env i valori numerici restituiti
da id -u e id -g nelle variabili FEEDBACK_UID e FEEDBACK_GID. Verificare inoltre:

- FEEDBACK_DATA_DIR=../feedback/data
- API_UPSTREAM=http://host.docker.internal:5000

Il mapping host.docker.internal:host-gateway è già previsto dal Compose Web per
Docker Linux.

### Avvio

Eseguire dalla radice, nell'ordine:

~~~bash
docker compose --project-directory API_Logica --file API_Logica/docker-compose.yml up --detach --build --wait
docker compose --project-directory Webpage_Logica --file Webpage_Logica/docker-compose.yml up --detach --build --wait
~~~

Gli stessi due comandi, senza altro testo, sono disponibili in fast_test.md.

Aprire:

- sito: http://localhost:12345
- documentazione Swagger dell'API: http://localhost:5000/docs
- specifica OpenAPI: http://localhost:5000/openapi.json

### Controlli rapidi

~~~bash
docker compose --project-directory API_Logica --file API_Logica/docker-compose.yml ps
docker compose --project-directory Webpage_Logica --file Webpage_Logica/docker-compose.yml ps
curl --fail http://localhost:5000/health
curl --fail http://localhost:5000/ready
curl --fail http://localhost:5000/api/capabilities
curl --fail http://localhost:12345/web-health
curl --fail http://localhost:12345/health
curl --fail http://localhost:12345/api/capabilities
~~~

Per seguire i log:

~~~bash
docker compose --project-directory API_Logica --file API_Logica/docker-compose.yml logs --follow
docker compose --project-directory Webpage_Logica --file Webpage_Logica/docker-compose.yml logs --follow webpage-logica feedback feedback-worker
~~~

### Arresto

Fermare prima lo stack Web e poi l'API:

~~~bash
docker compose --project-directory Webpage_Logica --file Webpage_Logica/docker-compose.yml down
docker compose --project-directory API_Logica --file API_Logica/docker-compose.yml down
~~~

Non aggiungere -v se si vogliono conservare i dati. Lo storage feedback è
comunque un bind mount in feedback/data, non un volume anonimo.

## Test senza avviare tutto

### API

~~~bash
cd API_Logica
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy server testlogica
swipl -q -s prolog/tests/run_tests.pl
python scripts/stress_generation.py
~~~

L'ultimo comando è il collaudo esteso manuale: genera per impostazione
predefinita 100 esercizi per ciascuna delle cinque tipologie Web (500 in
totale), ne verifica contratto, semantica proposizionale e regole attese per
traduzioni e quantificatori, e richiede almeno il 95% di fingerprint distinti
per tipologia. La soglia non considera diverso un esercizio per il solo
riordino delle opzioni. Per cambiare quantità, soglia o sequenza riproducibile
usare rispettivamente `--count`,
`--minimum-unique-ratio` e `--seed`. Lo script non è eseguito separatamente
dalla CI; i test di regressione elencati nell'inventario rientrano invece nella
normale suite pytest.

Il profilo operativo verificato usa al massimo 5 variabili, 8 opzioni totali
nelle conseguenze logiche, fino a 21 distractor nelle equivalenze generate
automaticamente e sempre 3 distractor nelle traduzioni. Per un'equivalenza da
formula esplicita il limite è invece 3 distractor e la formula deve rispettare
il profilo breve documentato dall'API. Ove applicabile, la Webpage usa il
profilo più conservativo da 3 a 5 variabili e 3 distractor. La generazione
`use_all` viene rifiutata prima di interrogare SWI-Prolog quando la stima supera
50.000 formule; i batch hanno seed distinti per elemento e validano anche i
payload annidati. Nelle traduzioni, le azioni dei predicati quantificati devono
essere distinte; la variante proposizionale richiede almeno due descrizioni
nome/azione diverse e abilita le catene soltanto quando ne sono disponibili
almeno tre.

Per avviare soltanto l'API fuori da Docker:

~~~bash
python -m uvicorn server.server:app --host 127.0.0.1 --port 5000
~~~

### Web

Usare Node 24 e le versioni bloccate dal lockfile:

~~~bash
cd Webpage_Logica
npm ci
npm run verify
npm run build
npm run typecheck
docker compose config
docker build .
~~~

### Feedback

~~~bash
cd feedback
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
MPLCONFIGDIR=/tmp/testlogica-matplotlib pytest
ruff check .
mypy feedback_service
docker compose config
docker build .
~~~

## Inventario dei file

Per la nuova struttura `src/`, la migrazione progressiva dei controller, la
build statica e il confezionamento senza Git consultare
[NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md](NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md).
Gli HTML elencati sotto restano sorgenti per l'adattatore; la home visibile e
in `src/components/HomeContent.tsx` e le impostazioni in `SiteSettings.tsx`.

L'inventario seguente copre i file sorgente, configurazione, test, documentazione
e operazioni che si modificano manualmente. Non elenca internamente .git,
ambienti virtuali, cache, egg-info, database/WAL e snapshot generati. I
file .env reali sono citati per ruolo, senza mostrarne i valori.

### Radice del workspace

| File | Come usarlo |
| --- | --- |
| GUIDA_PROGETTO.md | Questa guida operativa trasversale. |
| README.md | Definisce architettura, confini dei tre repository e deployment. È la fonte canonica del workspace. |
| fast_test.md | Contiene unicamente i due comandi Compose di avvio locale. |
| .gitignore | Esclude artefatti locali e sensibili del workspace. |
| FEATURE_BACKLOG.md | Backlog storico, non contratto operativo corrente. |
| FEATURE_IMPLEMENTATION_ROADMAP.md | Stato storico delle funzionalità; il punto 15 resta escluso. |
| FORMULA_CONSTRUCTION_PLAN.md | Piano storico sulle trace di formula. |
| MIGRATION.md | Note storiche della migrazione a Linux. |

### API_Logica: configurazione e avvio

| File | Come usarlo |
| --- | --- |
| API_Logica/README.md | Documentazione canonica di API, sintassi, endpoint, test e deploy. |
| API_Logica/pyproject.toml | Metadati, dipendenze Python, gruppi dev e configurazione di pytest, Ruff e mypy. |
| API_Logica/requirements.txt | Dipendenze runtime per installazioni che non usano il package editable; mantenerlo coerente con pyproject.toml. |
| API_Logica/Dockerfile | Costruisce l'immagine non-root con Python e SWI-Prolog. |
| API_Logica/docker-compose.yml | Avvio locale dell'unico servizio API, pubblicato normalmente sulla porta 5000. |
| API_Logica/compose.server.yml | Stack di produzione su rete backend privata, senza porta host. |
| API_Logica/compose.server.loopback.yml | Override controllato per esporre l'API solo su loopback durante verifiche server. |
| API_Logica/.env | Configurazione locale reale e ignorata; non committare né documentarne i segreti. |
| API_Logica/.env.example | Modello di configurazione per il Compose locale. |
| API_Logica/.env.server.example | Modello di produzione, da copiare in .env.server fuori da Git. |
| API_Logica/.dockerignore | Esclude dal contesto Docker cache, dati locali e file non necessari. |
| API_Logica/.gitignore | Esclude ambiente, cache, configurazioni reali e artefatti. |
| API_Logica/.gitattributes | Normalizza terminatori e bit eseguibili per Linux. |
| API_Logica/.github/workflows/ci.yml | CI di pytest, Ruff, mypy, test Prolog e build Docker. |

### API_Logica: livello HTTP

| File | Come usarlo |
| --- | --- |
| API_Logica/server/__init__.py | Dichiara il package HTTP; non contiene logica applicativa. |
| API_Logica/server/server.py | Entry point ASGI server.server:app usato da Uvicorn. |
| API_Logica/server/app_factory.py | Costruisce FastAPI, middleware, CORS, error handler e metadati OpenAPI. |
| API_Logica/server/routes.py | Definisce health, ready, capabilities e gli endpoint POST; delega al dominio. |
| API_Logica/server/schemas.py | Modelli Pydantic dei request, response, formule e trace. Modificarlo solo preservando i contratti pubblici desiderati. |
| API_Logica/server/openapi_docs.py | Tag, descrizioni, esempi e risposte di errore della documentazione OpenAPI. |
| API_Logica/server/errors.py | Traduce gli errori nel formato uniforme code, message e request_id. |
| API_Logica/server/middleware.py | Gestisce request ID, durata e logging strutturato delle richieste. |
| API_Logica/server/request_id.py | Valida un request ID ricevuto o genera un UUID sicuro. |

### API_Logica: dominio Python

| File | Come usarlo |
| --- | --- |
| API_Logica/testlogica/__init__.py | Espone i tipi pubblici principali del package, in particolare l'AST. |
| API_Logica/testlogica/ast_logic.py | AST immutabile delle formule e conversioni strutturali. |
| API_Logica/testlogica/config.py | Legge e valida timeout, batch, CORS, log, eseguibile SWI e percorsi Prolog. |
| API_Logica/testlogica/constants.py | Limiti e costanti condivise dal generatore e dal bridge. |
| API_Logica/testlogica/metrics.py | Calcola profondità, dimensione, atomi e operatori delle formule. |
| API_Logica/testlogica/validation.py | Valida variabili, profondità, deadline, limiti e invarianti JSON. |
| API_Logica/testlogica/formula_construction.py | Produce la trace strutturale bottom-up; non descrive il passaggio A-verso-B. |
| API_Logica/testlogica/formula_transformation.py | Produce e valida il percorso da formula sorgente a formula finale con leggi e mutazioni. |
| API_Logica/testlogica/question_identity.py | Genera identificatori stabili e riproducibili per le domande batch. |
| API_Logica/testlogica/generator.py | Facciata pubblica del generatore e funzioni comuni di creazione delle formule. |
| API_Logica/testlogica/orchestrator.py | Coordina bridge, builder, distractor, deduplicazione, trace e generazione batch. |
| API_Logica/testlogica/prolog_bridge.py | Mantiene il processo SWI-Prolog JSON-lines, sincronizza gli accessi e valida input/output. |

### API_Logica: builder delle domande

| File | Come usarlo |
| --- | --- |
| API_Logica/testlogica/questions/__init__.py | Esporta i builder distinti per tipologia. |
| API_Logica/testlogica/questions/equivalence.py | Costruisce domande di equivalenza e relative risposte/distractor. |
| API_Logica/testlogica/questions/truth_value.py | Costruisce domande sul valore di verità, rispettando atomi e assegnazioni richiesti. |
| API_Logica/testlogica/questions/logical_consequence.py | Costruisce esercizi di conseguenza logica con premesse e conclusione. |
| API_Logica/testlogica/questions/translation.py | Costruisce esercizi di traduzione e trace didattiche anche con quantificatori. |

### API_Logica: infrastruttura Python per Prolog

| File | Come usarlo |
| --- | --- |
| API_Logica/testlogica/prolog/__init__.py | Esporta codec, errori e controlli del sottosistema Prolog. |
| API_Logica/testlogica/prolog/codec.py | Codifica richieste e decodifica risposte del protocollo JSON-lines. |
| API_Logica/testlogica/prolog/exceptions.py | Eccezioni specifiche per protocollo, timeout, processo e risultati non validi. |
| API_Logica/testlogica/prolog/health.py | Esegue il controllo di disponibilità usato dalla readiness. |

### API_Logica: regole SWI-Prolog

| File | Come usarlo |
| --- | --- |
| API_Logica/prolog/logic.pl | Valutazione, variabili, assegnazioni e tavole di verità. |
| API_Logica/prolog/equivalence.pl | Equivalenza, modelli, contromodelli, soddisfacibilità e conseguenza. |
| API_Logica/prolog/rewrite.pl | Regole di riscrittura e trasformazioni NNF, CNF e DNF. |
| API_Logica/prolog/templates.pl | Template e campionamento delle formule; è l'entry point logico caricato dal bridge. |
| API_Logica/prolog/distractions.pl | Facciata comune del sottosistema che genera i distractor. |
| API_Logica/prolog/distractions_generation.pl | Strategie di generazione dei candidati. |
| API_Logica/prolog/distractions_mutations.pl | Mutazioni controllate e relativa trace. |
| API_Logica/prolog/distractions_non_equivalent.pl | Filtra e certifica i candidati non equivalenti. |
| API_Logica/prolog/rpc_server.pl | Processo persistente che legge richieste JSON-lines e restituisce risposte JSON. |
| API_Logica/prolog/tests/distractions_tests.pl | Test plunit per generazione, mutazioni e casi limite dei distractor. |
| API_Logica/prolog/tests/run_tests.pl | Entry point che carica ed esegue l'intera suite SWI-Prolog. |

### API_Logica: operazioni server

| File | Come usarlo |
| --- | --- |
| API_Logica/scripts/preflight-server.sh | Verifica prerequisiti, rete privata, configurazione, revisioni, permessi e percorsi. |
| API_Logica/scripts/deploy-server.sh | Costruisce e attiva una release API immutabile, poi esegue gli smoke test. |
| API_Logica/scripts/smoke-server.sh | Verifica container, health, ready, capabilities e contratto esposto. |
| API_Logica/scripts/rollback-server.sh | Riattiva l'ultima immagine API verificata senza cancellare dati o sorgenti. |
| API_Logica/scripts/stress_generation.py | Collaudo manuale riproducibile: genera 100 esercizi per ognuna delle cinque tipologie Web (500 totali), valida risposte e semantica e impone almeno il 95% di fingerprint distinti per tipologia. |

### API_Logica: test Python

| File | Copertura |
| --- | --- |
| API_Logica/tests/test_api_contract.py | Endpoint FastAPI, codici, schemi, errori e OpenAPI. |
| API_Logica/tests/test_ast_logic.py | Costruzione, immutabilità e conversione dell'AST. |
| API_Logica/tests/test_config.py | Default, variabili ambiente, limiti e configurazioni non valide. |
| API_Logica/tests/test_formula_construction.py | Trace bottom-up della struttura delle formule. |
| API_Logica/tests/test_formula_transformation.py | Continuità e correttezza dei passaggi A-verso-B. |
| API_Logica/tests/test_generation_diversity.py | Protegge riproducibilità cache fredda/calda, timeout breve, diversità semantica e selezione dei distractor dipendente dal seed. |
| API_Logica/tests/test_generator_regressions.py | Regressioni strutturali del generatore, inclusa la generazione con quattro e cinque variabili. |
| API_Logica/tests/test_logical_consequence_errors.py | Impedisce che timeout, errori o risultati non booleani vengano etichettati come non-conseguenze. |
| API_Logica/tests/test_logical_consequence_stress.py | Verifica su 100 seed affidabilità, semantica, vincoli e diversità delle conseguenze logiche. |
| API_Logica/tests/test_metrics.py | Profondità, dimensione, conteggio di atomi e operatori. |
| API_Logica/tests/test_prolog_codec.py | Protocollo JSON-lines e rifiuto di dati malformati. |
| API_Logica/tests/test_prolog_health.py | Liveness del processo SWI e casi di errore. |
| API_Logica/tests/test_question_identity.py | Stabilità e unicità degli ID delle domande. |
| API_Logica/tests/test_question_modules.py | Contratti e casi principali dei builder modulari. |
| API_Logica/tests/test_multiple_questions_seed.py | Seed per elemento, determinismo, immutabilità dell'input e limite diretto dei batch. |
| API_Logica/tests/test_request_id.py | Validazione, propagazione e generazione dei request ID. |
| API_Logica/tests/test_request_schemas.py | Limiti operativi e validazione dei payload annidati per gli endpoint batch. |
| API_Logica/tests/test_server_deployment.py | Proprietà di sicurezza e coerenza dei file di deploy API. |
| API_Logica/tests/test_translation_question.py | Domande di traduzione e relative trace. |
| API_Logica/tests/test_truth_value_regressions.py | Regressioni del generatore, inclusa la disponibilità di formule con gli atomi richiesti. |
| API_Logica/tests/test_validation.py | Limiti, nomi, deadline e input ostili. |

### Webpage_Logica: configurazione e avvio

| File | Come usarlo |
| --- | --- |
| Webpage_Logica/README.md | Documentazione canonica di frontend, feedback integrato, test e deploy. |
| Webpage_Logica/package.json | Definisce gli script npm; npm run verify è il controllo completo del Web. |
| Webpage_Logica/Dockerfile | Costruisce il container Nginx che serve l'applicazione statica. |
| Webpage_Logica/docker-compose.yml | Avvia Web, feedback HTTP e feedback worker in locale. |
| Webpage_Logica/compose.server.yml | Stack Web/feedback di produzione, con reti private e bind mount persistente. |
| Webpage_Logica/.env | Configurazione locale reale e ignorata; contiene upstream, porte, UID/GID e soglie. |
| Webpage_Logica/.env.example | Modello per l'avvio locale. |
| Webpage_Logica/.env.server.example | Modello server con revisioni, rete, percorsi persistenti e URL pubblico. |
| Webpage_Logica/.dockerignore | Riduce il contesto di build ai file necessari. |
| Webpage_Logica/.gitignore | Esclude configurazioni reali, cache e artefatti locali. |
| Webpage_Logica/.gitattributes | Mantiene terminatori e permessi compatibili con Linux. |
| Webpage_Logica/.github/workflows/ci.yml | Esegue verifica JavaScript, test, controlli Compose e build. |
| Webpage_Logica/nginx/default.conf.template | Routing interno: statici, API logica, ricezione feedback e grafici. |
| Webpage_Logica/nginx/security-headers.conf | Header CSP e altre protezioni HTTP condivise. |
| Webpage_Logica/deploy/nginx-edge.example.conf | Esempio di reverse proxy TLS host con HSTS e rate limit. |
| Webpage_Logica/service-worker.js | Tombstone senza cache né fetch handler che disattiva le vecchie installazioni PWA. |

### Webpage_Logica: operazioni server e strumenti

| File | Come usarlo |
| --- | --- |
| Webpage_Logica/ops/server-common.sh | Funzioni condivise da preflight, deploy, smoke e rollback. |
| Webpage_Logica/ops/server-preflight.sh | Valida release, reti, percorsi, permessi, UID/GID, API e configurazione. |
| Webpage_Logica/ops/server-deploy.sh | Costruisce e attiva Web più feedback, con backup e rollback automatico in caso di errore. |
| Webpage_Logica/ops/server-smoke.sh | Collauda Web, proxy API, feedback e intestazioni della release. |
| Webpage_Logica/ops/server-rollback.sh | Torna alle immagini verificate precedenti dopo un backup SQLite. |
| Webpage_Logica/tools/check-js.mjs | Analizza tutti gli script JavaScript individuati dal progetto e ne controlla la sintassi. |

### Webpage_Logica: pagine

| File | Ruolo e punto di integrazione |
| --- | --- |
| Webpage_Logica/index.html | Home e configuratore della sessione; carica impostazioni, progressi e navigazione principale. |
| Webpage_Logica/privacy.html | Informativa e controlli separati per persistenza locale, feedback e dati demografici. |
| Webpage_Logica/esercizi/esercitazione.html | Interfaccia del quiz; è il contenitore usato dai moduli quiz-*.js. |
| Webpage_Logica/progressi/index.html | Dashboard personale costruita dai dati IndexedDB del browser. |
| Webpage_Logica/ripasso/errori.html | Elenco filtrabile degli errori salvati per il ripasso. |
| Webpage_Logica/strumenti/sandbox.html | Laboratorio di logica con input simbolico, risultati e costruttore ad albero. |
| Webpage_Logica/grafici/grafici.html | Galleria dei grafici aggregati pubblicati da feedback. |
| Webpage_Logica/grafici/placeholder.svg | Segnaposto locale mostrato quando un grafico non è disponibile. |
| Webpage_Logica/Errori_comuni/index.html | Indice delle spiegazioni sugli errori comuni. |
| Webpage_Logica/Errori_comuni/Per_Ogni.html | Scheda didattica sull'uso del quantificatore universale. |
| Webpage_Logica/Errori_comuni/Esiste.html | Scheda didattica sull'uso del quantificatore esistenziale. |
| Webpage_Logica/Errori_comuni/O_logico.html | Scheda didattica sulla disgiunzione logica. |
| Webpage_Logica/Errori_comuni/Implica.html | Scheda didattica sull'implicazione. |
| Webpage_Logica/Errori_comuni/Equivalenza.html | Scheda didattica sull'equivalenza. |
| Webpage_Logica/Errori_comuni/Conseguenza.html | Scheda didattica sulla conseguenza logica. |
| Webpage_Logica/Errori_comuni/Formula_vera.html | Scheda didattica sulla verità di una formula. |
| Webpage_Logica/lezioni/lezione-1.html | Prima lezione e relativi controlli interattivi. |
| Webpage_Logica/lezioni/lezione-2.html | Seconda lezione e relativi controlli interattivi. |
| Webpage_Logica/lezioni/lezione-3.html | Terza lezione e relativi controlli interattivi. |
| Webpage_Logica/lezioni/lezione-4.html | Quarta lezione e relativi controlli interattivi. |
| Webpage_Logica/lezioni/lezione-5.html | Quinta lezione e relativi controlli interattivi. |
| Webpage_Logica/lezioni/lezione-6.html | Sesta lezione e relativi controlli interattivi. |
| Webpage_Logica/favicon.ico | Icona del sito; è un asset binario, non codice. |
| Webpage_Logica/Immagini/*.png | Asset didattici chiari/scuri per domande e quantificatori; mantenere esatti nomi e maiuscole. |

### Webpage_Logica: JavaScript di base

| File | Come usarlo |
| --- | --- |
| Webpage_Logica/scripts/app.js | Bootstrap comune dell'interfaccia e dei collegamenti globali. |
| Webpage_Logica/scripts/app-events.js | Bus di eventi e nomi degli eventi condivisi tra moduli. |
| Webpage_Logica/scripts/app-storage.js | Accesso centralizzato a IndexedDB e lifecycle dei dati locali. |
| Webpage_Logica/scripts/api-client.js | Client same-origin per l'API, timeout, request ID ed errori normalizzati. |
| Webpage_Logica/scripts/data-contracts.js | Versioni e validatori dei dati persistiti nel browser. |
| Webpage_Logica/scripts/logger.js | Logging client controllato senza includere payload sensibili. |
| Webpage_Logica/scripts/settings.js | Applica impostazioni globali e controlli di accessibilità. |
| Webpage_Logica/scripts/settings-preferences.js | Persiste e ripristina tema, testo e preferenze di visualizzazione. |
| Webpage_Logica/scripts/privacy-controls.js | Gestisce consensi, cancellazione selettiva e stato della privacy. |
| Webpage_Logica/scripts/results-export.js | Esporta i risultati locali nei formati JSON e CSV. |

### Webpage_Logica: quiz e feedback in uscita

| File | Come usarlo |
| --- | --- |
| Webpage_Logica/scripts/quiz.js | Coordinatore principale del quiz e compatibilità con il markup della pagina. |
| Webpage_Logica/scripts/quiz-bootstrap.js | Avvia i moduli del quiz nell'ordine corretto. |
| Webpage_Logica/scripts/quiz-config.js | Legge e valida la configurazione scelta dall'utente. |
| Webpage_Logica/scripts/quiz-batch.js | Richiede e gestisce batch di domande dall'API. |
| Webpage_Logica/scripts/quiz-session.js | Avvio, avanzamento, ripresa e conclusione di una sessione. |
| Webpage_Logica/scripts/quiz-state.js | Stato runtime del quiz, separato da DOM e trasporto. |
| Webpage_Logica/scripts/quiz-timer.js | Countdown, scadenza e aggiornamenti temporali. |
| Webpage_Logica/scripts/quiz-renderer.js | Renderizza domanda, risposte, controlli e stato di errore. |
| Webpage_Logica/scripts/quiz-normalizers.js | Normalizza le diverse forme delle risposte API per la UI. |
| Webpage_Logica/scripts/quiz-shared.js | Costanti e funzioni riutilizzate dai moduli quiz. |
| Webpage_Logica/scripts/quiz-payloads.js | Costruisce i payload delle chiamate API e ne preserva il contratto. |
| Webpage_Logica/scripts/quiz-report.js | Crea il report storico finale che deve rimanere identico durante il trasferimento a feedback. |
| Webpage_Logica/scripts/quiz-feedback.js | Invia il report con consenso a /api/revisione e usa Idempotency-Key UUIDv4. |
| Webpage_Logica/scripts/quiz-images-question.js | Associa e mostra l'immagine prevista dalla domanda. |
| Webpage_Logica/scripts/quiz-images-correct.js | Gestisce l'immagine o lo stato visuale della risposta corretta. |
| Webpage_Logica/scripts/quiz-images-wrong.js | Gestisce l'immagine o lo stato visuale della risposta errata. |

### Webpage_Logica: apprendimento, formule e strumenti

| File | Come usarlo |
| --- | --- |
| Webpage_Logica/scripts/adaptive-engine.js | Calcola localmente difficoltà e suggerimenti adattivi spiegabili. |
| Webpage_Logica/scripts/learning-metrics.js | Deriva indicatori di apprendimento dalle sessioni persistite. |
| Webpage_Logica/scripts/dashboard.js | Prepara dati e componenti della pagina I miei progressi. |
| Webpage_Logica/scripts/index-progress.js | Mostra nella home il riepilogo sintetico dei progressi. |
| Webpage_Logica/scripts/charts.js | Disegna i grafici personali della dashboard dai dati locali. |
| Webpage_Logica/scripts/error-notebook.js | Modello e operazioni del quaderno degli errori. |
| Webpage_Logica/scripts/error-notebook-page.js | Controller DOM della pagina di ripasso degli errori. |
| Webpage_Logica/scripts/lesson-progress.js | Registra e mostra l'avanzamento delle lezioni. |
| Webpage_Logica/scripts/lesson-checks.js | Gestisce esercizi e verifiche brevi inseriti nelle lezioni. |
| Webpage_Logica/scripts/lesson-radio.js | Gestisce gruppi radio e feedback immediato nelle lezioni. |
| Webpage_Logica/scripts/formula-syntax.js | Parser e formattatore condiviso tra sintassi funzionale e simboli logici. |
| Webpage_Logica/scripts/formula-tree.js | Renderizza l'albero SVG di una formula ricevuta o inserita. |
| Webpage_Logica/scripts/formula-construction.js | Interpreta la trace che descrive la struttura bottom-up. |
| Webpage_Logica/scripts/formula-construction-renderer.js | Renderizza i passaggi strutturali quando il relativo contratto è presente. |
| Webpage_Logica/scripts/formula-transformation.js | Valida e prepara la trace che porta dalla formula A alla formula B. |
| Webpage_Logica/scripts/formula-transformation-renderer.js | Mostra legge generale, applicazione locale e formula raggiunta a ogni passo. |
| Webpage_Logica/scripts/logic-sandbox.js | Controller del Laboratorio: input, chiamate API, risultati e coordinamento albero. |
| Webpage_Logica/scripts/logic-tree-builder.js | Costruttore interattivo ad albero con atomi e operatori logici. |
| Webpage_Logica/scripts/feedback-charts.js | Scarica manifest e PNG aggregati dal servizio feedback con refresh controllato. |
| Webpage_Logica/scripts/graphs-gallery.js | Gestisce layout, stato vuoto ed esperienza della galleria. |

### Webpage_Logica: fogli di stile

| File | Ambito |
| --- | --- |
| Webpage_Logica/styles/base.css | Reset, variabili fondamentali, tipografia e layout globale. |
| Webpage_Logica/styles/components.css | Pulsanti, campi, card, navigazione e componenti condivisi. |
| Webpage_Logica/styles/themes.css | Temi, contrasto, dimensione del testo e varianti di accessibilità. |
| Webpage_Logica/styles/quiz.css | Layout e stati specifici del configuratore e del quiz. |
| Webpage_Logica/styles/quiz-images.css | Dimensionamento e disposizione delle immagini nelle domande. |
| Webpage_Logica/styles/errori.css | Stili limitati all'indice e alle schede degli errori comuni. |
| Webpage_Logica/styles/study-tools.css | Laboratorio, progressi, lezioni e strumenti di studio. |
| Webpage_Logica/styles/formula-construction.css | Presentazione della trace di costruzione strutturale. |
| Webpage_Logica/styles/formula-transformation.css | Presentazione della sequenza dalla formula A alla formula B. |
| Webpage_Logica/styles/graphs.css | Griglia, card, stati e immagini dei grafici feedback. |

Quando si modifica il CSS, preferire una classe della pagina o del componente
come selettore radice. Non ridefinire globalmente input, button o label in un
foglio specifico: base.css e components.css sono responsabili dello stile
condiviso, mentre gli altri file devono contenere soltanto adattamenti locali.

### Webpage_Logica: test

| File | Copertura |
| --- | --- |
| Webpage_Logica/tests/api-client.test.js | URL same-origin, timeout, request ID e traduzione degli errori API. |
| Webpage_Logica/tests/app-enhancements.test.js | Inizializzazione e miglioramenti comuni delle pagine. |
| Webpage_Logica/tests/charts.test.js | Elaborazione e rendering dei grafici personali. |
| Webpage_Logica/tests/content-security.test.js | CSP, assenza di pattern non sicuri e vincoli sugli asset. |
| Webpage_Logica/tests/feature-foundations.test.js | Presenza dei moduli e contratti base delle funzionalità. |
| Webpage_Logica/tests/feedback-charts.test.js | Manifest feedback, allow-list degli asset, refresh e stati di errore. |
| Webpage_Logica/tests/formula-construction.test.js | Parsing e rendering della trace strutturale. |
| Webpage_Logica/tests/formula-syntax.test.js | Conversione robusta tra sintassi API e simboli visibili. |
| Webpage_Logica/tests/formula-transformation.test.js | Continuità e visualizzazione dei passaggi dalla formula A alla B. |
| Webpage_Logica/tests/formula-tree-layout.test.js | Geometria dell'albero e assenza di sovrapposizioni. |
| Webpage_Logica/tests/frontend-retirement.test.js | Assenza di ricerca, modalità online/offline e vecchia PWA. |
| Webpage_Logica/tests/global-ui-refresh.test.js | Coerenza dei componenti e regressioni dell'interfaccia globale. |
| Webpage_Logica/tests/learning-features.test.js | Progressi, metriche, adattamento e funzionalità didattiche. |
| Webpage_Logica/tests/live-clear-ui.test.js | Cancellazione dei dati e aggiornamento immediato della UI. |
| Webpage_Logica/tests/logic-tree-builder.test.js | Creazione di atomi, collegamenti, operatori e formula risultante. |
| Webpage_Logica/tests/quiz-error-explanations.test.js | Ritorno al menu sugli errori e precedenza della spiegazione rispetto alle immagini. |
| Webpage_Logica/tests/quiz-flow-regressions.test.js | Regressioni end-to-end del flusso del quiz. |
| Webpage_Logica/tests/quiz-modules.test.js | Collaborazione e responsabilità dei moduli quiz. |
| Webpage_Logica/tests/quiz-payloads.test.js | Contratti esatti dei payload inviati all'API. |
| Webpage_Logica/tests/quiz-report.test.js | Forma storica del report finale e consensi. |
| Webpage_Logica/tests/quiz-services.test.js | Sessione, batch, timer e servizi usati dal quiz. |
| Webpage_Logica/tests/secondary-ui.test.js | Pagine secondarie, Laboratorio, progressi e controlli visuali. |
| Webpage_Logica/tests/server-deployment.test.js | Compose, Nginx, reti, healthcheck e proprietà del deploy. |
| Webpage_Logica/tests/settings-preferences.test.js | Persistenza e applicazione delle preferenze. |
| Webpage_Logica/tests/storage-lifecycle.test.js | IndexedDB prima/dopo consenso, scadenze, ripresa e cancellazione selettiva. |

## Come utilizzare feedback

### Flusso normale dal sito

1. L'utente termina un quiz.
2. quiz-report.js costruisce il payload storico.
3. Se il consenso feedback è attivo, quiz-feedback.js invia lo stesso oggetto a
   POST /api/revisione con una Idempotency-Key UUIDv4.
4. Nginx inoltra la richiesta al solo container feedback sulla rete interna.
5. Il servizio valida e sincronizza il JSON in SQLite, poi risponde 201 senza
   attendere la creazione dei grafici.
6. feedback-worker, dopo FEEDBACK_PUBLISH_INTERVAL_SECONDS, legge i report,
   calcola aggregati e pubblica uno snapshot atomico.
7. La pagina Grafici scarica il manifest e mostra gli asset pubblicati.

I dati grezzi non attraversano API_Logica. Le normalizzazioni statistiche
avvengono soltanto nella vista analitica e non riscrivono il payload conservato.

### Dove sono i dati

Con la configurazione locale consigliata:

- database: feedback/data/receipts/feedback.sqlite3
- manifest corrente: feedback/data/charts/manifest.json
- immagini: feedback/data/charts/snapshots/ID_GENERAZIONE/CATEGORIA/NOME.png
- stato del worker: feedback/data/charts/worker-status.json

Il nome JSON restituito dal POST è un identificatore logico della ricevuta. Il
servizio corrente non crea un file JSON separato per ogni invio: il documento è
salvato come record nel database SQLite.

Per ispezionare lo stato con i container integrati avviati:

~~~bash
cd Webpage_Logica
docker compose exec feedback python -m feedback_service.admin status
docker compose exec feedback python -m feedback_service.admin check
docker compose logs --follow feedback feedback-worker
~~~

status è di sola lettura. check apre e valida lo storage e può applicare una
migrazione di schema supportata.

### Ottenere rapidamente grafici in locale

Le impostazioni predefinite richiedono almeno 10 sessioni e pubblicano ogni
86400 secondi. Per un collaudo breve, impostare temporaneamente in
Webpage_Logica/.env:

~~~text
FEEDBACK_MIN_AGGREGATE_SESSIONS=2
FEEDBACK_PUBLISH_INTERVAL_SECONDS=2
~~~

Ricostruire lo stack Web, completare due quiz validi accettando il consenso
feedback e poi aprire:

http://localhost:12345/grafici/grafici.html

Una coorte sotto la soglia produce un segnaposto neutro; non espone dati della
singola sessione.

### Backup, retention e cancellazione

Con lo stack integrato:

~~~bash
cd Webpage_Logica
docker compose exec feedback python -m feedback_service.admin purge
docker compose exec feedback python -m feedback_service.admin backup /app/data/backups/feedback-manuale.sqlite3
~~~

- purge elimina soltanto le ricevute scadute secondo la retention.
- backup usa l'API SQLite, include i commit WAL, crea un file con modo 0600 e
  rifiuta di sovrascrivere una destinazione esistente.
- Non copiare feedback.sqlite3 direttamente mentre il servizio è attivo.

Sul server usare, dalla directory feedback:

~~~bash
./scripts/server-backup.sh --env-file ../Webpage_Logica/.env.server
~~~

Per eliminare tutti i dati locali, creare prima un backup se necessario,
arrestare lo stack Web e rimuovere come utente normale le sottodirectory
feedback/data/receipts e feedback/data/charts. L'operazione è irreversibile; al
riavvio prepare-data.sh o i container ricreano la struttura privata. Non esiste
un endpoint HTTP che esponga i payload grezzi o cancelli arbitrariamente una
ricevuta.

### Endpoint feedback

| Metodo e percorso | Uso |
| --- | --- |
| POST /api/revisione | Valida e salva un report; 201 per inserimento o retry idempotente valido. |
| GET /api/feedback/charts/manifest | Restituisce il manifest corrente, oppure 404 prima della pubblicazione. |
| GET /api/feedback/charts/{generation_id}/{category}/{filename} | Serve soltanto PNG presenti nell'allow-list del manifest. |
| GET /health | Liveness del processo HTTP. |
| GET /ready | Controlla database, snapshot e heartbeat del worker. |
| GET /metrics | Metriche Prometheus private, senza payload o etichette utente. |
| GET /docs, /redoc, /openapi.json | Documentazione e contratto del servizio. |

Risposte rilevanti del POST: 400 richiesta malformata, 409 chiave idempotente
riusata con body diverso, 413 body troppo grande, 415 content type errato, 422
payload non valido, 503 storage non pronto e 507 quota o spazio esauriti.

La porta 5555 non deve essere esposta alla rete. Nel Compose Web non è pubblicata;
il Compose standalone feedback la collega soltanto a 127.0.0.1 ed è destinato
allo sviluppo. Non avviare contemporaneamente Compose standalone e integrato
sulla stessa directory dati.

### Migrazione di vecchi report

I vecchi file JSON possono essere importati esplicitamente:

~~~bash
cd feedback
python -m feedback_service.migrate_legacy /percorso/dump --dry-run
python -m feedback_service.migrate_legacy /percorso/dump
~~~

Eseguire sempre prima dry-run. La sorgente non viene modificata.

### feedback: configurazione e avvio

| File | Come usarlo |
| --- | --- |
| feedback/README.md | Documentazione canonica di storage, privacy, worker, backup, restore e deploy. |
| feedback/pyproject.toml | Package, dipendenze runtime/dev e configurazione di pytest, Ruff e mypy. |
| feedback/Dockerfile | Immagine non-root comune al processo HTTP e al worker. |
| feedback/docker-compose.yml | Stack standalone di sviluppo su loopback; non usarlo insieme al Compose Web. |
| feedback/.env | Configurazione locale reale e ignorata; non committare valori o percorsi privati. |
| feedback/.env.example | Modello per UID/GID, directory, quote, soglie e intervalli. |
| feedback/.dockerignore | Esclude dati, cache e artefatti dal contesto Docker. |
| feedback/.gitignore | Esclude database, grafici, report, env e cache. |
| feedback/.gitattributes | Normalizza terminatori e permessi su Linux. |
| feedback/.github/workflows/ci.yml | Esegue test, qualità statica e build del servizio. |
| feedback/.github/dependabot.yml | Configura gli aggiornamenti automatici delle dipendenze del repository. |
| feedback/data/.gitkeep | Mantiene la directory vuota in Git; i contenuti reali sono persistenti e ignorati. |

### feedback: package applicativo

| File | Come usarlo |
| --- | --- |
| feedback/feedback_service/__init__.py | Dichiara il package e la sua versione pubblica. |
| feedback/feedback_service/app.py | Applicazione FastAPI: POST, manifest, asset, health, ready, metriche e middleware. |
| feedback/feedback_service/schemas.py | Contratto Pydantic del payload storico e delle risposte HTTP. |
| feedback/feedback_service/config.py | Legge e valida directory, quote, retention, soglie e tempi del worker. |
| feedback/feedback_service/storage.py | Repository SQLite: schema, WAL, idempotenza, quote, retention, backup e restore. |
| feedback/feedback_service/coordinator.py | Coordina inizializzazione, storage e operazioni condivise dai processi. |
| feedback/feedback_service/data_processor.py | Legge i report e costruisce il dataset aggregato per il rendering. |
| feedback/feedback_service/analytics.py | Normalizza la sola vista analitica e calcola metriche, coorti e intervalli. |
| feedback/feedback_service/chart_generator.py | Genera i 22 grafici e i segnaposto con Matplotlib. |
| feedback/feedback_service/snapshots.py | Pubblica atomicamente manifest e asset, verifica hash e ripulisce vecchie generazioni. |
| feedback/feedback_service/filelock.py | Lock interprocesso per impedire worker o pubblicazioni concorrenti. |
| feedback/feedback_service/worker.py | Processo periodico esterno per retention, aggregazione e pubblicazione. |
| feedback/feedback_service/worker_status.py | Scrive e valida heartbeat, ultimo ciclo e stato del worker. |
| feedback/feedback_service/metrics.py | Metriche Prometheus aggregate e prive di contenuti del payload. |
| feedback/feedback_service/admin.py | CLI per status, check, purge, backup e restore. |
| feedback/feedback_service/migrate_legacy.py | Importatore esplicito e idempotente dei vecchi report JSON. |

### feedback: script e test

| File | Come usarlo |
| --- | --- |
| feedback/scripts/prepare-data.sh | Crea bind mount e sottodirectory private con UID/GID dell'utente, senza sudo. |
| feedback/scripts/server-backup.sh | Produce backup SQLite consistente e checksum nel bind persistente del server. |
| feedback/tests/test_feedback_service.py | Contratto HTTP, validazione, idempotenza, limiti e accesso agli asset. |
| feedback/tests/test_external_worker.py | Separazione HTTP/worker, heartbeat, aggregazione e pubblicazione periodica. |
| feedback/tests/test_sqlite_storage.py | Transazioni, WAL, concorrenza, hash, quote, backup e restore. |
| feedback/tests/test_storage_maintenance.py | Retention, checkpoint, compattazione e gestione dello spazio. |
| feedback/tests/test_snapshot_cleanup.py | Pubblicazione atomica, integrità, allow-list e pulizia delle generazioni. |
| feedback/tests/test_prepare_data_script.py | Permessi, UID/GID, idempotenza e sicurezza di prepare-data.sh. |
| feedback/tests/test_server_operations.py | Compose, immagine, backup e vincoli operativi del server. |

### feedback: artefatti locali esclusi

I vecchi script Python della radice sono stati rimossi. Questi eventuali output
locali non fanno parte del runtime e non devono essere pubblicati:

| File | Stato |
| --- | --- |
| feedback/Risultati.txt | Dato/risultato locale storico; non è sorgente e non va pubblicato. |
| feedback/report_feedback.txt | Report locale storico; non è usato dal servizio. |
| feedback/radar_competenze.png | Immagine generata storica; i grafici correnti vivono in data/charts. |

## Regole pratiche per modificare il codice

### Contratti tra Web e API

- Considerare server/schemas.py e OpenAPI come contratto pubblico.
- Il Web deve chiamare percorsi same-origin sotto /api; Nginx sceglie l'upstream.
- Aggiungere prima schema e test del contratto, poi route e logica di dominio.
- Non importare moduli Python nel Web e non spostare algoritmi logici in
  JavaScript per aggirare l'API.
- Una formula mostrata all'utente passa da formula-syntax.js; una formula inviata
  all'API conserva la sintassi funzionale prevista dal contratto.

### Contratto del report feedback

- quiz-report.js è la fonte del payload storico.
- quiz-feedback.js deve trasferire l'oggetto senza rinominare campi, aggiungere
  dati al body o normalizzare valori.
- schemas.py convalida il contratto in ingresso.
- storage.py conserva un JSON deep-equal al body.
- analytics.py può costruire una vista normalizzata soltanto dopo la lettura.
- Qualsiasi modifica in questa catena richiede almeno i test quiz-report,
  quiz-payloads, test_feedback_service e test_sqlite_storage.

### Stato nel browser

app-storage.js è l'unico punto comune per IndexedDB. Le pagine non devono aprire
database paralleli. Prima del consenso i dati non persistenti restano in memoria;
dopo il consenso i repository locali gestiscono sessioni, progressi ed errori.
privacy-controls.js coordina consenso e cancellazione, mentre
storage-lifecycle.test.js protegge ripresa, scadenze e cancellazione selettiva.

### Trace delle formule

- formula_construction.py e formula-construction*.js spiegano la composizione
  strutturale della formula.
- formula_transformation.py e formula-transformation*.js spiegano come si passa
  dalla formula della domanda alla risposta corretta.
- Per una sezione chiamata Costruzione della risposta corretta usare la trace
  transformation: ogni riga deve mostrare legge, applicazione e formula ottenuta.

### CSS

Prima di aggiungere una regola controllare base.css e components.css. Usare il
foglio specifico della funzione e un selettore radice locale. Verificare almeno:

- desktop e viewport mobile;
- campi con opzioni attive e disattive;
- testi lunghi, errori e stati vuoti;
- tema chiaro/scuro e dimensione testo aumentata;
- alberi con formule profonde;
- assenza di overflow, sovrapposizioni e controlli non centrati.

Dopo ogni modifica Web eseguire npm run verify e un controllo reale in browser.

## Avvio sul server

Il server usa i Compose e gli script di produzione dei repository API e Web,
non il Compose standalone feedback. Preparare i due file reali:

~~~bash
cp API_Logica/.env.server.example API_Logica/.env.server
chmod 600 API_Logica/.env.server
cp Webpage_Logica/.env.server.example Webpage_Logica/.env.server
chmod 600 Webpage_Logica/.env.server
~~~

Compilare tag e revisioni univoci, CORS/URL pubblico, UID/GID dell'utente di
deployment e percorsi assoluti persistenti posseduti dallo stesso utente. Poi:

~~~bash
cd API_Logica
./scripts/deploy-server.sh
cd ../Webpage_Logica
./ops/server-deploy.sh
~~~

Gli script eseguono preflight, build, avvio con attesa e smoke test; non fanno
commit né push. Il Web deve essere pubblicato soltanto su loopback dietro il
reverse proxy TLS dell'host. API e feedback restano su reti Docker private e non
devono esporre le porte 5000 o 5555 a Internet. Per tutti i dettagli di release,
backup, restore e rollback consultare i README dei singoli repository.

## Checklist prima di consegnare una modifica

1. Controllare l'inventario dei sorgenti nei tre componenti. Le precedenti
   directory Git sono state rimosse; le release usano checksum dei file.
2. Non annullare modifiche preesistenti e non includere `.env`, database,
   grafici o cache.
3. Eseguire i test del componente modificato e i test dei contratti attraversati.
4. Eseguire docker compose config nei Compose interessati.
5. Avviare entrambi gli stack locali e controllare health, ready, capabilities e
   OpenAPI.
6. Collaudare da http://localhost:12345 il flusso coinvolto.
7. Per modifiche feedback, verificare consenso, 201, record SQLite, heartbeat,
   manifest e caricamento dei PNG.
8. Confermare che API_Logica non contenga route o storage feedback.
9. Confermare che la modalità docente, punto 15, non sia stata implementata.
