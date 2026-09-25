const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadQuizModules() {
    const context = { window: null };
    context.window = context;
    [
        'scripts/data-contracts.js',
        'scripts/quiz-payloads.js',
        'scripts/quiz-config.js',
        'scripts/quiz-report.js'
    ].forEach(function(file) {
        vm.runInNewContext(fs.readFileSync(file, 'utf8'), context, { filename: file });
    });
    return context;
}

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

function extractFunction(source, name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, 'funzione non trovata: ' + name);
    const bodyStart = source.indexOf('{', start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error('corpo funzione non terminato: ' + name);
}

function quizFormScope(configuration) {
    const config = configuration || {};
    const types = config.types || [];
    const selected = config.selectedTypes || [];
    const elements = {
        '#quizPreset': { value: config.preset },
        '#quizMode': { value: config.mode },
        '#quizDifficulty': { value: config.difficulty },
        '#quizQuestionCount': { value: String(selected.length) },
        '#quizTimeMinutes': { value: '20' },
        '#quizAdaptive': { checked: config.options.adaptive },
        '#quizShowConstruction': { checked: config.options.showConstruction },
        '#quizSpokenLanguage': { checked: config.options.spokenLanguage },
        '#quizShowWrongActionImages': { checked: config.options.showImages }
    };
    const checkedTypes = selected.map(function(type) { return { value: type }; });
    const typeCounts = types.map(function(type) {
        return {
            dataset: { quizTypeCount: type },
            value: selected.includes(type) ? '1' : '99'
        };
    });
    return {
        querySelector: function(selector) { return elements[selector] || null; },
        querySelectorAll: function(selector) {
            if (selector === '[data-quiz-question-type]:checked') return checkedTypes;
            if (selector === '[data-quiz-type-count]') return typeCounts;
            return [];
        }
    };
}

function selectedTypes(types, mask) {
    return types.filter(function(_type, index) {
        return Boolean(mask & (1 << index));
    });
}

const BOOLEAN_OPTION_NAMES = [
    'showFormulas',
    'colorAtoms',
    'spokenLanguage',
    'showImages',
    'adaptive',
    'showConstruction'
];

function booleanOptions(mask) {
    return Object.fromEntries(BOOLEAN_OPTION_NAMES.map(function(name, index) {
        return [name, Boolean(mask & (1 << index))];
    }));
}

function quantifierRatioForDifficulty(difficulty) {
    if (difficulty === 'hard') return 0.75;
    if (difficulty === 'easy') return 0.25;
    return 0.5;
}

function expectedPayload(type, difficulty, spokenLanguage, names, actions) {
    const atomCount = difficulty === 'hard' ? 5 : difficulty === 'easy' ? 3 : 4;
    if (type === 'equivalence') {
        return {
            use_all: false,
            wrong_answers_count: 3,
            allow_spoken_mode: spokenLanguage,
            timeout: 10
        };
    }
    if (type === 'truth-value') {
        return {
            predicate_count: atomCount,
            true_options_count: 1,
            false_options_count: 3,
            allow_spoken_mode: spokenLanguage,
            timeout: 10
        };
    }
    if (type === 'logical-consequence') {
        return {
            variable_count: atomCount,
            correct_options_count: 1,
            wrong_options_count: 3,
            allow_spoken_mode: spokenLanguage,
            timeout: 10
        };
    }
    if (type === 'translation') {
        return {
            mode: 'auto',
            quantifier_ratio: quantifierRatioForDifficulty(difficulty),
            wrong_options_count: 3,
            names_pool: names,
            people_count: 3,
            actions_pool: actions,
            allow_spoken_mode: spokenLanguage,
            timeout: 10
        };
    }
    return {};
}

