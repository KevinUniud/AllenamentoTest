const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadFiles(files) {
    const context = { window: null };
    context.window = context;
    files.forEach(file => vm.runInNewContext(fs.readFileSync(file, 'utf8'), context));
    return context;
}

test('operation plan follows selected question types and exact count', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const plan = context.LogicQuizConfig.buildOperationPlan({
        questionCount: 5,
        questionTypes: ['equivalence', 'quantifier-negation']
    }, { equivalence: () => ({ value: 1 }) });

    assert.equal(plan.length, 5);
    assert.deepEqual(Array.from(plan, item => item.operation), [
        'build_ex_depth',
        'build_quantifier_negation',
        'build_ex_depth',
        'build_quantifier_negation',
        'build_ex_depth'
    ]);
});

test('operation plan honours exact per-type quotas', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const plan = context.LogicQuizConfig.buildOperationPlan({
        questionTypes: ['equivalence', 'translation'],
        typeCounts: { equivalence: 1, translation: 3 }
    }, { equivalence: () => ({}), translation: () => ({}) });
    assert.deepEqual(Array.from(plan, item => item.questionType), [
        'equivalence', 'translation', 'translation', 'translation'
    ]);
});

test('merged mode control preserves the complete quiz configuration contract', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const elements = {
        '#quizPreset': { value: 'exam' },
        '#quizMode': { value: 'exam' },
        '#quizDifficulty': { value: 'hard' },
        '#quizQuestionCount': { value: '4' },
        '#quizTimeMinutes': { value: '45' },
        '#quizAdaptive': { checked: true },
        '#quizShowConstruction': { checked: true },
        '#quizSpokenLanguage': { checked: true },
        '#quizShowWrongActionImages': { checked: true }
    };
    const checkedTypes = [
        { value: 'equivalence' },
        { value: 'truth-value' }
    ];
    const typeCounts = [
        { dataset: { quizTypeCount: 'equivalence' }, value: '1' },
        { dataset: { quizTypeCount: 'truth-value' }, value: '3' }
    ];
    const scope = {
        querySelector: selector => elements[selector] || null,
        querySelectorAll: selector => selector === '[data-quiz-question-type]:checked' ? checkedTypes : typeCounts
    };

    const config = context.LogicQuizConfig.readForm(scope);

    assert.deepEqual(JSON.parse(JSON.stringify(config)), {
        version: 1,
        preset: 'exam',
        mode: 'exam',
        questionCount: 4,
        timeMinutes: 45,
        difficulty: 'hard',
        questionTypes: ['equivalence', 'truth-value'],
        typeCounts: {
            equivalence: 1,
            'truth-value': 3,
            'logical-consequence': 0,
            translation: 0,
            'quantifier-negation': 0
        },
        adaptive: false,
        showConstruction: false,
        spokenLanguage: true,
        showImages: true
    });
});

test('mode presets continue to synchronize the hidden session mode', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const elements = {
        '#quizMode': { value: 'practice' },
        '#quizDifficulty': { value: 'easy' },
        '#quizAdaptive': { checked: true },
        '#quizShowConstruction': { checked: true }
    };
    const scope = { querySelector: selector => elements[selector] || null };

    context.LogicQuizConfig.applyPreset(scope, 'exam');

    assert.equal(elements['#quizMode'].value, 'exam');
    assert.equal(elements['#quizDifficulty'].value, 'medium');
    assert.equal(elements['#quizAdaptive'].checked, false);
    assert.equal(elements['#quizShowConstruction'].checked, false);
});

