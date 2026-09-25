const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function contextWithStorage() {
    const values = new Map();
    const context = {
        localStorage: {
            getItem: key => values.has(key) ? values.get(key) : null,
            setItem: (key, value) => values.set(key, String(value)),
            removeItem: key => values.delete(key)
        },
        setTimeout,
        clearTimeout
    };
    context.window = context;
    return context;
}

function load(context, file) {
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
}

test('quiz configuration is normalized and exam mode disables adaptive help', () => {
    const context = contextWithStorage();
    load(context, 'scripts/data-contracts.js');
    const config = context.LogicDataContracts.normalizeQuizConfig({
        mode: 'exam',
        adaptive: true,
        showConstruction: true,
        questionCount: 500,
        questionTypes: ['translation', 'invalid']
    });

    assert.equal(config.questionCount, 100);
    assert.equal(config.adaptive, false);
    assert.equal(config.showConstruction, false);
    assert.deepEqual(Array.from(config.questionTypes), ['translation']);
});

test('privacy choices are opt-in and demographics depend on feedback consent', () => {
    const context = contextWithStorage();
    load(context, 'scripts/app-events.js');
    load(context, 'scripts/privacy-controls.js');

    assert.equal(context.LogicPrivacy.canPersist(), false);
    context.LogicPrivacy.update({ includeDemographics: true });
    assert.equal(context.LogicPrivacy.includeDemographics(), false);
    context.LogicPrivacy.update({ anonymousFeedback: true, includeDemographics: true });
    assert.equal(context.LogicPrivacy.includeDemographics(), true);
});

test('memory storage honours persistence consent and supports deletion', async () => {
    const context = contextWithStorage();
    load(context, 'scripts/app-events.js');
    load(context, 'scripts/privacy-controls.js');
    load(context, 'scripts/app-storage.js');
    const storage = context.LogicAppStorage.createMemoryStore(context.LogicPrivacy);

    assert.equal(await storage.put('sessions', 'one', { value: 1 }), false);
    context.LogicPrivacy.update({ localData: true });
    assert.equal(await storage.put('sessions', 'one', { value: 1 }), true);
    assert.equal((await storage.list('sessions')).length, 1);
    await storage.clearType('sessions');
    assert.equal((await storage.list('sessions')).length, 0);
});

test('IndexedDB is not opened by data operations before local-storage consent', async () => {
    let openCalls = 0;
    const context = contextWithStorage();
    context.LogicPrivacy = { canPersist: () => false };
    context.indexedDB = {
        open() {
            openCalls += 1;
            throw new Error('IndexedDB must remain closed without consent');
        }
    };
    load(context, 'scripts/app-storage.js');
    const storage = context.LogicAppStorage.instance;

    assert.equal(await storage.put('sessions', 'active', { value: 1 }, { force: true }), false);
    assert.equal(await storage.get('sessions', 'active'), null);
    assert.equal((await storage.list('sessions')).length, 0);
    assert.equal(await storage.remove('sessions', 'active'), false);
    assert.equal(await storage.purgeExpired(Date.now()), 0);
    assert.equal((await storage.exportAll()).length, 0);
    assert.equal(openCalls, 0);
});

test('memory storage hides existing records again when consent is revoked', async () => {
    let allowed = true;
    const context = contextWithStorage();
    load(context, 'scripts/app-storage.js');
    const storage = context.LogicAppStorage.createMemoryStore({ canPersist: () => allowed });

    await storage.put('sessions', 'active', { value: 1 });
    allowed = false;
    assert.equal(await storage.get('sessions', 'active'), null);
    assert.equal((await storage.list('sessions')).length, 0);
    assert.equal((await storage.exportAll()).length, 0);
    assert.equal(await storage.remove('sessions', 'active'), false);
    allowed = true;
    assert.equal((await storage.get('sessions', 'active')).value, 1);
});

test('expired sessions and learning records are purged locally', async () => {
    const context = contextWithStorage();
    load(context, 'scripts/app-events.js');
    load(context, 'scripts/privacy-controls.js');
    load(context, 'scripts/app-storage.js');
    context.LogicPrivacy.update({ localData: true });
    const storage = context.LogicAppStorage.createMemoryStore(context.LogicPrivacy);
    const now = Date.now();
    await storage.put('sessions', 'old', { expiresAt: now - 1 });
    await storage.put('attempts', 'old', { answeredAt: now - (366 * 86400000) });
    await storage.put('attempts', 'new', { answeredAt: now });
    assert.equal(await storage.purgeExpired(now), 2);
    assert.equal((await storage.list('attempts')).length, 1);
});
