const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');

function load(file) {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context, { filename: file });
    return context;
}

function extractFunction(source, name) {
    let start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, 'funzione non trovata: ' + name);
    if (source.slice(start - 6, start) === 'async ') start -= 6;
    const bodyStart = source.indexOf('{', start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error('corpo funzione non terminato: ' + name);
}

test('one hundred remote questions are sent as two aligned batches of fifty around local-only slots', async () => {
    const context = load('scripts/quiz-batch.js');
    const operations = [];
    const localPlanIndexes = new Set();

    function addLocalOnly(label) {
        localPlanIndexes.add(operations.length);
        operations.push({ operation: 'local-' + label, payload: {}, localOnly: true });
    }

    addLocalOnly('before');
    for (let remoteIndex = 0; remoteIndex < 100; remoteIndex += 1) {
        if ([25, 50, 75].includes(remoteIndex)) addLocalOnly('at-' + String(remoteIndex));
        operations.push({
            operation: 'remote-' + String(remoteIndex),
            payload: { remoteIndex: remoteIndex }
        });
    }
    addLocalOnly('after');

    const requests = [];
    const results = await context.LogicQuizBatch.fetchQuestions(operations, {
        batchSize: 50,
        timeoutMs: 4567,
        buildApiUrl: path => '/api/' + path,
        postJson: async function(url, body, options) {
            requests.push({ url: url, body: body, options: options });
            return {
                result: {
                    questions: Array.from(body.questions, function(question, index) {
                        return {
                            index: index,
                            status: 'ok',
                            result: { remoteIndex: question.payload.remoteIndex }
                        };
                    }).reverse()
                }
            };
        }
    });

    assert.equal(requests.length, 2);
    assert.deepEqual(requests.map(request => request.url), [
        '/api/generator/multiple-questions',
        '/api/generator/multiple-questions'
    ]);
    assert.deepEqual(requests.map(request => request.body.questions.length), [50, 50]);
    assert.deepEqual(requests.map(request => request.options.timeoutMs), [4567, 4567]);
    assert.deepEqual(
        Array.from(requests[0].body.questions, question => question.payload.remoteIndex),
        Array.from({ length: 50 }, (_value, index) => index)
    );
    assert.deepEqual(
        Array.from(requests[1].body.questions, question => question.payload.remoteIndex),
        Array.from({ length: 50 }, (_value, index) => index + 50)
    );

    assert.equal(results.length, operations.length);
    operations.forEach(function(operation, planIndex) {
        if (localPlanIndexes.has(planIndex)) {
            assert.equal(results[planIndex], null, 'slot locale ' + String(planIndex));
            return;
        }
        assert.equal(
            results[planIndex].remoteIndex,
            operation.payload.remoteIndex,
            'risposta remota riallineata al piano ' + String(planIndex)
        );
    });
});

test('capabilities keep the web session at 100 while respecting the advertised batch limit', async () => {
    const countInputs = Array.from({ length: 5 }, () => ({ max: '' }));
    const typeInputs = [
        { value: 'equivalence', disabled: false },
        { value: 'truth-value', disabled: false }
    ];
    const questionCountInput = { max: '' };
    const questionMaximumEl = { textContent: '' };
    const apiCalls = [];
    let advertisedLimits = {
        question_count: { maximum: 500 },
        batch_size: 500
    };
    const context = {
        MAX_QUIZ_QUESTIONS: 100,
        DEFAULT_BATCH_SIZE: 50,
        quizMaximumQuestions: 100,
        quizBatchSize: 50,
        questionCountInput: questionCountInput,
        questionMaximumEl: questionMaximumEl,
        adaptiveNoticeEl: { textContent: '' },
        buildApiUrl: path => '/api/' + path,
        root: {
            querySelectorAll(selector) {
                if (selector === '[data-quiz-type-count]') return countInputs;
                if (selector === '[data-quiz-question-type]') return typeInputs;
                return [];
            }
        }
    };
    context.window = context;
    context.LogicApi = {
        async requestJson(url, options) {
            apiCalls.push({ url: url, options: options });
            return {
                limits: advertisedLimits,
                question_types: ['equivalence', 'truth-value']
            };
        }
    };

    const loadQuizCapabilities = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'loadQuizCapabilities') + ')',
        context
    );
    await loadQuizCapabilities();

    assert.equal(apiCalls.length, 1);
    assert.equal(apiCalls[0].url, '/api/capabilities');
    assert.equal(apiCalls[0].options.timeoutMs, 5000);
    assert.equal(context.quizMaximumQuestions, 100);
    assert.equal(context.quizBatchSize, 100);
    assert.equal(questionCountInput.max, '100');
    assert.equal(questionMaximumEl.textContent, '100');
    assert.ok(countInputs.every(input => input.max === '100'));

    advertisedLimits = {
        question_count: { maximum: 100 },
        batch_size: 50
    };
    await loadQuizCapabilities();

    assert.equal(apiCalls.length, 2);
    assert.equal(context.quizMaximumQuestions, 100);
    assert.equal(context.quizBatchSize, 50);
});

test('the raw selected total accepts 100 questions and rejects 101 before normalization', async () => {
    const startTestSource = extractFunction(quizSource, 'startTest');

    function boundaryHarness(counts) {
        const alerts = [];
        let formReads = 0;
        const inputs = counts.map(function(count, index) {
            return {
                dataset: { quizTypeCount: 'type-' + String(index) },
                value: String(count)
            };
        });
        const context = {
            currentQuizConfig: null,
            quizMaximumQuestions: 100,
            syncLogDataSettings() {},
            alert(message) { alerts.push(message); },
            root: {
                querySelector(selector) {
                    if (selector === '[data-quiz-question-type]:checked') return { checked: true };
                    if (selector.startsWith('[data-quiz-question-type][value="')) return { checked: true };
                    return null;
                },
                querySelectorAll(selector) {
                    return selector === '[data-quiz-type-count]' ? inputs : [];
                }
            }
        };
        context.window = context;
        context.LogicQuizConfig = {
            readForm() {
                formReads += 1;
                throw new Error('accepted boundary');
            }
        };
        return {
            alerts: alerts,
            getFormReads: () => formReads,
            startTest: vm.runInNewContext('(' + startTestSource + ')', context)
        };
    }

    const atLimit = boundaryHarness([50, 50]);
    await assert.rejects(atLimit.startTest(), /accepted boundary/);
    assert.equal(atLimit.getFormReads(), 1);
    assert.deepEqual(atLimit.alerts, []);

    const aboveLimit = boundaryHarness([50, 51]);
    await aboveLimit.startTest();
    assert.equal(aboveLimit.getFormReads(), 0);
    assert.deepEqual(aboveLimit.alerts, [
        'Il quiz supporta al massimo 100 domande per sessione. Riduci le quantita per tipologia.'
    ]);
});

test('exercise markup advertises 100 as the total and per-type maximum', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    const typeCountInputs = html.match(/<input[^>]*data-quiz-type-count="[^"]+"[^>]*>/g) || [];

    assert.match(html, /<span id="quizQuestionMaximum">100<\/span>/);
    assert.match(html, /<output id="quizQuestionCount"[^>]*\bmax="100"[^>]*>10<\/output>/);
    assert.equal(typeCountInputs.length, 5);
    assert.ok(typeCountInputs.every(input => /\bmax="100"/.test(input)));
});
