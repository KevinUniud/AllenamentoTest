import { readFileSync } from 'node:fs';
import path from 'node:path';
import { parse, serialize } from 'parse5';

export const PAGE_FILES = Object.freeze([
  'index.html', 'privacy.html',
  ...Array.from({ length: 6 }, (_, index) => `lezioni/lezione-${index + 1}.html`),
  ...['index', 'Conseguenza', 'Equivalenza', 'Esiste', 'Formula_vera', 'Implica', 'O_logico', 'Per_Ogni']
    .map(name => `Errori_comuni/${name}.html`),
  'esercizi/esercitazione.html', 'strumenti/sandbox.html', 'progressi/index.html',
  'ripasso/errori.html', 'grafici/grafici.html',
]);

const origin = 'https://testlogica.invalid';
const sharedScripts = new Set([
  '/scripts/settings-preferences.js', '/scripts/app-events.js', '/scripts/data-contracts.js',
  '/scripts/privacy-controls.js', '/scripts/app-storage.js', '/scripts/settings.js',
  '/scripts/index-progress.js',
]);

export function routeForFile(file) {
  return '/' + file.replace(/(?:^|\/)index\.html$/, '').replace(/\.html$/, '').replace(/\/$/, '')
    + (file === 'index.html' ? '' : '/');
}

export const PAGE_ROUTES = Object.freeze(PAGE_FILES.map(file => ({ file, route: routeForFile(file) })));

export function canonicalUrl(value, file) {
  if (!value || value.startsWith('#') || /^(?:data:|blob:|mailto:|tel:)/i.test(value)) return value;
  const url = new URL(value, `${origin}/${file}`);
  if (url.origin !== origin) return value;
  const entry = PAGE_ROUTES.find(page => '/' + page.file === url.pathname);
  return (entry?.route || url.pathname) + url.search + url.hash;
}

export function findPage(route) {
  const normalized = '/' + String(route).replace(/^\/+|\/+$/g, '');
  return PAGE_ROUTES.find(page => page.route.replace(/\/$/, '') === normalized.replace(/\/$/, '')
    || '/' + page.file === normalized);
}

function child(node, tagName) {
  return node.childNodes?.find(item => item.tagName === tagName);
}

function content(node) {
  return node?.childNodes?.map(item => item.value || content(item)).join('') || '';
}

export function readPage(file, root = process.cwd()) {
  if (!PAGE_FILES.includes(file)) throw new Error('Pagina non registrata: ' + file);
  const document = parse(readFileSync(path.join(root, file), 'utf8'));
  const html = child(document, 'html');
  const head = child(html, 'head');
  const body = child(html, 'body');
  const title = content(child(head, 'title')) || 'TestLogica';
  const description = head.childNodes.find(node => node.tagName === 'meta'
    && node.attrs.some(attr => attr.name === 'name' && attr.value === 'description'))
    ?.attrs.find(attr => attr.name === 'content')?.value || 'Lezioni ed esercizi di logica.';
  const styles = head.childNodes.filter(node => node.tagName === 'link'
    && node.attrs.some(attr => attr.name === 'rel' && attr.value === 'stylesheet'))
    .map(node => canonicalUrl(node.attrs.find(attr => attr.name === 'href').value, file));
  const scripts = [];
  let hasMain = false;

  function clean(node) {
    if (node.tagName === 'main') hasMain = true;
    for (const attribute of node.attrs || []) {
      if (/^on/i.test(attribute.name) || attribute.name === 'style') {
        throw new Error(`Attributo inline non autorizzato: ${file}: ${attribute.name}`);
      }
      if (['href', 'src', 'poster', 'action'].includes(attribute.name)) {
        attribute.value = canonicalUrl(attribute.value, file);
      }
    }
    node.childNodes = (node.childNodes || []).filter(item => {
      if (item.tagName !== 'script') return true;
      const source = item.attrs.find(attr => attr.name === 'src')?.value;
      if (!source || content(item).trim()) throw new Error('Script inline non autorizzato in ' + file);
      const url = new URL(source, `${origin}/${file}`);
      if (url.origin !== origin || !url.pathname.startsWith('/scripts/')) {
        throw new Error('Script esterno non autorizzato: ' + source);
      }
      if (!sharedScripts.has(url.pathname)) scripts.push(url.pathname);
      return false;
    });
    for (const item of node.childNodes) clean(item);
  }
  clean(body);
  let markup = serialize(body);
  if (!hasMain) markup = `<main id="main-content" tabindex="-1">${markup}</main>`;
  return {
    file, route: routeForFile(file), title, description, styles, html: markup,
    scripts: [...new Set(scripts)], bodyAttributes: Object.fromEntries(body.attrs.map(attr => [attr.name, attr.value])),
  };
}
