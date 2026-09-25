/*
 * Stato iniziale del quiz, isolato dal rendering e dalle chiamate di rete.
 */
(function exposeQuizState(global) {
    'use strict';

    function create(options) {
        const settings = options || {};
        const isExercisesPage = Boolean(settings.isExercisesPage);
        const readSetting = typeof settings.readSetting === 'function'
            ? settings.readSetting
            : function() { return false; };

        return {
            mode: 'check',
            selectedIndex: 0,
            options: [],
            correctIndex: -1,
            locked: false,
            spokenlanguageLocked: false,
            exerciseKind: 'equivalence',
            showFormulas: false,
            colorAtoms: false,
            showWrongActionImages: false,
            highlightAtoms: isExercisesPage ? readSetting(settings.highlightKey) : false,
            differentiateParens: isExercisesPage ? readSetting(settings.parensKey) : false,
            spokenlanguage: false
        };
    }

    global.LogicQuizState = Object.freeze({
        create: create
    });
})(window);

