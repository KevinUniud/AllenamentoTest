/* Aggiorna la galleria con gli snapshot pubblicati dal servizio feedback. */
(function exposeFeedbackCharts(global) {
    'use strict';

    const MANIFEST_URL = '/api/feedback/charts/manifest';
    const PLACEHOLDER_URL = './placeholder.svg';
    const CHARTS = Object.freeze({
        'general.performance_summary': Object.freeze({
            category: 'general', filename: 'performance_summary.png'
        }),
        'general.percentuale_domande_corrette': Object.freeze({
            category: 'general', filename: 'percentuale_domande_corrette.png'
        }),
        'general.corrette_vs_errate': Object.freeze({
            category: 'general', filename: 'corrette_vs_errate.png'
        }),
        'timings.tempo_medio_risposta': Object.freeze({
            category: 'timings', filename: 'tempo_medio_risposta.png'
        }),
        'timings.tempo_per_tipologia': Object.freeze({
            category: 'timings', filename: 'tempo_per_tipologia.png'
        }),
        'timings.tempo_vs_correttezza': Object.freeze({
            category: 'timings', filename: 'tempo_vs_correttezza.png'
        }),
        'timings.distribuzione_tempi': Object.freeze({
            category: 'timings', filename: 'distribuzione_tempi.png'
        }),
        'timings.boxplot_tempi_tipologia': Object.freeze({
            category: 'timings', filename: 'boxplot_tempi_tipologia.png'
        }),
        'timings.timeline_risposte': Object.freeze({
            category: 'timings', filename: 'timeline_risposte.png'
        }),
        'temporal.accuracy_timeline': Object.freeze({
            category: 'temporal', filename: 'accuracy_timeline.png'
        }),
        'temporal.velocity_timeline': Object.freeze({
            category: 'temporal', filename: 'velocity_timeline.png'
        }),
        'behavioral.opzioni_vs_performance': Object.freeze({
            category: 'behavioral', filename: 'opzioni_vs_performance.png'
        }),
        'behavioral.heatmap_sessioni_tipologie': Object.freeze({
            category: 'behavioral', filename: 'heatmap_sessioni_tipologie.png'
        }),
        'demographics.performance_per_demographic': Object.freeze({
            category: 'demographics', filename: 'performance_per_demographic.png'
        }),
        'demographics.feedback_correlation': Object.freeze({
            category: 'demographics', filename: 'feedback_correlation.png'
        }),
        'accuracy.accuratezza_per_tipologia': Object.freeze({
            category: 'accuracy', filename: 'accuratezza_per_tipologia.png'
        }),
        'accuracy.difficolta_vs_risultato': Object.freeze({
            category: 'accuracy', filename: 'difficolta_vs_risultato.png'
        }),
        'accuracy.multipanel_tipologia': Object.freeze({
            category: 'accuracy', filename: 'multipanel_tipologia.png'
        }),
        'accuracy.radar_competenze': Object.freeze({
            category: 'accuracy', filename: 'radar_competenze.png'
        }),
        'advanced.performance_projection': Object.freeze({
            category: 'advanced', filename: 'performance_projection.png'
        }),
        'advanced.learning_curve': Object.freeze({
            category: 'advanced', filename: 'learning_curve.png'
        }),
        'advanced.regression_tempo_accuracy': Object.freeze({
            category: 'advanced', filename: 'regression_tempo_accuracy.png'
        })
    });
    const EXPECTED_COUNT = Object.keys(CHARTS).length;
    const DEFAULT_REFRESH_SECONDS = 300;
    const MIN_REFRESH_SECONDS = 30;
    const MAX_REFRESH_SECONDS = 86400;
    const imageErrorHandlers = new WeakMap();

    function setStatus(status, state, message) {
        if (!status) return;
        status.dataset.state = state;
        status.textContent = message;
    }

    function normalizeRefreshSeconds(value) {
        const parsed = Number(value);
        if (!Number.isInteger(parsed)) return DEFAULT_REFRESH_SECONDS;
        return Math.min(MAX_REFRESH_SECONDS, Math.max(MIN_REFRESH_SECONDS, parsed));
    }

    function refreshSecondsFrom(response) {
        if (!response || !response.headers || typeof response.headers.get !== 'function') {
            return DEFAULT_REFRESH_SECONDS;
        }
        return normalizeRefreshSeconds(response.headers.get('X-Feedback-Refresh-Seconds'));
    }

    function parseManifest(manifest) {
        if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)
            || manifest.schema_version !== 1 || !Array.isArray(manifest.charts)) {
            throw new TypeError('Manifest dei grafici non valido');
        }

        const generationId = String(manifest.generation_id || '');
        if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(generationId)) {
            throw new TypeError('Identificativo di generazione non valido');
        }

        const generatedAt = String(manifest.generated_at || '');
        if (!generatedAt || !Number.isFinite(Date.parse(generatedAt))) {
            throw new TypeError('Data di generazione non valida');
        }

        if (typeof manifest.session_count !== 'number'
            || !Number.isSafeInteger(manifest.session_count)
            || manifest.session_count < 2) {
            throw new TypeError('Numero di sessioni aggregate non valido');
        }

        const selected = [];
        const seen = new Set();
        manifest.charts.slice(0, 100).forEach(function(entry) {
            if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return;
            const id = String(entry.id || '');
            const expected = CHARTS[id];
            if (!expected || seen.has(id)) return;
            if (entry.category !== expected.category || entry.filename !== expected.filename) return;
            seen.add(id);
            selected.push(Object.freeze({
                id: id,
                category: expected.category,
                filename: expected.filename,
                assetUrl: '/api/feedback/charts/' + generationId + '/'
                    + expected.category + '/' + expected.filename
            }));
        });

        return Object.freeze({
            generationId: generationId,
            generatedAt: generatedAt,
            sessionCount: manifest.session_count,
            charts: Object.freeze(selected)
        });
    }

    function localizedDate(value) {
        try {
            return new Intl.DateTimeFormat('it-IT', {
                dateStyle: 'medium',
                timeStyle: 'short'
            }).format(new Date(value));
        } catch (_) {
            return value;
        }
    }

    function updateTemporalDetails(documentRef, attemptedAt, parsed) {
        const attempt = documentRef.getElementById('feedbackChartsLastAttempt');
        if (attempt) {
            attempt.textContent = 'Ultimo tentativo: ' + localizedDate(attemptedAt) + '.';
            attempt.dateTime = new Date(attemptedAt).toISOString();
        }
        if (!parsed) return;
        const published = documentRef.getElementById('feedbackChartsLastPublished');
        if (published) {
            published.textContent = 'Ultima pubblicazione: ' + localizedDate(parsed.generatedAt)
                + ' · ' + parsed.sessionCount + ' sessioni aggregate.';
            published.dateTime = new Date(parsed.generatedAt).toISOString();
        }
    }

    function applyManifest(documentRef, parsed, status) {
        const images = new Map();
        Array.from(documentRef.querySelectorAll('.graph-card img[data-chart-id]')).forEach(function(image) {
            const id = image.getAttribute('data-chart-id');
            if (CHARTS[id] && !images.has(id)) images.set(id, image);
        });

        let applied = 0;
        let failed = 0;
        parsed.charts.forEach(function(chart) {
            const image = images.get(chart.id);
            if (!image) return;
            const previousSource = image.getAttribute('src') || PLACEHOLDER_URL;
            const fallbackSource = previousSource === chart.assetUrl
                ? PLACEHOLDER_URL : previousSource;
            const previousHandler = imageErrorHandlers.get(image);
            if (previousHandler && typeof image.removeEventListener === 'function') {
                image.removeEventListener('error', previousHandler);
            }

            const restorePreviousImage = function restorePreviousImage() {
                if (image.getAttribute('src') !== chart.assetUrl) return;
                failed += 1;
                image.setAttribute('src', fallbackSource);
                setStatus(
                    status,
                    'fallback',
                    'Alcuni grafici della pubblicazione più recente non sono disponibili. '
                        + 'Resta il contenuto precedente o il segnaposto neutro.'
                );
            };
            imageErrorHandlers.set(image, restorePreviousImage);
            image.addEventListener('error', restorePreviousImage, { once: true });
            image.setAttribute('src', chart.assetUrl);
            image.setAttribute('data-chart-generation', parsed.generationId);
            applied += 1;
        });

        if (applied === EXPECTED_COUNT) {
            setStatus(
                status,
                'updated',
                'Grafici aggregati da ' + parsed.sessionCount + ' sessioni, pubblicati il '
                    + localizedDate(parsed.generatedAt) + '.'
            );
        } else if (applied > 0) {
            setStatus(
                status,
                'fallback',
                'Disponibili ' + applied + ' grafici aggiornati su ' + EXPECTED_COUNT
                    + ' dalla pubblicazione di ' + parsed.sessionCount
                    + ' sessioni; per gli altri resta il contenuto precedente o il segnaposto.'
            );
        } else {
            setStatus(
                status,
                'fallback',
                'Il servizio feedback non ha ancora pubblicato grafici compatibili. '
                    + 'Vengono mostrati segnaposto privi di dati.'
            );
        }

        return Object.freeze({ applied: applied, failed: failed });
    }

    async function refresh(documentRef, fetchImpl, options) {
        const status = documentRef && documentRef.getElementById('feedbackChartsStatus');
        const attemptedAt = options && options.now ? options.now() : new Date();
        if (!documentRef || typeof fetchImpl !== 'function') {
            setStatus(status, 'error', 'Impossibile verificare i grafici aggiornati. Vengono mostrati segnaposto privi di dati.');
            return Object.freeze({
                state: 'error', applied: 0, refreshSeconds: DEFAULT_REFRESH_SECONDS
            });
        }

        updateTemporalDetails(documentRef, attemptedAt);
        setStatus(status, 'loading', 'Controllo di una nuova pubblicazione in corso…');

        let response;
        try {
            response = await fetchImpl(MANIFEST_URL, {
                method: 'GET',
                headers: { Accept: 'application/json' },
                cache: 'no-store',
                credentials: 'same-origin'
            });
        } catch (_) {
            setStatus(status, 'error', 'Servizio feedback non raggiungibile. Vengono mostrati segnaposto privi di dati.');
            return Object.freeze({
                state: 'network-error', applied: 0, refreshSeconds: DEFAULT_REFRESH_SECONDS
            });
        }

        const refreshSeconds = refreshSecondsFrom(response);

        if (response.status === 404 || response.status === 204) {
            setStatus(
                status,
                'waiting',
                'Nessuno snapshot è ancora pubblicabile: il campione minimo può non essere '
                    + 'stato raggiunto oppure il periodo di pubblicazione non è ancora trascorso.'
            );
            return Object.freeze({ state: 'waiting', applied: 0, refreshSeconds: refreshSeconds });
        }
        if (!response.ok) {
            setStatus(status, 'error', 'Errore nel caricamento dei grafici aggiornati. Vengono mostrati segnaposto privi di dati.');
            return Object.freeze({ state: 'http-error', applied: 0, refreshSeconds: refreshSeconds });
        }

        try {
            const parsed = parseManifest(await response.json());
            const result = applyManifest(documentRef, parsed, status);
            updateTemporalDetails(documentRef, attemptedAt, parsed);
            return Object.freeze({
                state: result.applied === EXPECTED_COUNT ? 'updated' : 'fallback',
                applied: result.applied,
                refreshSeconds: refreshSeconds,
                sessionCount: parsed.sessionCount,
                generatedAt: parsed.generatedAt
            });
        } catch (_) {
            setStatus(status, 'error', 'Manifest dei grafici non valido. Vengono mostrati segnaposto privi di dati.');
            return Object.freeze({ state: 'invalid-manifest', applied: 0, refreshSeconds: refreshSeconds });
        }
    }

    function createController(globalRef, documentRef, fetchImpl, options) {
        const settings = options || {};
        const setTimer = settings.setTimeout || globalRef.setTimeout.bind(globalRef);
        const clearTimer = settings.clearTimeout || globalRef.clearTimeout.bind(globalRef);
        const refreshButton = documentRef.getElementById('feedbackChartsRefresh');
        let refreshSeconds = normalizeRefreshSeconds(settings.refreshSeconds);
        let timerId = null;
        let inFlight = null;
        let disposed = false;

        function isVisible() {
            return documentRef.visibilityState !== 'hidden';
        }

        function cancelTimer() {
            if (timerId === null) return;
            clearTimer(timerId);
            timerId = null;
        }

        function schedule() {
            cancelTimer();
            if (disposed || !isVisible()) return;
            timerId = setTimer(function refreshAfterDelay() {
                timerId = null;
                run();
            }, refreshSeconds * 1000);
        }

        function run() {
            if (disposed) return Promise.resolve(Object.freeze({ state: 'disposed', applied: 0 }));
            if (inFlight) return inFlight;
            cancelTimer();
            if (refreshButton) refreshButton.disabled = true;

            inFlight = refresh(documentRef, fetchImpl, settings).then(function(result) {
                refreshSeconds = normalizeRefreshSeconds(result.refreshSeconds);
                return result;
            }).finally(function() {
                inFlight = null;
                if (refreshButton) refreshButton.disabled = false;
                schedule();
            });
            return inFlight;
        }

        function visibilityChanged() {
            cancelTimer();
            if (isVisible()) run();
        }

        function destroy() {
            if (disposed) return;
            disposed = true;
            cancelTimer();
            if (refreshButton) refreshButton.removeEventListener('click', run);
            documentRef.removeEventListener('visibilitychange', visibilityChanged);
            if (typeof globalRef.removeEventListener === 'function') {
                globalRef.removeEventListener('pagehide', destroy);
            }
        }

        if (refreshButton) refreshButton.addEventListener('click', run);
        documentRef.addEventListener('visibilitychange', visibilityChanged);
        if (typeof globalRef.addEventListener === 'function') {
            globalRef.addEventListener('pagehide', destroy, { once: true });
        }
        if (isVisible()) run();

        return Object.freeze({ destroy: destroy, refresh: run });
    }

    const api = Object.freeze({
        CHARTS: CHARTS,
        MANIFEST_URL: MANIFEST_URL,
        PLACEHOLDER_URL: PLACEHOLDER_URL,
        applyManifest: applyManifest,
        createController: createController,
        normalizeRefreshSeconds: normalizeRefreshSeconds,
        parseManifest: parseManifest,
        refresh: refresh
    });
    global.LogicFeedbackCharts = api;

    if (global.document) {
        const start = function startFeedbackCharts() {
            global.LogicFeedbackChartsController = createController(
                global,
                global.document,
                global.fetch && global.fetch.bind(global)
            );
        };
        if (global.document.readyState === 'loading') {
            global.document.addEventListener('DOMContentLoaded', start, { once: true });
        } else {
            start();
        }
    }
})(window);
