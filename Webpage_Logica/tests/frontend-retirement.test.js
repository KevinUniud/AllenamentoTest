const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const WEB_ROOT = path.resolve(__dirname, '..');
const WORKER_SOURCE = fs.readFileSync(path.join(WEB_ROOT, 'service-worker.js'), 'utf8');

function walkFiles(directory) {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap(function(entry) {
        // Legacy snapshots retain their original relative paths, outside public assets.
        if (entry.isDirectory() && ['.git', 'node_modules', '.next', 'out', 'public', '.build', 'test-results', 'playwright-report', 'old_pages'].includes(entry.name)) return [];
        const target = path.join(directory, entry.name);
        return entry.isDirectory() ? walkFiles(target) : [target];
    });
}

function assertExactCase(relativePath, label) {
    let current = WEB_ROOT;
    relativePath.split('/').filter(Boolean).forEach(function(segment) {
        const names = fs.readdirSync(current);
        assert.ok(names.includes(segment), `${label}: case errato per ${segment}`);
        current = path.join(current, segment);
    });
    assert.ok(fs.existsSync(current), `${label}: risorsa assente`);
}

function dispatchExtendable(listener) {
    let pending;
    listener({
        waitUntil(promise) { pending = promise; }
    });
    assert.ok(pending, 'waitUntil non invocato');
    return pending;
}

function createRetirementHarness(cacheNames) {
    const listeners = {};
    const calls = { claimed: 0, deleted: [], skipWaiting: 0, unregistered: 0 };
    const context = {
        caches: {
            async keys() { return cacheNames; },
            async delete(name) { calls.deleted.push(name); return true; }
        },
        self: {
            addEventListener(type, listener) { listeners[type] = listener; },
            skipWaiting() { calls.skipWaiting += 1; return Promise.resolve(); },
            clients: {
                claim() { calls.claimed += 1; return Promise.resolve(); }
            },
            registration: {
                unregister() { calls.unregistered += 1; return Promise.resolve(true); }
            }
        }
    };
    vm.runInNewContext(WORKER_SOURCE, context, { filename: 'service-worker.js' });
    return { calls, listeners };
}