test('custom mode exits exam restrictions without overwriting user choices', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const elements = {
        '#quizMode': { value: 'practice' },
        '#quizDifficulty': { value: 'hard' },
        '#quizAdaptive': { checked: true },
        '#quizShowConstruction': { checked: true }
    };
    const scope = { querySelector: selector => elements[selector] || null };

    context.LogicQuizConfig.applyPreset(scope, 'exam');
    elements['#quizDifficulty'].value = 'hard';
    elements['#quizAdaptive'].checked = true;
    elements['#quizShowConstruction'].checked = true;
    context.LogicQuizConfig.applyPreset(scope, 'custom');

    assert.equal(elements['#quizMode'].value, 'practice');
    assert.equal(elements['#quizDifficulty'].value, 'hard');
    assert.equal(elements['#quizAdaptive'].checked, true);
    assert.equal(elements['#quizShowConstruction'].checked, true);

    const normalized = context.LogicDataContracts.normalizeQuizConfig({
        preset: 'custom',
        mode: elements['#quizMode'].value,
        difficulty: elements['#quizDifficulty'].value,
        adaptive: elements['#quizAdaptive'].checked,
        showConstruction: elements['#quizShowConstruction'].checked
    });
    assert.equal(normalized.preset, 'custom');
    assert.equal(normalized.mode, 'practice');
    assert.equal(normalized.adaptive, true);
    assert.equal(normalized.showConstruction, true);
});

test('exam preset locks only the requested configuration controls and unlocks them on exit', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const elements = {
        '#quizMode': { value: 'practice' },
        '#quizDifficulty': { value: 'hard', disabled: false },
        '#quizTimeMinutes': { value: '37', disabled: false },
        '#quizQuestionTypes': { disabled: false },
        '#quizAdaptive': { checked: true },
        '#quizShowConstruction': { checked: true }
    };
    const scope = { querySelector: selector => elements[selector] || null };

    context.LogicQuizConfig.applyPreset(scope, 'exam');

    assert.equal(elements['#quizDifficulty'].disabled, true);
    assert.equal(elements['#quizTimeMinutes'].disabled, true);
    assert.equal(elements['#quizTimeMinutes'].value, '37');
    assert.equal(elements['#quizQuestionTypes'].disabled, true);

    context.LogicQuizConfig.applyPreset(scope, 'custom');

    assert.equal(elements['#quizDifficulty'].disabled, false);
    assert.equal(elements['#quizTimeMinutes'].disabled, false);
    assert.equal(elements['#quizTimeMinutes'].value, '37');
    assert.equal(elements['#quizQuestionTypes'].disabled, false);
});

test('restoring an exam session reapplies locks without changing its saved values', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const saved = context.LogicDataContracts.normalizeQuizConfig({
        preset: 'exam',
        mode: 'exam',
        difficulty: 'hard',
        timeMinutes: 73,
        questionTypes: ['equivalence', 'translation'],
        typeCounts: { equivalence: 3, translation: 4 }
    });
    const elements = {
        '#quizDifficulty': { value: saved.difficulty, disabled: false },
        '#quizTimeMinutes': { value: String(saved.timeMinutes), disabled: false },
        '#quizQuestionTypes': { disabled: false },
        '#quizAdaptive': { checked: saved.adaptive, disabled: false }
    };
    const scope = { querySelector: selector => elements[selector] || null };

    context.LogicQuizConfig.syncPresetLocks(scope, saved.preset);

    assert.equal(elements['#quizDifficulty'].value, 'hard');
    assert.equal(elements['#quizTimeMinutes'].value, '73');
    assert.equal(elements['#quizDifficulty'].disabled, true);
    assert.equal(elements['#quizTimeMinutes'].disabled, true);
    assert.equal(elements['#quizQuestionTypes'].disabled, true);
    assert.equal(elements['#quizAdaptive'].disabled, false);

    context.LogicQuizConfig.syncPresetLocks(scope, 'custom');

    assert.equal(elements['#quizDifficulty'].value, 'hard');
    assert.equal(elements['#quizTimeMinutes'].value, '73');
    assert.equal(elements['#quizDifficulty'].disabled, false);
    assert.equal(elements['#quizTimeMinutes'].disabled, false);
    assert.equal(elements['#quizQuestionTypes'].disabled, false);
});