test('every finite quiz option combination produces the expected plan and payloads', () => {
    const context = loadQuizModules();
    const contracts = context.LogicDataContracts;
    const configModule = context.LogicQuizConfig;
    const payloads = context.LogicQuizPayloads;
    const report = context.LogicQuizReport;
    const presets = ['practice', 'exam', 'custom'];
    const difficulties = Array.from(contracts.DIFFICULTIES);
    const types = Array.from(contracts.QUESTION_TYPES);
    const names = ['Anna', 'Bruno', 'Carla', 'Diego', 'Elena'];
    const actions = ['corre', 'studia', 'nuota', 'legge', 'salta'];
    let combinations = 0;

    presets.forEach(function(preset) {
        difficulties.forEach(function(difficulty) {
            for (let typeMask = 1; typeMask < (1 << types.length); typeMask += 1) {
                const requestedTypes = selectedTypes(types, typeMask);

                for (let optionMask = 0; optionMask < (1 << BOOLEAN_OPTION_NAMES.length); optionMask += 1) {
                    const options = booleanOptions(optionMask);
                    const mode = preset === 'exam' ? 'exam' : 'practice';
                    const normalized = configModule.readForm(quizFormScope({
                        preset: preset,
                        mode: mode,
                        difficulty: difficulty,
                        types: types,
                        selectedTypes: requestedTypes,
                        options: options
                    }));
                    const atomCount = configModule.atomCountForDifficulty(normalized.difficulty);
                    const ratio = quantifierRatioForDifficulty(normalized.difficulty);
                    const plan = configModule.buildOperationPlan(normalized, {
                        equivalence: function() {
                            return payloads.buildEquivalencePayload(normalized.spokenLanguage, {
                                wrongAnswersCount: 3
                            });
                        },
                        'truth-value': function() {
                            return payloads.buildTruthValuePayload(normalized.spokenLanguage, atomCount, {
                                wrongAnswersCount: 3
                            });
                        },
                        'logical-consequence': function() {
                            return payloads.buildLogicalConsequencePayload(normalized.spokenLanguage, atomCount, {
                                wrongAnswersCount: 3
                            });
                        },
                        translation: function() {
                            return payloads.buildTranslationPayload(
                                normalized.spokenLanguage,
                                names,
                                actions,
                                function(values) { return values; },
                                { wrongAnswersCount: 3, quantifierRatio: ratio }
                            );
                        }
                    });
                    const activeOptions = {
                        showFormulas: options.showFormulas,
                        colorAtoms: options.colorAtoms,
                        spokenLanguage: options.spokenLanguage,
                        showWrongActionImages: options.showImages
                    };
                    const reportOptions = report.buildReport({
                        startedAt: 1,
                        now: 2,
                        results: [{
                            isCorrect: true,
                            question: 'Q',
                            selectedAnswer: 'A',
                            correctAnswer: 'A',
                            opzioniAttive: activeOptions
                        }]
                    })['Initial Data']['Opzioni attive'];
                    const expectedPlan = requestedTypes.map(function(type) {
                        const item = {
                            operation: configModule.TYPE_TO_OPERATION[type],
                            payload: expectedPayload(type, difficulty, options.spokenLanguage, names, actions),
                            questionType: type
                        };
                        if (type === 'quantifier-negation') item.localOnly = true;
                        return item;
                    });
                    const caseLabel = [preset, difficulty, typeMask, optionMask].join('/');

                    assert.deepEqual({
                        preset: normalized.preset,
                        mode: normalized.mode,
                        difficulty: normalized.difficulty,
                        questionCount: normalized.questionCount,
                        questionTypes: Array.from(normalized.questionTypes),
                        adaptive: normalized.adaptive,
                        showConstruction: normalized.showConstruction,
                        spokenLanguage: normalized.spokenLanguage,
                        showImages: normalized.showImages,
                        atomCount: atomCount,
                        plan: plain(plan),
                        reportOptions: plain(reportOptions)
                    }, {
                        preset: preset,
                        mode: mode,
                        difficulty: difficulty,
                        questionCount: requestedTypes.length,
                        questionTypes: requestedTypes,
                        adaptive: mode === 'exam' ? false : options.adaptive,
                        showConstruction: mode === 'exam' ? false : options.showConstruction,
                        spokenLanguage: options.spokenLanguage,
                        showImages: options.showImages,
                        atomCount: difficulty === 'hard' ? 5 : difficulty === 'easy' ? 3 : 4,
                        plan: expectedPlan,
                        reportOptions: activeOptions
                    }, 'combinazione ' + caseLabel);
                    combinations += 1;
                }
            }
        });
    });

    assert.equal(combinations, 3 * 3 * 31 * 64);
});

test('every valid minute value is preserved by quiz normalization', () => {
    const contracts = loadQuizModules().LogicDataContracts;
    const actual = [];
    for (let minutes = 1; minutes <= 240; minutes += 1) {
        actual.push(contracts.normalizeQuizConfig({ timeMinutes: minutes }).timeMinutes);
    }
    assert.deepEqual(actual, Array.from({ length: 240 }, function(_value, index) {
        return index + 1;
    }));
});

