/* Configurazione e piano deterministico delle tipologie di quiz. */
(function exposeQuizConfig(global) {
    'use strict';

    const TYPE_TO_OPERATION = Object.freeze({
        equivalence: 'build_ex_depth',
        'truth-value': 'build_tvq',
        'logical-consequence': 'build_logical_consequence_question',
        translation: 'build_translation_question',
        'quantifier-negation': 'build_quantifier_negation'
    });

    function atomCountForDifficulty(difficulty) {
        if (difficulty === 'hard') return 5;
        if (difficulty === 'easy') return 3;
        return 4;
    }

    function buildOperationPlan(config, payloadBuilders) {
        const normalized = global.LogicDataContracts.normalizeQuizConfig(config);
        const builders = payloadBuilders || {};
        const plan = [];
        const quotaPlan = [];
        Object.keys(normalized.typeCounts || {}).forEach(function(type) {
            if (!normalized.questionTypes.includes(type)) return;
            for (let count = 0; count < normalized.typeCounts[type]; count += 1) quotaPlan.push(type);
        });
        for (let index = 0; index < normalized.questionCount; index += 1) {
            const type = quotaPlan[index] || normalized.questionTypes[index % normalized.questionTypes.length];
            const operation = TYPE_TO_OPERATION[type];
            if (!operation) continue;
            if (type === 'quantifier-negation') {
                plan.push({ operation: operation, payload: {}, localOnly: true, questionType: type });
                continue;
            }
            const builder = builders[type];
            plan.push({
                operation: operation,
                payload: typeof builder === 'function' ? builder(normalized) : {},
                questionType: type
            });
        }
        return plan;
    }

    function allowedOperations(config) {
        const normalized = global.LogicDataContracts.normalizeQuizConfig(config);
        return normalized.questionTypes.map(function(type) {
            return TYPE_TO_OPERATION[type];
        }).filter(Boolean);
    }

    function resolveFallbackOperation(config, plannedOperation) {
        const allowed = allowedOperations(config);
        const requested = String(plannedOperation || '');
        if (allowed.includes(requested)) return requested;
        return allowed[0] || '';
    }

    function readForm(root) {
        const scope = root || document;
        const checkedTypes = Array.from(scope.querySelectorAll('[data-quiz-question-type]:checked'))
            .map(function(input) { return input.value; });
        const typeCounts = {};
        scope.querySelectorAll('[data-quiz-type-count]').forEach(function(input) {
            if (checkedTypes.includes(input.dataset.quizTypeCount)) {
                typeCounts[input.dataset.quizTypeCount] = input.value;
            }
        });
        return global.LogicDataContracts.normalizeQuizConfig({
            preset: scope.querySelector('#quizPreset')?.value,
            mode: scope.querySelector('#quizMode')?.value,
            difficulty: scope.querySelector('#quizDifficulty')?.value,
            questionCount: scope.querySelector('#quizQuestionCount')?.value,
            timeMinutes: scope.querySelector('#quizTimeMinutes')?.value,
            questionTypes: checkedTypes,
            typeCounts: typeCounts,
            adaptive: scope.querySelector('#quizAdaptive')?.checked,
            showConstruction: scope.querySelector('#quizShowConstruction')?.checked,
            spokenLanguage: scope.querySelector('#quizSpokenLanguage')?.checked,
            showImages: scope.querySelector('#quizShowWrongActionImages')?.checked
        });
    }

    function syncPresetLocks(root, preset) {
        const scope = root || document;
        const examLocked = preset === 'exam';
        const difficulty = scope.querySelector('#quizDifficulty');
        const timeMinutes = scope.querySelector('#quizTimeMinutes');
        const questionTypes = scope.querySelector('#quizQuestionTypes');

        if (difficulty) difficulty.disabled = examLocked;
        if (timeMinutes) timeMinutes.disabled = examLocked;
        if (questionTypes) questionTypes.disabled = examLocked;
    }

    function applyPreset(root, preset) {
        const scope = root || document;
        const mode = scope.querySelector('#quizMode');
        if (preset === 'custom') {
            if (mode) mode.value = 'practice';
            syncPresetLocks(scope, preset);
            return;
        }
        const values = preset === 'exam'
            ? { mode: 'exam', difficulty: 'medium', adaptive: false, construction: false }
            : preset === 'practice'
                ? { mode: 'practice', difficulty: 'easy', adaptive: true, construction: true }
                : null;
        if (!values) return;
        const difficulty = scope.querySelector('#quizDifficulty');
        const adaptive = scope.querySelector('#quizAdaptive');
        const construction = scope.querySelector('#quizShowConstruction');
        if (mode) mode.value = values.mode;
        if (difficulty) difficulty.value = values.difficulty;
        if (adaptive) adaptive.checked = values.adaptive;
        if (construction) construction.checked = values.construction;
        syncPresetLocks(scope, preset);
    }

    global.LogicQuizConfig = Object.freeze({
        TYPE_TO_OPERATION: TYPE_TO_OPERATION,
        allowedOperations: allowedOperations,
        applyPreset: applyPreset,
        atomCountForDifficulty: atomCountForDifficulty,
        buildOperationPlan: buildOperationPlan,
        readForm: readForm,
        resolveFallbackOperation: resolveFallbackOperation,
        syncPresetLocks: syncPresetLocks
    });
})(window);
