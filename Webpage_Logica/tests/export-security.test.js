const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { mkdtemp, mkdir, readFile, writeFile, rm } = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const generator = import('../tools/generate-csp.mjs');
const hash = source => 'sha256-' + createHash('sha256').update(source, 'utf8').digest('base64');

async function exportFixture(t) {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'testlogica-csp-'));
    t.after(() => rm(directory, { recursive: true, force: true }));
    const outDir = path.join(directory, 'out');
    const buildDir = path.join(directory, '.build');
    await mkdir(path.join(outDir, 'lezioni', 'lezione-1'), { recursive: true });
    await writeFile(path.join(outDir, 'index.html'), '<script>window.home = true;</script>');
    await writeFile(path.join(outDir, 'lezioni', 'lezione-1', 'index.html'), '<style>p { color: red; }</style><script>window.lesson = 1;</script>');
    await writeFile(path.join(outDir, '404.html'), '<h1>Non trovato</h1>');
    return { outDir, buildDir };
}

test('inline CSP hashes preserve exact content, whitespace and character references', async () => {
    const { inspectHtml } = await generator;
    const script = '\n  self.__next_f.push([1,"a &amp; b"]);\n';
    const style = '\n p::before { content: "&amp;"; } \n';
    const result = inspectHtml(`<script>${script}</script><style>${style}</style><script>${script}</script>`);
    assert.deepEqual(result.scriptHashes, [hash(script)]);
    assert.deepEqual(result.styleHashes, [hash(style)]);
    assert.notEqual(result.scriptHashes[0], hash(script.trim()));
    assert.notDeepEqual(inspectHtml('<script>one()</script>').scriptHashes, inspectHtml('<script>two()</script>').scriptHashes);
});

test('inline event handlers are rejected on elements, external scripts and templates', async () => {
    const { inspectHtml } = await generator;
    for (const html of [
        '<body onload="start()">',
        '<script src="/app.js" onerror="recover()"></script>',
        '<template><button ONCLICK="run()">Avvia</button></template>',
        '<svg><image onload="run()" /></svg>',
    ]) assert.throws(() => inspectHtml(html), /gestore di evento inline vietato/);
});

test('only origin-relative or relative external scripts are allowed', async () => {
    const { inspectHtml } = await generator;
    for (const source of ['/scripts/app.js', './app.js?v=1', '../app.js', '_next/static/app.js']) {
        assert.deepEqual(inspectHtml(`<script src="${source}"></script>`).scriptHashes, []);
    }
    for (const source of [
        'https://cdn.example/app.js', 'http://cdn.example/app.js', '//cdn.example/app.js',
        'data:text/javascript,alert(1)', 'javascript:alert(1)', '\\\\cdn.example/app.js', '',
        '&#x68;ttps://cdn.example/app.js', 'https://testlogica.invalid/app.js',
    ]) assert.throws(() => inspectHtml(`<script src="${source}"></script>`), /script esterno non locale/);
    assert.throws(() => inspectHtml('<svg><script href="https://cdn.example/app.js"></script></svg>'), /non locale/);
});

test('style attributes use decoded exact hashes and unsafe-hashes only in the style map', async () => {
    const { inspectHtml, renderCspMaps } = await generator;
    const page = inspectHtml('<p style="content: &quot;a&amp;b&quot;; color: red;">Test</p><style>p{margin:0}</style>');
    assert.deepEqual(page.styleAttributeHashes, [hash('content: "a&b"; color: red;')]);
    assert.deepEqual(page.styleHashes, [hash('p{margin:0}')]);
    const maps = renderCspMaps([page]);
    const [scripts, styles] = maps.split('map $uri $testlogica_style_hashes');
    assert.doesNotMatch(scripts, /unsafe-hashes/);
    assert.match(styles, /'unsafe-hashes'/);
    assert.ok(styles.includes("'" + page.styleAttributeHashes[0] + "'"));
    assert.ok(styles.includes("'" + page.styleHashes[0] + "'"));
    assert.doesNotMatch(maps, /unsafe-inline|unsafe-eval/);
    assert.doesNotMatch(renderCspMaps([inspectHtml('<style>p{margin:0}</style>')]), /unsafe-hashes/);
});