test('quiz restoration delegates the saved preset to the lock synchronizer', () => {
    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const applyStart = quizSource.indexOf('function applyConfigToForm(config)');
    const applyEnd = quizSource.indexOf('async function resumeSavedSession()', applyStart);
    const applyBlock = quizSource.slice(applyStart, applyEnd);

    assert.ok(applyStart >= 0 && applyEnd > applyStart);
    assert.match(applyBlock, /normalizeQuizConfig\(config\)/);
    assert.match(applyBlock, /syncPresetLocks\(root, normalized\.preset\)/);
});

test('single-question fallback stays inside configured types and honours a valid plan slot', () => {
    const context = loadFiles(['scripts/data-contracts.js', 'scripts/quiz-config.js']);
    const translationOnly = { spokenLanguage: true, questionTypes: ['translation'] };

    assert.deepEqual(
        Array.from(context.LogicQuizConfig.allowedOperations(translationOnly)),
        ['build_translation_question']
    );
    assert.equal(
        context.LogicQuizConfig.resolveFallbackOperation(translationOnly, 'build_tvq'),
        'build_translation_question'
    );
    assert.equal(
        context.LogicQuizConfig.resolveFallbackOperation(
            { questionTypes: ['truth-value', 'translation'] },
            'build_translation_question'
        ),
        'build_translation_question'
    );
});

test('adaptive engine changes at most one transparent level', () => {
    const context = loadFiles(['scripts/learning-metrics.js', 'scripts/adaptive-engine.js']);
    const attempts = Array.from({ length: 6 }, () => ({ type: 'equivalence', correct: true, elapsedMs: 1000 }));
    const result = context.LogicAdaptiveEngine.recommend(attempts, 'easy');

    assert.equal(result.difficulty, 'medium');
    assert.equal(result.changed, true);
    assert.match(result.reason, /80%/);
});

test('CSV export prevents spreadsheet formula injection', () => {
    const context = loadFiles(['scripts/results-export.js']);
    const csv = context.LogicResultsExport.toCsv([{ question: '=CMD()', correct: false }]);

    assert.match(csv, /'=CMD\(\)/);
});

test('metrics include accessible groupings by type and difficulty', () => {
    const context = loadFiles(['scripts/learning-metrics.js']);
    const metrics = context.LogicLearningMetrics.aggregate([
        { type: 'equivalence', difficulty: 'easy', correct: true, elapsedMs: 1000 },
        { type: 'equivalence', difficulty: 'hard', correct: false, elapsedMs: 3000 }
    ]);
    assert.equal(metrics.byType[0].total, 2);
    assert.equal(metrics.byDifficulty.length, 2);
});

test('error notebook preserves authentic transformation paths for later review', async () => {
    const writes = [];
    const storage = {
        get: async function() { return null; },
        put: async function(store, key, value) { writes.push({ store, key, value }); },
        list: async function() { return []; },
        remove: async function() {}
    };
    const contracts = {
        errorKey: function() { return 'equivalence|question-1|answer'; }
    };
    const context = { window: null };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/error-notebook.js', 'utf8'), context);
    const notebook = context.LogicErrorNotebook.create({ storage: storage, contracts: contracts });
    const correctTransformation = { version: 1, strategy: 'equivalence_rewrite' };
    const selectedTransformation = { version: 1, strategy: 'distractor_mutation' };

    await notebook.record({
        correct: false,
        questionId: 'question-1',
        type: 'equivalence',
        difficulty: 'easy',
        question: 'Domanda',
        selectedAnswer: 'and(p,q)',
        correctAnswer: 'or(not(p),q)',
        answeredAt: 1
    }, {
        transformationCorrect: correctTransformation,
        transformationSelected: selectedTransformation
    });

    assert.equal(writes.length, 1);
    assert.equal(writes[0].value.transformationCorrect, correctTransformation);
    assert.equal(writes[0].value.transformationSelected, selectedTransformation);
});
