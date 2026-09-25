'use strict';

/*
 * Worker di dismissione: non offre cache, fallback offline o intercettazione fetch.
 * Rimane raggiungibile per una release affinche i browser con la vecchia PWA
 * possano attivarlo, eliminare le cache TestLogica e annullare la registrazione.
 */
const LEGACY_CACHE_PREFIX = 'testlogica-';

async function retireLegacyPwa() {
    const names = await caches.keys();
    await Promise.all(names
        .filter(function(name) { return name.startsWith(LEGACY_CACHE_PREFIX); })
        .map(function(name) { return caches.delete(name); }));
    await self.clients.claim();
    await self.registration.unregister();
}

self.addEventListener('install', function(event) {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', function(event) {
    event.waitUntil(retireLegacyPwa());
});
