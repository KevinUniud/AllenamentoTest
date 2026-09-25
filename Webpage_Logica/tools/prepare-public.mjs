import { cp, mkdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

// public/ is generated only from this allow-list, never from the workspace or .env.
const root = process.cwd();
const target = resolve(root, 'public');
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
for (const entry of ['scripts', 'styles', 'Immagini', 'favicon.ico', 'service-worker.js']) {
  await cp(resolve(root, entry), resolve(target, entry), { recursive: true });
}
await mkdir(resolve(target, 'grafici'), { recursive: true });
await cp(resolve(root, 'grafici/placeholder.svg'), resolve(target, 'grafici/placeholder.svg'));
console.log('Asset pubblici preparati dalla lista dei sorgenti autorizzati.');