test('search and installable/offline assets are absent from the public frontend', () => {
    [
        'manifest.webmanifest',
        'offline.html',
        'search-index.json',
        'scripts/global-search.js',
        'tools/build-search-index.mjs',
        'tools/check-search-index.mjs',
        'icons/app-icon.svg',
        'icons'
    ].forEach(function(relativePath) {
        assert.equal(fs.existsSync(path.join(WEB_ROOT, relativePath)), false, relativePath);
    });

    const html = walkFiles(WEB_ROOT)
        .filter(function(file) { return file.endsWith('.html'); })
        .map(function(file) { return fs.readFileSync(file, 'utf8'); })
        .join('\n');
    assert.doesNotMatch(html, /rel\s*=\s*["']manifest["']/i);
    assert.doesNotMatch(html, /manifest\.webmanifest|offline\.html|search-index\.json|global-search\.js/i);
});

test('all remaining local HTML, CSS and dynamic image references use exact Linux case', () => {
    const origin = new URL('https://testlogica.invalid/');
    const htmlFiles = walkFiles(WEB_ROOT).filter(function(file) { return file.endsWith('.html'); });
    htmlFiles.forEach(function(file) {
        const source = fs.readFileSync(file, 'utf8');
        const pageUrl = new URL(path.relative(WEB_ROOT, file).split(path.sep).join('/'), origin);
        for (const match of source.matchAll(/\b(?:src|href)\s*=\s*(["'])(.*?)\1/gi)) {
            const reference = match[2];
            if (!reference || reference.startsWith('#')) continue;
            const url = new URL(reference, pageUrl);
            if (url.origin !== origin.origin) continue;
            assertExactCase(decodeURIComponent(url.pathname.slice(1)), `${path.relative(WEB_ROOT, file)} -> ${reference}`);
        }
    });

    const quizCss = fs.readFileSync(path.join(WEB_ROOT, 'styles/quiz.css'), 'utf8');
    for (const match of quizCss.matchAll(/@import\s+(?:url\()?\s*(["']?)([^"')\s;]+)\1/gi)) {
        const url = new URL(match[2], new URL('styles/quiz.css', origin));
        assertExactCase(url.pathname.slice(1), `styles/quiz.css -> ${match[2]}`);
    }

    const quiz = fs.readFileSync(path.join(WEB_ROOT, 'scripts/quiz.js'), 'utf8');
    for (const match of quiz.matchAll(/\b(?:day|night):\s*'([^']+\.png)'/g)) {
        assertExactCase(`Immagini/${match[1]}`, `scripts/quiz.js -> ${match[1]}`);
    }
});

test('the current bootstrap removes only legacy TestLogica registrations and caches', () => {
    const app = fs.readFileSync(path.join(WEB_ROOT, 'scripts/app.js'), 'utf8');
    assert.match(app, /getRegistrations\(\)/);
    assert.match(app, /registration\.scope === legacyScope/);
    assert.match(app, /registration\.unregister\(\)/);
    assert.match(app, /name\.startsWith\('testlogica-'\)/);
    assert.doesNotMatch(app, /serviceWorker\.register\s*\(/);
    assert.doesNotMatch(app, /navigator\.onLine|global-search|connectionStatus|pwaUpdateButton/);
    assert.doesNotMatch(app, /localStorage\.(?:clear|removeItem)|indexedDB\.deleteDatabase/);
});

test('the retirement worker claims clients, removes owned caches and unregisters without fetch handling', async () => {
    const harness = createRetirementHarness([
        'testlogica-static-v9',
        'testlogica-runtime-v9',
        'unrelated-cache',
        'testlogica-static-v3'
    ]);

    assert.deepEqual(Object.keys(harness.listeners).sort(), ['activate', 'install']);
    await dispatchExtendable(harness.listeners.install);
    await dispatchExtendable(harness.listeners.activate);

    assert.equal(harness.calls.skipWaiting, 1);
    assert.equal(harness.calls.claimed, 1);
    assert.equal(harness.calls.unregistered, 1);
    assert.deepEqual(harness.calls.deleted.sort(), [
        'testlogica-runtime-v9',
        'testlogica-static-v3',
        'testlogica-static-v9'
    ]);
    assert.doesNotMatch(WORKER_SOURCE, /respondWith|addEventListener\(['"]fetch|caches\.open|cache\.put/);
});

test('build and Nginx expose only the no-store retirement endpoint', () => {
    const dockerfile = fs.readFileSync(path.join(WEB_ROOT, 'Dockerfile'), 'utf8');
    assert.match(dockerfile, /COPY --from=build \/app\/out\/ \/usr\/share\/nginx\/html\//);
    const preparePublic = fs.readFileSync(path.join(WEB_ROOT, 'tools/prepare-public.mjs'), 'utf8');
    assert.match(preparePublic, /'service-worker\.js'/);
    assert.match(dockerfile, /API_UPSTREAM=http:\/\/host\.docker\.internal:5000/);
    assert.doesNotMatch(dockerfile, /manifest\.webmanifest|offline\.html|search-index\.json|COPY icons/);

    const nginx = fs.readFileSync(path.join(WEB_ROOT, 'nginx/default.conf.template'), 'utf8');
    const retirement = nginx.match(/location = \/service-worker\.js \{([\s\S]*?)\n\s*\}/);
    assert.ok(retirement, 'endpoint di dismissione service worker assente');
    assert.match(retirement[1], /default_type application\/javascript/);
    assert.match(retirement[1], /Cache-Control "no-store"/);
    assert.doesNotMatch(nginx, /location = \/manifest\.webmanifest/);

    const webHealth = nginx.match(/location = \/web-health \{([\s\S]*?)\n\s*\}/);
    assert.ok(webHealth, 'healthcheck locale del repository Web assente');
    assert.match(webHealth[1], /return 200 "ok\\n"/);

    const compose = fs.readFileSync(path.join(WEB_ROOT, 'docker-compose.yml'), 'utf8');
    assert.match(compose, /\$\{WEB_PORT:-12345\}:80/);
    assert.match(compose, /http:\/\/127\.0\.0\.1\/web-health/);
    assert.doesNotMatch(compose, /\bcontainer_name\s*:/);
    assert.match(compose, /^x-feedback-runtime: &feedback-runtime/m);
    const feedbackRuntime = compose.match(/^x-feedback-runtime: &feedback-runtime\n([\s\S]*?)\nservices:/m);
    assert.ok(feedbackRuntime, 'configurazione condivisa feedback assente');
    assert.match(feedbackRuntime[1], /networks:\n\s+- feedback-internal/);
    assert.doesNotMatch(feedbackRuntime[1], /\n\s+ports:/);
    assert.match(compose, /context: \.\.\/feedback/);
    assert.match(compose, /user: "\$\{FEEDBACK_UID:-1000\}:\$\{FEEDBACK_GID:-1000\}"/);
    assert.match(compose, /source: \$\{FEEDBACK_DATA_DIR:-\.\.\/feedback\/data\}/);
    assert.match(compose, /create_host_path: false/);
    assert.match(compose, /selinux: z/);
    assert.match(compose, /FEEDBACK_MAX_RECEIPTS: \$\{FEEDBACK_MAX_RECEIPTS:-100000\}/);
    assert.match(compose, /FEEDBACK_MAX_STORAGE_BYTES: \$\{FEEDBACK_MAX_STORAGE_BYTES:-1073741824\}/);
    assert.match(compose, /FEEDBACK_MIN_FREE_BYTES: \$\{FEEDBACK_MIN_FREE_BYTES:-67108864\}/);
    assert.match(compose, /FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS: \$\{FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS:-900\}/);
    const workerService = compose.match(/\n  feedback-worker:\n([\s\S]*?)\n  feedback:/);
    assert.ok(workerService, 'worker feedback separato non definito nel Compose Web');
    assert.match(workerService[1], /feedback_service\.worker/);
    assert.match(workerService[1], /--check/);
    assert.doesNotMatch(workerService[1], /\n\s+ports:/);
    const feedbackService = compose.match(/\n  feedback:\n([\s\S]*?)\n  webpage-logica:/);
    assert.ok(feedbackService, 'servizio feedback fratello non definito nel Compose Web');
    assert.match(feedbackService[1], /feedback-worker:/);
    assert.match(feedbackService[1], /condition: service_healthy/);
    assert.match(feedbackService[1], /127\.0\.0\.1:5555\/ready/);
    assert.doesNotMatch(feedbackService[1], /\n\s+ports:/);
    const webpageService = compose.match(/\n  webpage-logica:\n([\s\S]*?)\nnetworks:/);
    assert.ok(webpageService, 'servizio Web non definito nel Compose');
    assert.match(webpageService[1], /feedback:\n\s+condition: service_healthy/);
    assert.match(webpageService[1], /API_UPSTREAM: \$\{API_UPSTREAM:-http:\/\/host\.docker\.internal:5000\}/);
    assert.match(compose, /feedback-internal:\n\s+internal: true/);
    assert.match(compose, /FEEDBACK_UPSTREAM: http:\/\/feedback:5555/);
    assert.match(compose, /FEEDBACK_WORKER_MODE: external/);
    assert.doesNotMatch(compose, /^volumes:/m);

    const envExample = fs.readFileSync(path.join(WEB_ROOT, '.env.example'), 'utf8');
    [
        'FEEDBACK_UID=1000',
        'FEEDBACK_GID=1000',
        'FEEDBACK_DATA_DIR=../feedback/data',
        'FEEDBACK_WORKER_HEARTBEAT_SECONDS=15',
        'FEEDBACK_WORKER_STALE_SECONDS=60',
        'FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS=900'
    ].forEach(entry => assert.match(envExample, new RegExp('^' + entry.replaceAll('.', '\\.') + '$', 'm')));

    const pkg = JSON.parse(fs.readFileSync(path.join(WEB_ROOT, 'package.json'), 'utf8'));
    assert.equal(pkg.scripts.verify, 'npm run check && npm test');
    assert.equal(Object.hasOwn(pkg.scripts, 'search:index'), false);
    assert.equal(Object.hasOwn(pkg.scripts, 'search:check'), false);
});

test('feedback submission is proxied unchanged to its dedicated upstream without client IP headers', () => {
    const nginx = fs.readFileSync(path.join(WEB_ROOT, 'nginx/default.conf.template'), 'utf8');
    const feedback = nginx.match(/location = \/api\/revisione \{([\s\S]*?)\n\s*\}/);
    assert.ok(feedback, 'proxy esatto di /api/revisione assente');
    assert.match(feedback[1], /access_log off;/);
    assert.match(feedback[1], /proxy_pass \$\{FEEDBACK_UPSTREAM\}\/api\/revisione;/);
    assert.match(feedback[1], /proxy_set_header X-Real-IP "";/);
    assert.match(feedback[1], /proxy_set_header X-Forwarded-For "";/);
    assert.match(feedback[1], /proxy_set_header Idempotency-Key \$http_idempotency_key;/);
    assert.match(feedback[1], /client_max_body_size 2m;/);
    assert.match(feedback[1], /proxy_http_version 1\.1;/);
    assert.match(feedback[1], /proxy_request_buffering off;/);
    assert.match(feedback[1], /proxy_connect_timeout 5s;/);
    assert.match(feedback[1], /proxy_read_timeout 30s;/);
    assert.match(feedback[1], /proxy_send_timeout 30s;/);
    assert.doesNotMatch(feedback[1], /proxy_set_body|proxy_pass_request_body\s+off|upload-json/);
    assert.doesNotMatch(feedback[1], /API_UPSTREAM/);
    assert.doesNotMatch(feedback[1], /limit_req/);

    const edge = fs.readFileSync(path.join(WEB_ROOT, 'deploy/nginx-edge.example.conf'), 'utf8');
    assert.match(edge, /limit_req_zone \$binary_remote_addr zone=testlogica_feedback_per_client:10m rate=60r\/m;/);
    assert.match(edge, /location = \/api\/revisione \{[\s\S]*limit_req zone=testlogica_feedback_per_client burst=60 nodelay;/);
    assert.match(edge, /Strict-Transport-Security "max-age=31536000; includeSubDomains" always;/);

    const configuration = [
        nginx,
        fs.readFileSync(path.join(WEB_ROOT, 'Dockerfile'), 'utf8'),
        fs.readFileSync(path.join(WEB_ROOT, 'docker-compose.yml'), 'utf8'),
        fs.readFileSync(path.join(WEB_ROOT, '.env.example'), 'utf8')
    ].join('\n');
    assert.doesNotMatch(configuration, /REVIEW_UPSTREAM|\/upload-json/);
    assert.match(configuration, /FEEDBACK_UPSTREAM/);
    assert.match(configuration, /http:\/\/feedback:5555/);
    assert.doesNotMatch(configuration, /host\.docker\.internal:5555/);
});

test('versioned feedback charts bypass the static image regex while generic API calls stay on the logic API', () => {
    const nginx = fs.readFileSync(path.join(WEB_ROOT, 'nginx/default.conf.template'), 'utf8');
    const charts = nginx.match(/location \^~ \/api\/feedback\/charts\/ \{([\s\S]*?)\n\s*\}/);
    assert.ok(charts, 'proxy ^~ dei grafici feedback assente');
    assert.match(charts[1], /access_log off;/);
    assert.match(charts[1], /proxy_pass \$\{FEEDBACK_UPSTREAM\}\/api\/feedback\/charts\/;/);
    assert.match(charts[1], /proxy_set_header X-Real-IP "";/);
    assert.match(charts[1], /proxy_set_header X-Forwarded-For "";/);
    assert.match(charts[1], /X-Feedback-Refresh-Seconds "\$\{FEEDBACK_CHARTS_REFRESH_SECONDS\}"/);
    assert.doesNotMatch(charts[1], /try_files|API_UPSTREAM|limit_req|proxy_request_buffering/);

    const staticImages = nginx.match(/location ~\* \\\.\(\?:png\|jpg\|jpeg\|gif\|ico\|svg\|webp\)\$ \{([\s\S]*?)\n\s*\}/);
    assert.ok(staticImages, 'location regex degli asset statici assente');
    assert.match(staticImages[1], /try_files \$uri =404;/);

    const genericApi = nginx.match(/location \/api\/ \{([\s\S]*?)\n\s*\}/);
    assert.ok(genericApi, 'proxy generico API assente');
    assert.match(genericApi[1], /proxy_pass \$\{API_UPSTREAM\}\/api\/;/);
    assert.match(genericApi[1], /proxy_read_timeout \$\{API_PROXY_TIMEOUT_SECONDS\}s;/);
    assert.match(genericApi[1], /proxy_send_timeout \$\{API_PROXY_TIMEOUT_SECONDS\}s;/);
    assert.doesNotMatch(genericApi[1], /FEEDBACK_UPSTREAM|limit_req|proxy_request_buffering/);
});

test('feedback copy does not promise absolute anonymity', () => {
    const read = function(relativePath) {
        return fs.readFileSync(path.join(WEB_ROOT, relativePath), 'utf8');
    };
    const copy = [read('README.md'), read('privacy.html'), read('scripts/settings.js')].join('\n');
    assert.doesNotMatch(copy, /feedback anonimo/i);
    assert.match(read('scripts/settings.js'), /feedback senza nome o account/);
    assert.match(read('privacy.html'), /non permettono di garantire l'anonimato assoluto/);
    assert.match(read('privacy.html'), /non incorpora grafici storici/);
    assert.match(read('privacy.html'), /segnaposto SVG privo di dati/);
});
