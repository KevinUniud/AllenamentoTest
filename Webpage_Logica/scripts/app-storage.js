/* Storage local-first versionato. Usa un solo object store e separa i record per tipo. */
(function exposeAppStorage(global) {
    'use strict';

    const DB_NAME = 'testlogica-local-data';
    const DB_VERSION = 1;
    const STORE_NAME = 'records';

    function createMemoryStore(privacy) {
        const records = new Map();
        const canPersist = privacy && typeof privacy.canPersist === 'function'
            ? privacy.canPersist
            : function() { return true; };

        function isExpired(record, now) {
            const value = record.value || {};
            const yearlyThreshold = now - (365 * 24 * 60 * 60 * 1000);
            if (record.type === 'sessions') return Number(value.expiresAt) > 0 && Number(value.expiresAt) <= now;
            if (record.type === 'attempts') return Number(value.answeredAt) > 0 && Number(value.answeredAt) < yearlyThreshold;
            if (record.type === 'errors') return Number(value.lastSeenAt) > 0 && Number(value.lastSeenAt) < yearlyThreshold;
            if (record.type === 'sessionHistory') return Number(value.updatedAt) > 0 && Number(value.updatedAt) < yearlyThreshold;
            return false;
        }

        return Object.freeze({
            available: false,
            put: async function(type, id, value) {
                if (!canPersist()) return false;
                records.set(String(type) + ':' + String(id), {
                    key: String(type) + ':' + String(id),
                    type: String(type),
                    id: String(id),
                    updatedAt: Date.now(),
                    value: value
                });
                return true;
            },
            get: async function(type, id) {
                if (!canPersist()) return null;
                const record = records.get(String(type) + ':' + String(id));
                return record ? record.value : null;
            },
            list: async function(type) {
                if (!canPersist()) return [];
                return Array.from(records.values())
                    .filter(function(record) { return record.type === String(type); })
                    .sort(function(left, right) { return right.updatedAt - left.updatedAt; })
                    .map(function(record) { return record.value; });
            },
            remove: async function(type, id) {
                if (!canPersist()) return false;
                records.delete(String(type) + ':' + String(id));
            },
            clearType: async function(type) {
                Array.from(records.keys()).forEach(function(key) {
                    if (key.startsWith(String(type) + ':')) records.delete(key);
                });
            },
            clearAll: async function() { records.clear(); },
            purgeExpired: async function(now) {
                if (!canPersist()) return 0;
                const reference = Number(now) || Date.now();
                let removed = 0;
                records.forEach(function(record, key) {
                    if (isExpired(record, reference)) { records.delete(key); removed += 1; }
                });
                return removed;
            },
            exportAll: async function() {
                if (!canPersist()) return [];
                return Array.from(records.values()).map(function(record) { return { ...record }; });
            }
        });
    }

    function create(options) {
        const settings = options || {};
        const indexedDBApi = settings.indexedDB || global.indexedDB;
        const privacy = settings.privacy || global.LogicPrivacy;
        if (!indexedDBApi) return createMemoryStore(privacy);
        let databasePromise = null;

        function canPersist() {
            return !privacy || typeof privacy.canPersist !== 'function' || privacy.canPersist();
        }

        function openDatabase() {
            if (databasePromise) return databasePromise;
            databasePromise = new Promise(function(resolve, reject) {
                const request = indexedDBApi.open(DB_NAME, DB_VERSION);
                request.onupgradeneeded = function() {
                    const database = request.result;
                    if (!database.objectStoreNames.contains(STORE_NAME)) {
                        const store = database.createObjectStore(STORE_NAME, { keyPath: 'key' });
                        store.createIndex('type', 'type', { unique: false });
                        store.createIndex('updatedAt', 'updatedAt', { unique: false });
                    }
                };
                request.onsuccess = function() { resolve(request.result); };
                request.onerror = function() { reject(request.error || new Error('IndexedDB non disponibile')); };
            });
            return databasePromise;
        }

        function requestPromise(request) {
            return new Promise(function(resolve, reject) {
                request.onsuccess = function() { resolve(request.result); };
                request.onerror = function() { reject(request.error || new Error('Operazione IndexedDB fallita')); };
            });
        }

        function recordExpired(record, now) {
            const value = record.value || {};
            const yearlyThreshold = now - (365 * 24 * 60 * 60 * 1000);
            if (record.type === 'sessions') return Number(value.expiresAt) > 0 && Number(value.expiresAt) <= now;
            if (record.type === 'attempts') return Number(value.answeredAt) > 0 && Number(value.answeredAt) < yearlyThreshold;
            if (record.type === 'errors') return Number(value.lastSeenAt) > 0 && Number(value.lastSeenAt) < yearlyThreshold;
            if (record.type === 'sessionHistory') return Number(value.updatedAt) > 0 && Number(value.updatedAt) < yearlyThreshold;
            return false;
        }

        async function withStore(mode, callback) {
            const database = await openDatabase();
            const transaction = database.transaction(STORE_NAME, mode);
            const store = transaction.objectStore(STORE_NAME);
            const completion = new Promise(function(resolve, reject) {
                transaction.oncomplete = function() { resolve(); };
                transaction.onerror = function() { reject(transaction.error || new Error('Transazione fallita')); };
                transaction.onabort = function() { reject(transaction.error || new Error('Transazione annullata')); };
            });
            const result = await callback(store);
            await completion;
            return result;
        }

        return Object.freeze({
            available: true,
            put: async function(type, id, value) {
                if (!canPersist()) return false;
                const record = {
                    key: String(type) + ':' + String(id),
                    type: String(type),
                    id: String(id),
                    updatedAt: Date.now(),
                    value: value
                };
                await withStore('readwrite', function(store) { return requestPromise(store.put(record)); });
                return true;
            },
            get: async function(type, id) {
                if (!canPersist()) return null;
                const record = await withStore('readonly', function(store) {
                    return requestPromise(store.get(String(type) + ':' + String(id)));
                });
                return record ? record.value : null;
            },
            list: async function(type) {
                if (!canPersist()) return [];
                const records = await withStore('readonly', function(store) {
                    return requestPromise(store.index('type').getAll(String(type)));
                });
                return records.sort(function(left, right) { return right.updatedAt - left.updatedAt; })
                    .map(function(record) { return record.value; });
            },
            remove: async function(type, id) {
                if (!canPersist()) return false;
                await withStore('readwrite', function(store) {
                    return requestPromise(store.delete(String(type) + ':' + String(id)));
                });
            },
            clearType: async function(type) {
                const database = await openDatabase();
                const transaction = database.transaction(STORE_NAME, 'readwrite');
                const index = transaction.objectStore(STORE_NAME).index('type');
                const request = index.openKeyCursor(String(type));
                request.onsuccess = function() {
                    const cursor = request.result;
                    if (!cursor) return;
                    transaction.objectStore(STORE_NAME).delete(cursor.primaryKey);
                    cursor.continue();
                };
                await new Promise(function(resolve, reject) {
                    transaction.oncomplete = function() { resolve(); };
                    transaction.onerror = function() { reject(transaction.error || new Error('Cancellazione fallita')); };
                });
            },
            clearAll: async function() {
                await withStore('readwrite', function(store) { return requestPromise(store.clear()); });
            },
            purgeExpired: async function(now) {
                if (!canPersist()) return 0;
                const reference = Number(now) || Date.now();
                const expired = await withStore('readonly', function(store) {
                    return requestPromise(store.getAll()).then(function(records) {
                        return records.filter(function(record) { return recordExpired(record, reference); }).map(function(record) { return record.key; });
                    });
                });
                if (!expired.length) return 0;
                await withStore('readwrite', function(store) {
                    expired.forEach(function(key) { store.delete(key); });
                    return Promise.resolve();
                });
                return expired.length;
            },
            exportAll: async function() {
                if (!canPersist()) return [];
                return withStore('readonly', function(store) { return requestPromise(store.getAll()); });
            }
        });
    }

    global.LogicAppStorage = Object.freeze({
        DB_NAME: DB_NAME,
        create: create,
        createMemoryStore: createMemoryStore,
        instance: create()
    });
})(window);
