const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

class FakeImage {
    constructor(id, source) {
        this.attributes = new Map([
            ['data-chart-id', id],
            ['src', source]
        ]);
        this.listeners = new Map();
    }

    addEventListener(type, listener) {
        this.listeners.set(type, listener);
    }

    removeEventListener(type, listener) {
        if (this.listeners.get(type) === listener) this.listeners.delete(type);
    }

    dispatch(type) {
        const listener = this.listeners.get(type);
        if (listener) listener();
    }

    getAttribute(name) {
        return this.attributes.get(name) || null;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }
}

function loadModule() {
    const context = { Date, Intl, URL };
    context.window = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('scripts/feedback-charts.js', 'utf8'), context);
    return context.LogicFeedbackCharts;
}

function createHarness(charts) {
    const images = new Map(Object.entries(charts).map(function([id, chart]) {
        assert.ok(chart.category && chart.filename);
        return [id, new FakeImage(id, './placeholder.svg')];
    }));
    const status = { dataset: {}, textContent: '' };
    const attempt = { textContent: '', dateTime: '' };
    const published = { textContent: '', dateTime: '' };
    const listeners = new Map();
    const button = {
        disabled: false,
        addEventListener(type, listener) { listeners.set('button:' + type, listener); },
        removeEventListener(type, listener) {
            if (listeners.get('button:' + type) === listener) listeners.delete('button:' + type);
        },
        dispatch(type) {
            const listener = listeners.get('button:' + type);
            if (listener) listener();
        }
    };
    const document = {
        visibilityState: 'visible',
        getElementById(id) {
            return {
                feedbackChartsStatus: status,
                feedbackChartsLastAttempt: attempt,
                feedbackChartsLastPublished: published,
                feedbackChartsRefresh: button
            }[id] || null;
        },
        querySelectorAll(selector) {
            assert.equal(selector, '.graph-card img[data-chart-id]');
            return Array.from(images.values());
        },
        addEventListener(type, listener) { listeners.set('document:' + type, listener); },
        removeEventListener(type, listener) {
            if (listeners.get('document:' + type) === listener) listeners.delete('document:' + type);
        },
        dispatch(type) {
            const listener = listeners.get('document:' + type);
            if (listener) listener();
        }
    };
    return { document, images, status, attempt, published, button, listeners };
}

function manifestFor(api, ids) {
    return {
        schema_version: 1,
        generation_id: '2026-08-19_a1b2c3',
        generated_at: '2026-08-19T12:00:00Z',
        session_count: 24,
        source_sha256: 'not-used-by-the-browser',
        charts: ids.map(function(id) {
            return {
                id: id,
                category: api.CHARTS[id].category,
                filename: api.CHARTS[id].filename,
                url: 'https://attacker.invalid/raw-report.json',
                sha256: 'not-used-by-the-browser'
            };
        })
    };
}

test('a complete valid manifest updates all 22 charts with canonical versioned URLs', async () => {
    const api = loadModule();
    const ids = Object.keys(api.CHARTS);
    const harness = createHarness(api.CHARTS);
    let request;
    const result = await api.refresh(harness.document, async function(url, options) {
        request = { url, options };
        return {
            ok: true,
            status: 200,
            async json() { return manifestFor(api, ids); }
        };
    });

    assert.equal(ids.length, 22);
    assert.equal(result.state, 'updated');
    assert.equal(result.applied, 22);
    assert.equal(request.url, '/api/feedback/charts/manifest');
    assert.equal(request.options.cache, 'no-store');
    assert.equal(request.options.credentials, 'same-origin');
    assert.equal(request.options.headers.Accept, 'application/json');
    assert.equal(harness.status.dataset.state, 'updated');
    assert.match(harness.status.textContent, /aggregati da 24 sessioni/);
    assert.match(harness.status.textContent, /pubblicati il/);
    assert.match(harness.attempt.textContent, /Ultimo tentativo:/);
    assert.match(harness.published.textContent, /24 sessioni aggregate/);

    ids.forEach(function(id) {
        const expected = api.CHARTS[id];
        assert.equal(
            harness.images.get(id).getAttribute('src'),
            '/api/feedback/charts/2026-08-19_a1b2c3/'
                + expected.category + '/' + expected.filename
        );
        assert.doesNotMatch(harness.images.get(id).getAttribute('src'), /attacker|raw-report/);
    });
});

