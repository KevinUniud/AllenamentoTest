(function exposePreferences(global) {
    'use strict';

    const KEYS = Object.freeze({
        font: 'logic-app-font-size-px',
        highlightAtoms: 'logic-exercises-highlight-atoms',
        differentiateParens: 'logic-exercises-differentiate-parens',
        theme: 'logic-app-theme',
        daltonism: 'logic-app-daltonism-mode'
    });
    const DALTONISM_MODES = Object.freeze(['none', 'protanopia', 'deuteranopia', 'tritanopia', 'achromatopsia']);

    function clampFontPx(value, minimum, maximum, fallback) {
        const n = Number(value);
        if (!Number.isFinite(n)) return fallback;
        return Math.min(maximum, Math.max(minimum, Math.round(n)));
    }

    function parsePxValue(text, minimum, maximum, fallback) {
        const parsed = Number(String(text).replace(/px/gi, '').trim());
        if (!Number.isFinite(parsed)) return null;
        return clampFontPx(parsed, minimum, maximum, fallback);
    }

    function applyTheme(documentRef, mode) {
        const isDay = mode === 'day';
        documentRef.documentElement.classList.toggle('day-mode', isDay);
        documentRef.body.classList.toggle('day-mode', isDay);
        return isDay ? 'day' : 'night';
    }

    function applyDaltonism(documentRef, mode) {
        const safeMode = DALTONISM_MODES.includes(mode) ? mode : 'none';
        const nodes = [documentRef.documentElement, documentRef.body];
        nodes.forEach(function(node) {
            DALTONISM_MODES.slice(1).forEach(function(item) {
                node.classList.remove('daltonism-' + item);
            });
            if (safeMode !== 'none') node.classList.add('daltonism-' + safeMode);
        });
        return safeMode;
    }

    function readBool(storage, key) {
        return storage.getItem(key) === '1';
    }

    function writeBool(storage, key, value) {
        storage.setItem(key, value ? '1' : '0');
    }

    global.LogicPreferences = Object.freeze({
        DALTONISM_MODES,
        KEYS,
        applyDaltonism,
        applyTheme,
        clampFontPx,
        parsePxValue,
        readBool,
        writeBool
    });
})(window);
