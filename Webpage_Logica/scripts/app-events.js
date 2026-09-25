/* Event bus minimale condiviso dalle funzionalità local-first. */
(function exposeAppEvents(global) {
    'use strict';

    const listeners = new Map();

    function on(name, listener) {
        if (typeof listener !== 'function') return function() {};
        const key = String(name || '');
        if (!listeners.has(key)) listeners.set(key, new Set());
        listeners.get(key).add(listener);
        return function unsubscribe() {
            const group = listeners.get(key);
            if (group) group.delete(listener);
        };
    }

    function emit(name, detail) {
        const group = listeners.get(String(name || ''));
        if (!group) return;
        Array.from(group).forEach(function(listener) {
            try {
                listener(detail);
            } catch (error) {
                if (global.LogicLogger) global.LogicLogger.error('Errore evento applicativo:', error);
            }
        });
    }

    global.LogicAppEvents = Object.freeze({ emit: emit, on: on });
})(window);
