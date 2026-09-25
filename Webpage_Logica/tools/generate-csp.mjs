import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'parse5';

const MAP_FILENAME = 'csp-map.conf';
const MANIFEST_FILENAME = 'csp-manifest.json';

export function contentHash(source) {
    return 'sha256-' + createHash('sha256').update(source, 'utf8').digest('base64');
}

function fileHash(source) {
    return createHash('sha256').update(source, 'utf8').digest('hex');
}

function normalizeFile(file) {
    if (typeof file !== 'string' || !file || /[\x00-\x1f\x7f\\]/.test(file)
        || path.posix.isAbsolute(file) || file.split('/').some(segment => !segment || segment === '.' || segment === '..')
        || !file.endsWith('.html') || /[?#]/.test(file)) {
        throw new Error(`Percorso HTML non valido: ${String(file)}`);
    }
    return file;
}

/** URI aliases used by Nginx before and after its index/internal redirects. */
export function routesForFile(file) {
    normalizeFile(file);
    if (file === 'index.html') return ['/', '/index.html'];
    if (file === '404.html') return ['/404.html'];
    if (file.endsWith('/index.html')) {
        const directory = '/' + file.slice(0, -'/index.html'.length);
        return [directory, directory + '/', '/' + file];
    }
    const extensionless = '/' + file.slice(0, -'.html'.length);
    return extensionless.endsWith('/') ? ['/' + file] : [extensionless, '/' + file];
}

function assertLocalScript(source, file) {
    // Origin is deliberately synthetic: deployment hosts are not known at build time.
    // Only relative/root-relative URLs are portable across all bundle deployments.
    const value = source.trim();
    const base = 'https://testlogica.invalid/';
    let url;
    try { url = new URL(value, base); } catch { /* Error reported below. */ }
    if (!value || !url || url.origin !== new URL(base).origin || value.startsWith('//')
        || /^[a-z][a-z0-9+.-]*:/i.test(value) || /[\\\x00-\x1f\x7f]/.test(value)) {
        throw new Error(`${file}: script esterno non locale: ${JSON.stringify(source)}`);
    }
}

function inlineSource(node, source, file) {
    const location = node.sourceCodeLocation;
    if (!location?.startTag) throw new Error(`${file}: posizione sorgente inline non disponibile`);
    return source.slice(location.startTag.endOffset, location.endTag?.startOffset ?? location.endOffset);
}

/** Hash exact inline contents; do not trim/reformat emitted Next.js scripts or styles. */
export function inspectHtml(source, file = 'index.html') {
    normalizeFile(file);
    const scriptHashes = new Set();
    const styleHashes = new Set();
    const styleAttributeHashes = new Set();
    const document = parse(source, { sourceCodeLocationInfo: true });

    function visit(node) {
        const attributes = node.attrs || [];
        for (const attribute of attributes) {
            if (/^on/i.test(attribute.name)) {
                throw new Error(`${file}: gestore di evento inline vietato: ${attribute.name}`);
            }
            if (attribute.name === 'style') {
                // parse5 decodes character references as the browser does for attributes.
                styleAttributeHashes.add(contentHash(attribute.value));
            }
        }
        if (node.tagName === 'script') {
            const sources = attributes.filter(attribute => attribute.name === 'src' || attribute.name === 'href');
            sources.forEach(attribute => assertLocalScript(attribute.value, file));
            if (!sources.length) scriptHashes.add(contentHash(inlineSource(node, source, file)));
        }
        if (node.tagName === 'style') styleHashes.add(contentHash(inlineSource(node, source, file)));
        for (const child of node.childNodes || []) visit(child);
        if (node.content) visit(node.content); // Templates also need a safe policy when instantiated.
    }
    visit(document);
    return {
        file,
        fileSha256: fileHash(source),
        routes: routesForFile(file),
        scriptHashes: Array.from(scriptHashes).sort(),
        styleHashes: Array.from(styleHashes).sort(),
        styleAttributeHashes: Array.from(styleAttributeHashes).sort(),
    };
}

function quoteNginx(value) {
    return '"' + value.replace(/[\\"$]/g, character => '\\' + character) + '"';
}

/** The leading space permits script-src 'self'$testlogica_script_hashes in headers. */
export function renderCspMaps(pages) {
    const routes = new Map();
    for (const page of pages) {
        for (const route of page.routes) {
            if (routes.has(route)) throw new Error(`Collisione URI CSP ${route}: ${routes.get(route).file} e ${page.file}`);
            routes.set(route, page);
        }
    }
    const ordered = Array.from(routes.keys()).sort();
    function render(variable, getSources) {
        const lines = [`map $uri $${variable} {`, '    default "";'];
        for (const route of ordered) {
            const sources = getSources(routes.get(route));
            const value = sources.length ? ' ' + sources.map(source => "'" + source + "'").join(' ') : '';
            lines.push(`    ${quoteNginx(route)} ${quoteNginx(value)};`);
        }
        lines.push('}');
        return lines.join('\n');
    }
    return '# Generated from the final static export. Regenerate after every build.\n'
        + render('testlogica_script_hashes', page => page.scriptHashes) + '\n\n'
        + render('testlogica_style_hashes', page => [
            ...(page.styleAttributeHashes.length ? ['unsafe-hashes'] : []),
            ...new Set([...page.styleHashes, ...page.styleAttributeHashes].sort()),
        ]) + '\n';
}

async function collectHtml(directory, prefix = '') {
    const entries = await readdir(directory, { withFileTypes: true });
    const files = [];
    for (const entry of entries) {
        const relative = prefix + entry.name;
        if (entry.isSymbolicLink()) throw new Error(`Link simbolico non supportato nell'export: ${relative}`);
        if (entry.isDirectory()) files.push(...await collectHtml(path.join(directory, entry.name), relative + '/'));
        else if (entry.isFile() && entry.name.endsWith('.html')) files.push(relative);
    }
    return files.sort();
}

async function inspectExport(outDir) {
    const files = await collectHtml(outDir);
    if (!files.length) throw new Error(`Nessun HTML da verificare in ${outDir}`);
    return Promise.all(files.map(async file => inspectHtml(await readFile(path.join(outDir, file), 'utf8'), file)));
}

/** Also catches new/removed HTML files and modified route/hash entries in a stale manifest. */
export async function verifyManifest(outDir, manifest) {
    if (!manifest || manifest.version !== 1 || manifest.algorithm !== 'sha256' || !Array.isArray(manifest.pages)) {
        throw new Error('Manifest CSP non valido o versione non supportata');
    }
    const pages = await inspectExport(outDir);
    if (JSON.stringify(pages) !== JSON.stringify(manifest.pages)) {
        throw new Error('Manifest CSP non corrisponde all’export HTML corrente. Rigenerare la CSP.');
    }
    const maps = renderCspMaps(pages);
    if (manifest.mapSha256 !== fileHash(maps)) throw new Error('Manifest CSP: checksum della mappa non valido');
    return true;
}

export async function generateCsp({ outDir = 'out', buildDir = '.build', verify = false } = {}) {
    const manifestPath = path.join(buildDir, MANIFEST_FILENAME);
    const mapPath = path.join(buildDir, MAP_FILENAME);
    if (verify) {
        const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
        await verifyManifest(outDir, manifest);
        const maps = await readFile(mapPath, 'utf8');
        if (maps !== renderCspMaps(manifest.pages)) throw new Error('La mappa CSP non corrisponde al manifest verificato');
        return manifest;
    }
    const pages = await inspectExport(outDir);
    const maps = renderCspMaps(pages); // Resolve every collision before writing any build artifact.
    const manifest = { version: 1, algorithm: 'sha256', mapSha256: fileHash(maps), pages };
    await mkdir(buildDir, { recursive: true });
    await writeFile(mapPath, maps, 'utf8');
    await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
    return manifest;
}

async function main() {
    const options = {};
    const args = process.argv.slice(2);
    for (let index = 0; index < args.length; index += 1) {
        if (args[index] === '--verify') options.verify = true;
        else if ((args[index] === '--out-dir' || args[index] === '--build-dir') && args[index + 1]) {
            options[args[index] === '--out-dir' ? 'outDir' : 'buildDir'] = args[++index];
        } else throw new Error(`Argomento non riconosciuto: ${args[index]}`);
    }
    const manifest = await generateCsp(options);
    console.log(`CSP ${options.verify ? 'verificata' : 'generata'} per ${manifest.pages.length} pagine HTML.`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    main().catch(error => {
        console.error(error.message);
        process.exitCode = 1;
    });
}
