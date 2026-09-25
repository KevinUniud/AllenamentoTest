(function exposeLogger(global) {
    'use strict';

    const enabled = Boolean(global.LOGIC_DEBUG);
    const sink = global.console || {};

    function emit(method, args) {
        if (!enabled && method !== 'error') return;
        if (typeof sink[method] === 'function') {
            sink[method].apply(sink, args);
        }
    }

    global.LogicLogger = Object.freeze({
        debug: function() { emit('debug', arguments); },
        info: function() { emit('info', arguments); },
        warn: function() { emit('warn', arguments); },
        error: function() { emit('error', arguments); }
    });
})(window);
