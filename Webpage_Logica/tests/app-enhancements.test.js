const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load(file, extras = {}) {
    const context = { ...extras };
    context.window = context;
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
    return context;
}

test('formula tree preserves construction nodes and operand edges', () => {
    const context = load('scripts/formula-tree.js');
    const graph = context.LogicFormulaTree.toGraph({ steps: [
        { node_id: 'p', result_prolog: 'p', depth: 0, operands: [] },
        { node_id: 'q', result_prolog: 'q', depth: 0, operands: [] },
        { node_id: 'and', result_prolog: 'and(p,q)', depth: 1, operands: ['p', 'q'] }
    ] });
    assert.equal(graph.nodes.length, 3);
    assert.equal(graph.edges.length, 2);
});

test('question text-to-speech controls and browser speech APIs are absent', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    const quiz = fs.readFileSync('scripts/quiz.js', 'utf8');
    assert.equal(fs.existsSync('scripts/spoken-mode.js'), false);
    assert.doesNotMatch(html, /spoken-mode\.js|quizSpeakButton|quizStopSpeakingButton|quizSpeechRate/);
    assert.doesNotMatch(quiz, /LogicSpokenMode|speechSynthesis|SpeechSynthesisUtterance|quizSpeakButton|quizStopSpeakingButton|quizSpeechRate/);

    // La forma parlata resta una trasformazione testuale separata dal text-to-speech.
    assert.match(html, /id="quizSpokenLanguage"/);
    assert.match(quiz, /applySpokenTransform/);
});

test('local-first feature pages remain present', () => {
    [
        'progressi/index.html',
        'ripasso/errori.html',
        'strumenti/sandbox.html',
        'privacy.html'
    ].forEach(file => assert.equal(fs.existsSync(path.resolve(file)), true, file));
});

test('quiz sessions restore valid records and discard incompatible versions', async () => {
    const values = new Map();
    const storage = {
        put: async (type, id, value) => { values.set(type + ':' + id, value); return true; },
        get: async (type, id) => values.get(type + ':' + id) || null,
        remove: async (type, id) => values.delete(type + ':' + id)
    };
    const context = load('scripts/data-contracts.js');
    context.LogicAppStorage = { instance: storage };
    vm.runInNewContext(fs.readFileSync('scripts/quiz-session.js', 'utf8'), context);
    const manager = context.LogicQuizSession.create({ storage });
    const started = await manager.start({ questionCount: 4 });
    await manager.update({ currentIndex: 2, remainingSeconds: 99 });
    const restored = await manager.loadActive();
    assert.equal(restored.sessionId, started.sessionId);
    assert.equal(restored.remainingSeconds, 99);
    await storage.put('sessions', 'active', { ...restored, version: 999 });
    assert.equal(await manager.loadActive(), null);
});

test('quiz sessions ignore pending loads and cached state after privacy clearing events', async () => {
    let resolveGet;
    const context = load('scripts/app-events.js');
    vm.runInNewContext(fs.readFileSync('scripts/data-contracts.js', 'utf8'), context);
    const saved = context.LogicDataContracts.createSession({ config: { questionCount: 4 } });
    const storage = {
        put: async () => true,
        get: async () => new Promise(resolve => { resolveGet = resolve; }),
        remove: async () => true
    };
    context.LogicAppStorage = { instance: storage };
    vm.runInNewContext(fs.readFileSync('scripts/quiz-session.js', 'utf8'), context);
    const manager = context.LogicQuizSession.create({ storage });

    const pendingLoad = manager.loadActive();
    context.LogicAppEvents.emit('privacy:sessions-clearing');
    resolveGet(saved);
    assert.equal(await pendingLoad, null);

    assert.ok(await manager.start({ questionCount: 4 }));
    context.LogicAppEvents.emit('privacy:data-cleared');
    assert.equal(await manager.update({ currentIndex: 2 }), null);
});
