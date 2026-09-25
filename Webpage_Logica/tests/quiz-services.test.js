const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function load(file, extras = {}) {
    const context = { ...extras };
    context.window = context;
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
    return context;
}

test('quiz timer formats and expires through injected scheduler', () => {
    let tick = null;
    let expired = false;
    const display = { textContent: '', hidden: true };
    const context = load('scripts/quiz-timer.js', {
        setInterval: callback => { tick = callback; return 7; },
        clearInterval: () => {}
    });
    const timer = context.LogicQuizTimer.create({
        display,
        defaultMinutes: 1,
        parseMinutes: value => Number(value),
        onExpire: () => { expired = true; },
        setInterval: context.setInterval,
        clearInterval: context.clearInterval
    });
    timer.start(1);
    for (let index = 0; index < 60; index += 1) tick();
    assert.equal(display.textContent, '00:00');
    assert.equal(expired, true);
});

test('quiz timer resumes from exact remaining seconds', () => {
    let tick = null;
    const context = load('scripts/quiz-timer.js', {
        setInterval: callback => { tick = callback; return 8; },
        clearInterval: () => {}
    });
    const timer = context.LogicQuizTimer.create({
        defaultMinutes: 20,
        parseMinutes: Number,
        setInterval: context.setInterval,
        clearInterval: context.clearInterval
    });
    timer.startSeconds(17);
    tick();
    assert.equal(timer.getRemainingSeconds(), 16);
});

test('batch module preserves local-only slots and response indexes', async () => {
    const context = load('scripts/quiz-batch.js');
    const result = await context.LogicQuizBatch.fetchQuestions([
        { operation: 'first', payload: {} },
        { operation: 'local', payload: {}, localOnly: true },
        { operation: 'third', payload: {} }
    ], {
        buildApiUrl: path => '/' + path,
        postJson: async () => ({
            result: { questions: [
                { index: 1, status: 'ok', result: { id: 'third' } },
                { index: 0, status: 'ok', result: { id: 'first' } }
            ] }
        })
    });
    assert.equal(result[0].id, 'first');
    assert.equal(result[1], null);
    assert.equal(result[2].id, 'third');
});

test('feedback requires every score in the 1-5 range', () => {
    const context = load('scripts/quiz-feedback.js');
    const values = {};
    context.LogicQuizFeedback.FIELDS.forEach(field => { values[field.id] = '5'; });
    assert.equal(context.LogicQuizFeedback.isComplete(values), true);
    values.control = '0';
    assert.equal(context.LogicQuizFeedback.isComplete(values), false);
});

test('feedback keeps the five legacy payload keys while clarifying visible labels', () => {
    const context = load('scripts/quiz-feedback.js');
    const fields = context.LogicQuizFeedback.FIELDS;

    assert.deepEqual(Array.from(fields, field => field.payloadKey), [
        'Aspettative test',
        'Utilità ausili',
        'Utilità lezioni',
        'Difficoltà test',
        'Controllo'
    ]);
    assert.equal(fields.length, 5);
    assert.ok(fields.every(field => field.label.endsWith('.')));
});

test('optional demographic age accepts only blank or integer values from 1 to 199', () => {
    const context = load('scripts/quiz-feedback.js');
    const isValid = context.LogicQuizFeedback.isOptionalAgeValid;

    ['', '1', '22', '199', ' 42 '].forEach(value => assert.equal(isValid(value), true));
    ['0', '200', '-1', '2.5', 'venti'].forEach(value => assert.equal(isValid(value), false));
    assert.equal(isValid('', { badInput: true }), false);
    assert.equal(isValid('22', { stepMismatch: true }), false);
});

test('feedback retry reuses the UUID header and exact JSON body without adding payload fields', async () => {
    const requests = [];
    const uuids = [
        '11111111-1111-4111-8111-111111111111',
        '22222222-2222-4222-8222-222222222222'
    ];
    const context = {
        AbortController,
        clearTimeout,
        crypto: { randomUUID() { return uuids.shift(); } },
        fetch: async function(url, options) {
            requests.push({
                url: url,
                body: options.body,
                headers: { ...options.headers }
            });
            const firstAttempt = requests.length === 1;
            return {
                ok: !firstAttempt,
                status: firstAttempt ? 503 : 201,
                headers: { get() { return null; } },
                async json() { return firstAttempt ? { detail: 'temporaneamente non disponibile' } : { status: 'accepted' }; }
            };
        },
        setTimeout
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/api-client.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/quiz-feedback.js', 'utf8'), context);

    const originalPayload = {
        'Initial Data': { 'Tempo totale': '12.34s', 'Totale domande': 2 },
        Domande: [{ 'Domanda nº 1': { Tipologia: 'Equivalenza' } }],
        Feedback: { 'Aspettative test': '5' }
    };
    const expectedPayload = JSON.parse(JSON.stringify(originalPayload));
    const submission = context.LogicQuizFeedback.createSubmission({
        postJson: context.LogicApi.postJson
    });

    assert.equal(await submission.submit(originalPayload), false);
    assert.equal(await submission.submit({ changed: 'must not replace a retry body' }), true);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].body, requests[1].body);
    assert.deepEqual(JSON.parse(requests[0].body), expectedPayload);
    assert.equal(Object.hasOwn(JSON.parse(requests[0].body), 'Idempotency-Key'), false);
    assert.equal(
        requests[0].headers['Idempotency-Key'],
        '11111111-1111-4111-8111-111111111111'
    );
    assert.equal(requests[1].headers['Idempotency-Key'], requests[0].headers['Idempotency-Key']);

    submission.reset();
    assert.equal(await submission.submit(originalPayload), true);
    assert.equal(
        requests[2].headers['Idempotency-Key'],
        '22222222-2222-4222-8222-222222222222'
    );
    assert.notEqual(requests[2].headers['Idempotency-Key'], requests[1].headers['Idempotency-Key']);
});

test('changing a failed feedback report invalidates its idempotency key', async () => {
    const calls = [];
    const keys = [
        '33333333-3333-4333-8333-333333333333',
        '44444444-4444-4444-8444-444444444444'
    ];
    const context = load('scripts/quiz-feedback.js', {
        crypto: { randomUUID() { return keys.shift(); } }
    });
    const submission = context.LogicQuizFeedback.createSubmission({
        postJson: async function(_url, payload, options) {
            calls.push({ payload: JSON.parse(JSON.stringify(payload)), key: options.headers['Idempotency-Key'] });
            if (calls.length === 1) throw new Error('timeout');
            return { status: 'accepted' };
        }
    });

    assert.equal(await submission.submit({ Feedback: { Controllo: '1' } }), false);
    assert.equal(submission.invalidate(), true);
    assert.equal(await submission.submit({ Feedback: { Controllo: '2' } }), true);
    assert.notEqual(calls[0].key, calls[1].key);
    assert.notDeepEqual(calls[0].payload, calls[1].payload);
});