test('a partial manifest replaces only allowlisted IDs with exact Linux case', async () => {
    const api = loadModule();
    const harness = createHarness(api.CHARTS);
    const validId = 'general.performance_summary';
    const payload = manifestFor(api, [validId]);
    payload.charts.push({
        id: 'general.percentuale_domande_corrette',
        category: 'General',
        filename: 'Percentuale_Domande_Corrette.png'
    });
    payload.charts.push({
        id: '../../raw-feedback',
        category: 'general',
        filename: 'report.json'
    });

    const result = await api.refresh(harness.document, async function() {
        return { ok: true, status: 200, async json() { return payload; } };
    });

    assert.equal(result.state, 'fallback');
    assert.equal(result.applied, 1);
    assert.equal(harness.status.dataset.state, 'fallback');
    assert.match(harness.status.textContent, /1 grafici aggiornati su 22/);
    assert.equal(
        harness.images.get(validId).getAttribute('src'),
        '/api/feedback/charts/2026-08-19_a1b2c3/general/performance_summary.png'
    );
    assert.equal(
        harness.images.get('general.percentuale_domande_corrette').getAttribute('src'),
        './placeholder.svg'
    );
    assert.equal(
        harness.images.get('demographics.performance_per_demographic').getAttribute('src'),
        './placeholder.svg'
    );

    harness.images.get(validId).dispatch('error');
    assert.equal(
        harness.images.get(validId).getAttribute('src'),
        './placeholder.svg'
    );
    assert.match(harness.status.textContent, /segnaposto neutro/);
});

test('a malformed manifest leaves every neutral placeholder unchanged and reports an error', async () => {
    const api = loadModule();
    const harness = createHarness(api.CHARTS);
    const before = new Map(Array.from(harness.images, function([id, image]) {
        return [id, image.getAttribute('src')];
    }));

    const result = await api.refresh(harness.document, async function() {
        return {
            ok: true,
            status: 200,
            async json() {
                return {
                    schema_version: 1,
                    generation_id: '../latest',
                    generated_at: 'not-a-date',
                    charts: []
                };
            }
        };
    });

    assert.equal(result.state, 'invalid-manifest');
    assert.equal(result.applied, 0);
    assert.equal(harness.status.dataset.state, 'error');
    assert.match(harness.status.textContent, /Manifest dei grafici non valido/);
    before.forEach(function(source, id) {
        assert.equal(harness.images.get(id).getAttribute('src'), source);
        assert.equal(source, './placeholder.svg');
    });
});

test('missing snapshots use fallback while transport failures expose an accessible error', async () => {
    const api = loadModule();
    const missing = createHarness(api.CHARTS);
    const fallback = await api.refresh(missing.document, async function() {
        return { ok: false, status: 404 };
    });
    assert.equal(fallback.state, 'waiting');
    assert.equal(fallback.applied, 0);
    assert.equal(missing.status.dataset.state, 'waiting');
    assert.match(missing.status.textContent, /campione minimo/);
    assert.match(missing.status.textContent, /periodo di pubblicazione/);

    const failed = createHarness(api.CHARTS);
    const error = await api.refresh(failed.document, async function() {
        throw new Error('connection refused');
    });
    assert.equal(error.state, 'network-error');
    assert.equal(error.applied, 0);
    assert.equal(failed.status.dataset.state, 'error');
    assert.match(failed.status.textContent, /non raggiungibile/);
    Array.from(failed.images.values()).forEach(function(image) {
        assert.equal(image.getAttribute('src'), './placeholder.svg');
    });
});

test('session count is a required trusted integer and manifest URLs remain ignored', () => {
    const api = loadModule();
    const payload = manifestFor(api, Object.keys(api.CHARTS));
    payload.session_count = '24';
    assert.throws(() => api.parseManifest(payload), /sessioni aggregate/);
    payload.session_count = 1;
    assert.throws(() => api.parseManifest(payload), /sessioni aggregate/);
    payload.session_count = 24;
    const parsed = api.parseManifest(payload);
    assert.equal(parsed.sessionCount, 24);
    assert.equal(parsed.charts.length, 22);
    parsed.charts.forEach(chart => assert.doesNotMatch(chart.assetUrl, /attacker|raw-report/));
});

