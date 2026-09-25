(function exposeQuizPayloads(global) {
    'use strict';

    const DEFAULT_TIMEOUT_SECONDS = 10;

    function count(value, fallback, minimum, maximum) {
        const number = Math.round(Number(value));
        return Number.isFinite(number) ? Math.min(maximum, Math.max(minimum, number)) : fallback;
    }

    function buildEquivalencePayload(spokenLanguageMode, options) {
        const settings = options || {};
        return {
            use_all: false,
            wrong_answers_count: count(settings.wrongAnswersCount, 3, 1, 21),
            allow_spoken_mode: Boolean(spokenLanguageMode),
            timeout: DEFAULT_TIMEOUT_SECONDS
        };
    }

    function buildTruthValuePayload(spokenLanguageMode, targetAtomCount, options) {
        const settings = options || {};
        return {
            predicate_count: count(targetAtomCount, 3, 3, 5),
            true_options_count: count(settings.trueOptionsCount, 1, 1, 32),
            false_options_count: count(settings.falseOptionsCount, 3, 1, 32),
            allow_spoken_mode: Boolean(spokenLanguageMode),
            timeout: DEFAULT_TIMEOUT_SECONDS
        };
    }

    function buildLogicalConsequencePayload(spokenLanguageMode, targetAtomCount, options) {
        const settings = options || {};
        let correctOptionsCount = count(settings.correctOptionsCount, 1, 1, 7);
        let wrongOptionsCount = count(settings.wrongAnswersCount, 3, 1, 7);
        if (correctOptionsCount + wrongOptionsCount > 8) {
            wrongOptionsCount = Math.max(1, 8 - correctOptionsCount);
        }
        if ((correctOptionsCount + wrongOptionsCount) % 2 !== 0) {
            if (correctOptionsCount + wrongOptionsCount < 8) {
                wrongOptionsCount += 1;
            } else {
                wrongOptionsCount -= 1;
            }
        }
        return {
            variable_count: count(targetAtomCount, 3, 2, 5),
            correct_options_count: correctOptionsCount,
            wrong_options_count: wrongOptionsCount,
            allow_spoken_mode: Boolean(spokenLanguageMode),
            timeout: DEFAULT_TIMEOUT_SECONDS
        };
    }

    function buildTranslationPayload(spokenLanguageMode, names, actions, shuffle, options) {
        const settings = options || {};
        const namesPool = Array.isArray(names) ? names.slice() : [];
        const actionsPool = Array.isArray(actions) ? actions.slice() : [];
        const randomizedActions = typeof shuffle === 'function' ? shuffle(actionsPool) : actionsPool;
        const quantifierRatio = Math.min(1, Math.max(0, Number(settings.quantifierRatio ?? 0.5)));
        const distinctNamesCount = new Set(namesPool).size;
        const distinctActionsCount = new Set(randomizedActions).size;
        let peopleLimit = distinctNamesCount;
        if (quantifierRatio > 0) {
            peopleLimit = quantifierRatio < 1
                ? Math.min(distinctNamesCount, distinctActionsCount)
                : distinctActionsCount;
        }
        return {
            mode: 'auto',
            quantifier_ratio: quantifierRatio,
            wrong_options_count: 3,
            names_pool: namesPool,
            people_count: Math.min(count(settings.peopleCount, 3, 1, 128), peopleLimit),
            actions_pool: randomizedActions,
            allow_spoken_mode: Boolean(spokenLanguageMode),
            timeout: DEFAULT_TIMEOUT_SECONDS
        };
    }

    global.LogicQuizPayloads = Object.freeze({
        buildEquivalencePayload,
        buildLogicalConsequencePayload,
        buildTranslationPayload,
        buildTruthValuePayload
    });
})(window);
