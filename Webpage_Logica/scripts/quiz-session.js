/* Persistenza e ripresa di una singola sessione quiz attiva. */
(function exposeQuizSession(global) {
    'use strict';

    function create(options) {
        const settings = options || {};
        const storage = settings.storage || global.LogicAppStorage.instance;
        const contracts = settings.contracts || global.LogicDataContracts;
        const events = settings.events || global.LogicAppEvents;
        let current = null;
        let invalidationVersion = 0;
        let invalidated = false;

        function invalidate() {
            invalidationVersion += 1;
            invalidated = true;
            current = null;
        }

        if (events && typeof events.on === 'function') {
            [
                'privacy:data-clearing',
                'privacy:data-cleared',
                'privacy:sessions-clearing',
                'privacy:sessions-cleared'
            ].forEach(function(name) { events.on(name, invalidate); });
        }

        async function start(config) {
            invalidationVersion += 1;
            invalidated = false;
            const operationVersion = invalidationVersion;
            const started = contracts.createSession({ config: config, currentIndex: 1, phase: 'check' });
            current = started;
            await storage.put('sessions', 'active', started);
            if (invalidated || operationVersion !== invalidationVersion) return null;
            return started;
        }

        async function update(patch) {
            if (!current) {
                const loaded = await loadActive();
                if (!loaded) return null;
            }
            if (!current) return null;
            const operationVersion = invalidationVersion;
            const updated = contracts.createSession({ ...current, ...(patch || {}), updatedAt: Date.now() });
            current = updated;
            await storage.put('sessions', 'active', updated);
            if (invalidated || operationVersion !== invalidationVersion) return null;
            return updated;
        }

        async function loadActive() {
            if (invalidated) return null;
            const operationVersion = invalidationVersion;
            const value = await storage.get('sessions', 'active');
            if (invalidated || operationVersion !== invalidationVersion) return null;
            if (!value || value.version !== contracts.SCHEMA_VERSION || value.status !== 'active' || Number(value.expiresAt) <= Date.now()) {
                if (value) {
                    await storage.remove('sessions', 'active');
                    if (invalidated || operationVersion !== invalidationVersion) return null;
                }
                current = null;
                return null;
            }
            current = contracts.createSession(value);
            return current;
        }

        async function complete(answers) {
            if (!current) {
                const loaded = await loadActive();
                if (!loaded) return null;
            }
            if (!current) return null;
            const operationVersion = invalidationVersion;
            const completed = contracts.createSession({
                ...current,
                answers: Array.isArray(answers) ? answers : current.answers,
                status: 'completed',
                updatedAt: Date.now()
            });
            await storage.put('sessionHistory', completed.sessionId, completed);
            if (invalidated || operationVersion !== invalidationVersion) return null;
            await storage.remove('sessions', 'active');
            if (invalidated || operationVersion !== invalidationVersion) return null;
            current = null;
            return completed;
        }

        async function discard() {
            invalidate();
            await storage.remove('sessions', 'active');
        }

        return Object.freeze({ complete: complete, discard: discard, loadActive: loadActive, start: start, update: update });
    }

    global.LogicQuizSession = Object.freeze({ create: create });
})(window);