test('every valid per-type count is preserved and contributes to the total', () => {
    const context = loadQuizModules();
    const contracts = context.LogicDataContracts;
    const configModule = context.LogicQuizConfig;
    const types = Array.from(contracts.QUESTION_TYPES);
    let checkedValues = 0;

    types.forEach(function(type) {
        for (let count = 0; count <= 100; count += 1) {
            const normalized = contracts.normalizeQuizConfig({
                questionCount: 1,
                questionTypes: [type],
                typeCounts: { [type]: count }
            });
            assert.equal(normalized.typeCounts[type], count, type + '/' + String(count));
            assert.equal(normalized.questionCount, count || 1, type + '/' + String(count));
            assert.deepEqual(Array.from(normalized.questionTypes), [type], type + '/' + String(count));
            const plan = configModule.buildOperationPlan(normalized);
            assert.equal(plan.length, count || 1, type + '/' + String(count));
            assert.ok(plan.every(function(item) { return item.questionType === type; }), type + '/' + String(count));
            checkedValues += 1;
        }
    });

    assert.equal(checkedValues, 5 * 101);
});

test('preset locks are correct for every difficulty, minute and behavioural option state', () => {
    const configModule = loadQuizModules().LogicQuizConfig;
    const presets = ['practice', 'exam', 'custom'];
    const difficulties = ['easy', 'medium', 'hard'];
    let combinations = 0;

    presets.forEach(function(preset) {
        difficulties.forEach(function(initialDifficulty) {
            for (let minutes = 1; minutes <= 240; minutes += 1) {
                [false, true].forEach(function(initialAdaptive) {
                    [false, true].forEach(function(initialConstruction) {
                        const elements = {
                            '#quizMode': { value: 'exam' },
                            '#quizDifficulty': { value: initialDifficulty, disabled: false },
                            '#quizTimeMinutes': { value: String(minutes), disabled: false },
                            '#quizQuestionTypes': { disabled: false },
                            '#quizAdaptive': { checked: initialAdaptive },
                            '#quizShowConstruction': { checked: initialConstruction }
                        };
                        const scope = {
                            querySelector: function(selector) { return elements[selector] || null; }
                        };

                        configModule.applyPreset(scope, preset);

                        const expected = preset === 'exam'
                            ? {
                                mode: 'exam', difficulty: 'medium', adaptive: false, construction: false,
                                difficultyLocked: true, timeLocked: true, typesLocked: true
                            }
                            : preset === 'practice'
                                ? {
                                    mode: 'practice', difficulty: 'easy', adaptive: true, construction: true,
                                    difficultyLocked: false, timeLocked: false, typesLocked: false
                                }
                                : {
                                    mode: 'practice', difficulty: initialDifficulty,
                                    adaptive: initialAdaptive, construction: initialConstruction,
                                    difficultyLocked: false, timeLocked: false, typesLocked: false
                                };

                        assert.deepEqual({
                            mode: elements['#quizMode'].value,
                            difficulty: elements['#quizDifficulty'].value,
                            adaptive: elements['#quizAdaptive'].checked,
                            construction: elements['#quizShowConstruction'].checked,
                            difficultyLocked: elements['#quizDifficulty'].disabled,
                            timeLocked: elements['#quizTimeMinutes'].disabled,
                            typesLocked: elements['#quizQuestionTypes'].disabled
                        }, expected, [preset, initialDifficulty, minutes, initialAdaptive, initialConstruction].join('/'));
                        assert.equal(elements['#quizTimeMinutes'].value, String(minutes));
                        combinations += 1;
                    });
                });
            }
        });
    });

    assert.equal(combinations, 3 * 3 * 240 * 2 * 2);
});

test('numeric values outside UI bounds are constrained safely', () => {
    const contracts = loadQuizModules().LogicDataContracts;
    const below = contracts.normalizeQuizConfig({
        timeMinutes: 0,
        questionTypes: ['equivalence'],
        typeCounts: { equivalence: -1 }
    });
    const above = contracts.normalizeQuizConfig({
        timeMinutes: 241,
        questionTypes: ['equivalence'],
        typeCounts: { equivalence: 101 }
    });

    assert.equal(below.timeMinutes, 1);
    assert.equal(below.typeCounts.equivalence, 0);
    assert.equal(below.questionCount, 10);
    assert.equal(above.timeMinutes, 240);
    assert.equal(above.typeCounts.equivalence, 100);
    assert.equal(above.questionCount, 100);
});

