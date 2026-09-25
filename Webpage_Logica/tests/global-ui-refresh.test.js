const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

function read(file) {
    return fs.readFileSync(file, 'utf8').replace(/\r\n?/g, '\n');
}

const base = read('styles/base.css');
const components = read('styles/components.css');
const app = read('scripts/app.js');
const home = read('index.html');

function cssBlock(source, selector) {
    const start = source.indexOf(selector);
    assert.notEqual(start, -1, `Selettore non trovato: ${selector}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let index = open; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(open + 1, index);
    }
    throw new Error(`Blocco CSS non chiuso: ${selector}`);
}

test('global layout retains the visual spacing and typography of static cache v5', () => {
    const root = cssBlock(base, 'html {');
    const page = cssBlock(base, 'body{');
    assert.match(root, /min-height:\s*100%/);
    assert.match(root, /margin:\s*0/);
    assert.match(root, /padding:\s*0/);
    assert.match(page, /min-height:\s*100%/);
    assert.match(page, /margin:\s*15px/);
    assert.match(page, /padding:\s*4vh 18%/);
    assert.match(page, /text-align:\s*justify/);
    assert.match(page, /overflow-wrap:\s*anywhere/);
    assert.match(page, /font-family:\s*"JetBrains Mono"/);
    assert.doesNotMatch(base, /--font-sans:/);

    const emphasis = cssBlock(base, 'b,\nstrong{');
    assert.match(emphasis, /display:\s*block/);
    assert.match(emphasis, /text-align:\s*center/);
    assert.match(emphasis, /color:\s*var\(--box-title\)/);
});

test('mobile typography wraps within the viewport without duplicating page spacing', () => {
    const mobileStart = components.indexOf('@media (max-width: 700px)');
    const mobile = components.slice(mobileStart);
    assert.ok(mobileStart >= 0);
    assert.match(mobile, /body\s*\{[\s\S]*?margin:\s*0;[\s\S]*?text-align:\s*left/);
    assert.match(mobile, /h1\s*\{[\s\S]*?font-size:\s*1\.3em/);
    assert.match(mobile, /h2,[\s\S]*?h3\s*\{[\s\S]*?font-size:\s*1em/);
    assert.match(mobile, /legend\s*\{[\s\S]*?overflow-wrap:\s*anywhere/);
    assert.match(mobile, /#main-content\s*\{[\s\S]*?padding-top:\s*52px/);
});

test('global palette and common surfaces match the v5 visual baseline', () => {
    const night = cssBlock(base, ':root{');
    const day = cssBlock(base, 'html.day-mode,');
    assert.match(night, /--bg:\s*#222226/);
    assert.match(night, /--fg:\s*#ffffff/);
    assert.match(night, /--box-bg:\s*#1d1d20/);
    assert.match(day, /--bg:\s*#ffffff/);
    assert.match(day, /--fg:\s*#222222/);
    assert.match(day, /--box-bg:\s*#fafafa/);

    const box = cssBlock(components, '.rounded-box {');
    assert.match(box, /padding:\s*20px/);
    assert.match(box, /border:\s*2px solid var\(--box-border\)/);
    assert.match(box, /border-radius:\s*8px/);
});

test('settings and navigation retain the v5 placement', () => {
    const settings = cssBlock(components, '.settings-trigger {');
    assert.match(settings, /position:\s*fixed/);
    assert.match(settings, /top:\s*16px/);
    assert.match(settings, /right:\s*16px/);
    assert.match(settings, /min-width:\s*56px/);

    const modal = cssBlock(components, '.settings-modal {');
    assert.match(modal, /max-height:\s*calc\(100dvh - 32px\)/);
    assert.match(modal, /overflow-y:\s*auto/);
    assert.match(cssBlock(components, '.settings-actions {'), /flex-wrap:\s*wrap/);

    const navigation = cssBlock(components, '.lesson-nav {');
    assert.match(navigation, /position:\s*relative/);
    assert.match(navigation, /display:\s*flex/);
    assert.match(navigation, /flex-wrap:\s*wrap/);
    assert.match(cssBlock(components, '.lesson-nav-btn {'), /position:\s*static/);
});

test('home and global bootstrap retain the v5 visual structure', () => {
    assert.match(home, /<title>Indice<\/title>/);
    assert.match(home, /<h1>Indice<\/h1>/);
    assert.match(home, /<div class="index-boxes">/);
    assert.match(home, /class="rounded-box index-actions-box"/);
    assert.match(home, /class="index-corner index-corner-left"/);
    assert.doesNotMatch(home, /home-hero|home-page|site-footer/);

    assert.match(app, /function ensureAccessibilityScaffold\(\)/);
    assert.doesNotMatch(app, /createElement\('header'\)|createElement\('footer'\)|siteUtilityActions/);
});

test('removed global controls leave no visual rules or bootstrap hooks', () => {
    assert.doesNotMatch(components, /\.global-search-|\.connection-status|\.pwa-update-button/);
    assert.doesNotMatch(app, /global-search|connectionStatus|pwaUpdateButton|navigator\.onLine/);
    assert.doesNotMatch(app, /serviceWorker\.register\s*\(/);
    assert.match(app, /getRegistrations\(\)/);
    assert.match(app, /name\.startsWith\('testlogica-'\)/);
});
