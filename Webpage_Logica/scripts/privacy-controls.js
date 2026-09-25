/* Preferenze esplicite per persistenza locale e trasmissione del feedback. */
(function exposePrivacyControls(global) {
    'use strict';

    const STORAGE_KEY = 'logic-privacy-preferences-v1';
    const DEFAULTS = Object.freeze({
        version: 1,
        localData: false,
        anonymousFeedback: false,
        includeDemographics: false,
        updatedAt: 0
    });

    function safeStorage(storage) {
        return storage || global.localStorage || null;
    }

    function read(storage) {
        const target = safeStorage(storage);
        if (!target) return { ...DEFAULTS };
        try {
            const raw = JSON.parse(target.getItem(STORAGE_KEY) || 'null');
            if (!raw || raw.version !== 1) return { ...DEFAULTS };
            return {
                version: 1,
                localData: Boolean(raw.localData),
                anonymousFeedback: Boolean(raw.anonymousFeedback),
                includeDemographics: Boolean(raw.anonymousFeedback && raw.includeDemographics),
                updatedAt: Number(raw.updatedAt) || 0
            };
        } catch (_) {
            return { ...DEFAULTS };
        }
    }

    function update(patch, storage) {
        const target = safeStorage(storage);
        const current = read(target);
        const changes = patch && typeof patch === 'object' ? patch : {};
        const next = {
            version: 1,
            localData: Object.prototype.hasOwnProperty.call(changes, 'localData')
                ? Boolean(changes.localData)
                : current.localData,
            anonymousFeedback: Object.prototype.hasOwnProperty.call(changes, 'anonymousFeedback')
                ? Boolean(changes.anonymousFeedback)
                : current.anonymousFeedback,
            includeDemographics: Object.prototype.hasOwnProperty.call(changes, 'includeDemographics')
                ? Boolean(changes.includeDemographics)
                : current.includeDemographics,
            updatedAt: Date.now()
        };
        if (!next.anonymousFeedback) next.includeDemographics = false;
        if (target) target.setItem(STORAGE_KEY, JSON.stringify(next));
        if (global.LogicAppEvents) global.LogicAppEvents.emit('privacy:changed', next);
        return next;
    }

    function reset(storage) {
        const target = safeStorage(storage);
        if (target) target.removeItem(STORAGE_KEY);
        const value = { ...DEFAULTS };
        if (global.LogicAppEvents) global.LogicAppEvents.emit('privacy:changed', value);
        return value;
    }

    global.LogicPrivacy = Object.freeze({
        DEFAULTS: DEFAULTS,
        STORAGE_KEY: STORAGE_KEY,
        canPersist: function() { return read().localData; },
        canSendFeedback: function() { return read().anonymousFeedback; },
        includeDemographics: function() { return read().includeDemographics; },
        read: read,
        reset: reset,
        update: update
    });
})(window);