test('a zero aggregate is displayed exactly and cannot start a quiz', () => {
    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const startTest = extractFunction(quizSource, 'startTest');
    const syncTotal = extractFunction(quizSource, 'syncTypeCountTotal');
    const zeroGuardIndex = startTest.indexOf('if (requestedQuestionCount < 1)');
    const normalizationIndex = startTest.indexOf('currentQuizConfig = window.LogicQuizConfig.readForm(root)');

    assert.ok(zeroGuardIndex >= 0);
    assert.ok(normalizationIndex > zeroGuardIndex);
    assert.match(startTest, /alert\('Imposta almeno una domanda nelle tipologie selezionate\.'\);/);
    assert.match(syncTotal, /String\(total\)/);
    assert.doesNotMatch(syncTotal, /Math\.max\(1,/);
    assert.doesNotMatch(syncTotal, /Math\.min\(quizMaximumQuestions,/);
});

test('round-robin planning covers every non-empty type subset and session length', () => {
    const context = loadQuizModules();
    const contracts = context.LogicDataContracts;
    const configModule = context.LogicQuizConfig;
    const types = Array.from(contracts.QUESTION_TYPES);
    let combinations = 0;

    for (let typeMask = 1; typeMask < (1 << types.length); typeMask += 1) {
        const requestedTypes = selectedTypes(types, typeMask);
        for (let questionCount = 1; questionCount <= 100; questionCount += 1) {
            const plan = configModule.buildOperationPlan({
                questionCount: questionCount,
                questionTypes: requestedTypes
            });
            assert.equal(plan.length, questionCount);
            plan.forEach(function(item, index) {
                assert.equal(item.questionType, requestedTypes[index % requestedTypes.length]);
                assert.equal(item.operation, configModule.TYPE_TO_OPERATION[item.questionType]);
            });
            combinations += 1;
        }
    }

    assert.equal(combinations, 31 * 100);
});

test('the UI enforces all four spoken-language and image-toggle states', () => {
    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const syncImages = extractFunction(quizSource, 'syncWrongImagesAvailability');
    let combinations = 0;

    [false, true].forEach(function(spokenLanguage) {
        [false, true].forEach(function(imagesChecked) {
            let clearCalls = 0;
            const context = {
                state: {
                    spokenlanguage: spokenLanguage,
                    showWrongActionImages: !imagesChecked
                },
                showWrongActionImagesInput: {
                    checked: imagesChecked,
                    disabled: false
                },
                clearWrongActionImages: function() { clearCalls += 1; }
            };
            const run = vm.runInNewContext('(' + syncImages + ')', context);

            run();

            assert.equal(context.showWrongActionImagesInput.disabled, !spokenLanguage);
            assert.equal(context.showWrongActionImagesInput.checked, spokenLanguage && imagesChecked);
            assert.equal(context.state.showWrongActionImages, spokenLanguage && imagesChecked);
            assert.equal(clearCalls, spokenLanguage ? 0 : 1);
            combinations += 1;
        });
    });

    assert.equal(combinations, 4);
});

test('all visual option combinations are read from their actual controls', () => {
    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const getActiveOptions = extractFunction(quizSource, 'getActiveOptions');
    const controlIds = [
        'quizShowFormulas',
        'quizColorAtoms',
        'quizSpokenLanguage',
        'quizShowWrongActionImages'
    ];

    for (let mask = 0; mask < (1 << controlIds.length); mask += 1) {
        const controls = Object.fromEntries(controlIds.map(function(id, index) {
            return [id, { checked: Boolean(mask & (1 << index)) }];
        }));
        const context = {
            document: {
                getElementById: function(id) { return controls[id] || null; }
            }
        };
        const readOptions = vm.runInNewContext('(' + getActiveOptions + ')', context);

        assert.deepEqual(plain(readOptions()), {
            showFormulas: controls.quizShowFormulas.checked,
            colorAtoms: controls.quizColorAtoms.checked,
            spokenLanguage: controls.quizSpokenLanguage.checked,
            showWrongActionImages: controls.quizShowWrongActionImages.checked
        });
    }
});

test('all formula-rendering preference combinations initialize independently', () => {
    const context = { window: null };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/quiz-state.js', 'utf8'), context, {
        filename: 'scripts/quiz-state.js'
    });
    let combinations = 0;

    [false, true].forEach(function(highlightAtoms) {
        [false, true].forEach(function(differentiateParens) {
            const values = {
                highlight: highlightAtoms,
                parens: differentiateParens
            };
            const state = context.LogicQuizState.create({
                isExercisesPage: true,
                highlightKey: 'highlight',
                parensKey: 'parens',
                readSetting: function(key) { return values[key]; }
            });

            assert.equal(state.highlightAtoms, highlightAtoms);
            assert.equal(state.differentiateParens, differentiateParens);
            combinations += 1;
        });
    });

    assert.equal(combinations, 4);
});