test('root, nested pages, 404 and individual HTML files have explicit route aliases', async () => {
    const { routesForFile } = await generator;
    assert.deepEqual(routesForFile('index.html'), ['/', '/index.html']);
    assert.deepEqual(routesForFile('lezioni/lezione-1/index.html'), [
        '/lezioni/lezione-1', '/lezioni/lezione-1/', '/lezioni/lezione-1/index.html',
    ]);
    assert.deepEqual(routesForFile('404.html'), ['/404.html']);
    assert.deepEqual(routesForFile('privacy.html'), ['/privacy', '/privacy.html']);
    assert.deepEqual(routesForFile('.html'), ['/.html']);
    for (const file of ['../index.html', '/index.html', 'folder/../index.html', 'foo\\index.html', 'foo?bar.html']) {
        assert.throws(() => routesForFile(file), /Percorso HTML non valido/);
    }
});

test('maps isolate page hashes, preserve the leading separator and reject collisions', async () => {
    const { inspectHtml, renderCspMaps } = await generator;
    const home = inspectHtml('<script>home()</script>');
    const lesson = inspectHtml('<script>lesson()</script>', 'lezioni/lezione-1/index.html');
    const maps = renderCspMaps([home, lesson]);
    assert.ok(maps.includes(`"/" " '${home.scriptHashes[0]}'";`));
    const lessonLine = maps.split('\n').find(line => line.includes('"/lezioni/lezione-1/"'));
    assert.ok(lessonLine.includes(lesson.scriptHashes[0]));
    assert.ok(!lessonLine.includes(home.scriptHashes[0]));
    assert.match(maps, /default "";/);
    assert.throws(() => renderCspMaps([
        inspectHtml('', 'foo.html'), inspectHtml('', 'foo/index.html'),
    ]), /Collisione URI CSP \/foo/);
});

test('the export manifest and generated map are reproducible and verify the complete HTML set', async t => {
    const { generateCsp, verifyManifest } = await generator;
    const options = await exportFixture(t);
    const manifest = await generateCsp(options);
    assert.equal(manifest.pages.length, 3);
    assert.equal(manifest.pages.find(page => page.file === 'index.html').fileSha256,
        createHash('sha256').update('<script>window.home = true;</script>').digest('hex'));
    assert.equal(await verifyManifest(options.outDir, manifest), true);
    assert.deepEqual(await generateCsp({ ...options, verify: true }), manifest);
    const original = await readFile(path.join(options.buildDir, 'csp-manifest.json'), 'utf8');
    await generateCsp(options);
    assert.equal(await readFile(path.join(options.buildDir, 'csp-manifest.json'), 'utf8'), original);

    await writeFile(path.join(options.outDir, 'new.html'), '<p>Nuovo contenuto</p>');
    await assert.rejects(verifyManifest(options.outDir, manifest), /non corrisponde/);
});

test('verification detects edited HTML, including changes outside inline scripts', async t => {
    const { generateCsp, verifyManifest } = await generator;
    const options = await exportFixture(t);
    const manifest = await generateCsp(options);
    const filename = path.join(options.outDir, 'index.html');
    await writeFile(filename, '<script>window.home = false;</script>');
    await assert.rejects(verifyManifest(options.outDir, manifest), /non corrisponde/);
    await writeFile(filename, '<h1>Pagina modificata</h1><script>window.home = true;</script>');
    await assert.rejects(verifyManifest(options.outDir, manifest), /non corrisponde/);
});

test('verification rejects removed HTML and a tampered generated map', async t => {
    const { generateCsp, verifyManifest } = await generator;
    const options = await exportFixture(t);
    const manifest = await generateCsp(options);
    const mapPath = path.join(options.buildDir, 'csp-map.conf');
    await writeFile(mapPath, 'map $uri $testlogica_script_hashes { default " unsafe-inline"; }');
    await assert.rejects(generateCsp({ ...options, verify: true }), /mappa CSP non corrisponde/);
    await rm(path.join(options.outDir, '404.html'));
    await assert.rejects(verifyManifest(options.outDir, manifest), /non corrisponde/);
});