test('refresh interval is read from the same-origin response and clamped conservatively', async () => {
    const api = loadModule();
    const harness = createHarness(api.CHARTS);
    const result = await api.refresh(harness.document, async function() {
        return {
            ok: false,
            status: 404,
            headers: { get() { return '5'; } }
        };
    });
    assert.equal(result.refreshSeconds, 30);
    assert.equal(api.normalizeRefreshSeconds(300), 300);
    assert.equal(api.normalizeRefreshSeconds(999999), 86400);
    assert.equal(api.normalizeRefreshSeconds('invalid'), 300);
});

test('controller keeps one timer, pauses while hidden and cleans listeners on pagehide', async () => {
    const api = loadModule();
    const harness = createHarness(api.CHARTS);
    const timers = new Map();
    const globalListeners = new Map();
    let nextTimer = 1;
    let requests = 0;
    const globalRef = {
        setTimeout(callback, delay) {
            const id = nextTimer++;
            timers.set(id, { callback, delay });
            return id;
        },
        clearTimeout(id) { timers.delete(id); },
        addEventListener(type, listener) { globalListeners.set(type, listener); },
        removeEventListener(type, listener) {
            if (globalListeners.get(type) === listener) globalListeners.delete(type);
        }
    };
    const fetchImpl = async function() {
        requests += 1;
        return {
            ok: false,
            status: 404,
            headers: { get() { return '60'; } }
        };
    };

    const controller = api.createController(globalRef, harness.document, fetchImpl);
    await controller.refresh();
    assert.equal(requests, 1, 'il refresh manuale concorrente riusa la richiesta iniziale');
    assert.equal(timers.size, 1);
    assert.equal(Array.from(timers.values())[0].delay, 60000);

    harness.document.visibilityState = 'hidden';
    harness.document.dispatch('visibilitychange');
    assert.equal(timers.size, 0, 'nessun polling con pagina nascosta');

    harness.document.visibilityState = 'visible';
    harness.document.dispatch('visibilitychange');
    await controller.refresh();
    assert.equal(requests, 2);
    assert.equal(timers.size, 1, 'il ritorno visibile crea un solo timer');

    harness.button.dispatch('click');
    await controller.refresh();
    assert.equal(requests, 3);
    assert.equal(timers.size, 1, 'il retry manuale sostituisce il timer precedente');

    globalListeners.get('pagehide')();
    assert.equal(timers.size, 0);
    assert.equal(globalListeners.has('pagehide'), false);
    assert.equal(harness.listeners.has('document:visibilitychange'), false);
    assert.equal(harness.listeners.has('button:click'), false);
});

test('the Web repository contains no historical chart PNG and every card starts from the neutral placeholder', () => {
    const html = fs.readFileSync('grafici/grafici.html', 'utf8');
    const entries = fs.readdirSync('grafici', { withFileTypes: true });
    assert.deepEqual(entries.map(entry => entry.name).sort(), ['grafici.html', 'placeholder.svg']);
    assert.equal((html.match(/src="\.\/placeholder\.svg"/g) || []).length, 22);
    assert.doesNotMatch(html, /src="\.\/[^"]+\.png"/i);

    const dockerfile = fs.readFileSync('Dockerfile', 'utf8');
    assert.match(dockerfile, /COPY --from=build \/app\/out\/ \/usr\/share\/nginx\/html\//);
    const prepare = fs.readFileSync('tools/prepare-public.mjs', 'utf8');
    assert.match(prepare, /cp\(resolve\(root, 'grafici\/placeholder\.svg'\)/);
    assert.doesNotMatch(prepare, /cp\(resolve\(root, 'grafici'\)/);
    const dockerignore = fs.readFileSync('.dockerignore', 'utf8');
    assert.match(dockerignore, /^!grafici\/placeholder\.svg$/m);
    assert.doesNotMatch(dockerignore, /^!grafici\/\*\*$/m);
    assert.doesNotMatch(dockerfile, /^COPY grafici \/usr\/share\/nginx\/html\/grafici$/m);
});
