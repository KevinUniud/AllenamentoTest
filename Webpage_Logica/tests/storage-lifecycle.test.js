const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function hasClass(element, name) {
    return String(element.className || '').split(/\s+/).includes(name);
}

class FakeElement {
    constructor(tagName) {
        this.tagName = String(tagName).toUpperCase();
        this.children = [];
        this.dataset = {};
        this.parentElement = null;
        this.className = '';
        this.id = '';
        this.href = '';
        this.disabled = false;
        this.offsetParent = {};
        this._text = '';
        this._listeners = new Map();
        this._attributes = new Map();
        this.classList = {
            add: (...names) => {
                const values = new Set(String(this.className || '').split(/\s+/).filter(Boolean));
                names.forEach(name => values.add(name));
                this.className = Array.from(values).join(' ');
            },
            remove: (...names) => {
                const removed = new Set(names);
                this.className = String(this.className || '').split(/\s+/)
                    .filter(name => name && !removed.has(name)).join(' ');
            },
            toggle: (name, force) => {
                const enabled = force === undefined ? !hasClass(this, name) : Boolean(force);
                if (enabled) this.classList.add(name);
                else this.classList.remove(name);
                return enabled;
            }
        };
    }

    get textContent() {
        return this._text + this.children.map(child => child.textContent).join('');
    }

    set textContent(value) {
        this._text = String(value);
        this.children.forEach(child => { child.parentElement = null; });
        this.children = [];
    }

    appendChild(child) {
        child.parentElement = this;
        this.children.push(child);
        return child;
    }

    addEventListener(name, listener) {
        this._listeners.set(name, listener);
    }

    dispatch(name) {
        const listener = this._listeners.get(name);
        return listener ? listener({ type: name, target: this }) : undefined;
    }

    setAttribute(name, value) {
        this._attributes.set(name, String(value));
    }

    getAttribute(name) {
        if (name === 'href' && this.href) return this.href;
        return this._attributes.has(name) ? this._attributes.get(name) : null;
    }

    hasAttribute(name) {
        return this._attributes.has(name);
    }

    focus() {}

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
        const className = selector.startsWith('.') ? selector.slice(1) : null;
        const matches = [];
        this.children.forEach(child => {
            if (className && hasClass(child, className)) matches.push(child);
            matches.push(...child.querySelectorAll(selector));
        });
        return matches;
    }

    remove() {
        if (!this.parentElement) return;
        const index = this.parentElement.children.indexOf(this);
        if (index >= 0) this.parentElement.children.splice(index, 1);
        this.parentElement = null;
    }
}

class FakeLessonDocument {
    constructor() {
        this.readyState = 'loading';
        this.body = new FakeElement('body');
        this.body.dataset.lessonId = 'lesson-1';
        this.heading = new FakeElement('h2');
        this.heading.id = 'intro';
        this.heading.textContent = '  Titolo   della sezione  ';
        this.switcher = new FakeElement('div');
        this.switcher.className = 'lesson-switcher-list';
        this.switcherLink = new FakeElement('a');
        this.switcherLink.className = 'lesson-switcher-link';
        this.switcherLink.href = '/lezioni/lezione-1.html';
        this.switcherLink.textContent = 'Lezione 1';
        this.switcher.appendChild(this.switcherLink);
        this.body.appendChild(this.heading);
        this.body.appendChild(this.switcher);
    }

    addEventListener() {}

    createElement(tagName) {
        return new FakeElement(tagName);
    }

    getElementById(id) {
        function find(element) {
            if (element.id === id) return element;
            for (const child of element.children) {
                const match = find(child);
                if (match) return match;
            }
            return null;
        }
        return find(this.body);
    }

    querySelector(selector) {
        if (selector === '.lesson-nav') return null;
        return this.body.querySelector(selector);
    }

    querySelectorAll(selector) {
        if (selector === 'section[id]') return [];
        if (selector === 'main h2, main h3, section h2, section h3') return [this.heading];
        return this.body.querySelectorAll(selector);
    }
}

class FakeSettingsDocument {
    constructor() {
        this.documentElement = new FakeElement('html');
        this.body = new FakeElement('body');
        this.activeElement = this.body;
    }

    addEventListener() {}

    createElement(tagName) {
        return new FakeElement(tagName);
    }

    getElementById(id) {
        function find(element) {
            if (element.id === id) return element;
            for (const child of element.children) {
                const match = find(child);
                if (match) return match;
            }
            return null;
        }
        return find(this.body);
    }

    querySelector(selector) {
        if (selector === 'script[src*="settings.js"]') return null;
        return this.body.querySelector(selector);
    }
}

function load(context, file) {
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
}

function lessonHarness(options = {}) {
    const document = new FakeLessonDocument();
    const puts = [];
    let listed = options.listed || [];
    let resolveGet;
    const storage = {
        get: options.deferred
            ? () => new Promise(resolve => { resolveGet = resolve; })
            : async () => options.saved || null,
        put: async (type, id, value) => {
            puts.push({ type, id, value });
            return true;
        },
        list: async () => listed
    };
    const context = {
        document,
        location: { pathname: '/lezioni/lezione-1.html' },
        LogicAppStorage: { instance: storage }
    };
    context.window = context;
    load(context, 'scripts/app-events.js');
    load(context, 'scripts/lesson-progress.js');
    return {
        context,
        document,
        puts,
        resolveGet(value) { resolveGet(value); },
        setListed(value) { listed = value; }
    };
}

function settingsHarness(storageOverrides = {}) {
    const document = new FakeSettingsDocument();
    const values = new Map([
        ['logDataAge', '25'],
        ['logDataInstitution', 'Università'],
        ['logDataStem', '1']
    ]);
    const updates = [];
    const events = [];
    const localStorage = {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key)
    };
    const appStorage = {
        clearAll: async () => {},
        clearType: async () => {},
        exportAll: async () => [],
        ...storageOverrides
    };
    const context = {
        document,
        localStorage,
        LogicAppStorage: { instance: appStorage },
        LogicAppEvents: { emit: name => events.push(name) },
        LogicPrivacy: {
            read: () => ({ localData: true, anonymousFeedback: true, includeDemographics: true }),
            update: patch => updates.push(patch)
        },
        CustomEvent: class CustomEvent {
            constructor(name, options) {
                this.type = name;
                this.detail = options && options.detail;
            }
        },
        dispatchEvent() {}
    };
    context.window = context;
    load(context, 'scripts/settings-preferences.js');
    load(context, 'scripts/settings.js');
    context.initGlobalSettings();

    function allElements(element) {
        return [element].concat(element.children.flatMap(allElements));
    }

    return {
        context,
        document,
        events,
        localStorage,
        updates,
        byText(text) {
            return allElements(document.body).find(element => element.textContent === text) || null;
        },
        privacyStatus() {
            return allElements(document.body).find(element => element.getAttribute('aria-live') === 'polite');
        },
        restoreLegacyValues() {
            values.set('logDataAge', '25');
            values.set('logDataInstitution', 'Università');
            values.set('logDataStem', '1');
        }
    };
}

async function settle() {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
}

test('lesson progress discards a pending load when local progress is cleared', async () => {
    const stale = {
        version: 1,
        lessonId: 'lesson-1',
        completedExercises: ['old-answer'],
        manuallyCompleted: true,
        bookmarks: [{ sectionId: 'intro', title: 'Vecchio titolo', url: '#intro' }]
    };
    const harness = lessonHarness({ deferred: true });
    harness.context.LogicLessonProgress.initialize();

    harness.context.LogicAppEvents.emit('privacy:data-clearing');
    harness.context.LogicAppEvents.emit('privacy:data-cleared');
    harness.resolveGet(stale);
    await settle();

    assert.equal(harness.puts.length, 0);
    assert.equal(harness.document.getElementById('lessonCompletionButton').disabled, false);
    assert.equal(harness.document.querySelector('.lesson-bookmark-button').textContent, 'Salva segnalibro');
    assert.match(harness.document.getElementById('lessonProgressStatus').textContent, /Esercizi superati: 0/);
});

test('lesson clearing resets rendered state and stores a clean bookmark title', async () => {
    const saved = {
        version: 1,
        lessonId: 'lesson-1',
        visitedAt: Date.now(),
        completedExercises: ['answer-1'],
        manuallyCompleted: true,
        bookmarks: [{ sectionId: 'intro', title: 'Titolo della sezione', url: '#intro' }]
    };
    const harness = lessonHarness({ saved, listed: [saved] });
    harness.context.LogicLessonProgress.initialize();
    await settle();

    const completion = harness.document.getElementById('lessonCompletionButton');
    const bookmark = harness.document.querySelector('.lesson-bookmark-button');
    assert.equal(completion.disabled, true);
    assert.equal(bookmark.textContent, 'Rimuovi segnalibro');

    harness.context.LogicAppEvents.emit('privacy:progress-clearing');
    assert.equal(completion.disabled, false);
    assert.equal(bookmark.textContent, 'Salva segnalibro');
    assert.match(harness.document.getElementById('lessonProgressStatus').textContent, /Esercizi superati: 0/);

    harness.setListed([]);
    harness.context.LogicAppEvents.emit('privacy:progress-cleared');
    bookmark.dispatch('click');
    await settle();

    const latest = harness.puts[harness.puts.length - 1].value;
    assert.equal(latest.bookmarks[0].title, 'Titolo della sezione');
    assert.doesNotMatch(latest.bookmarks[0].title, /segnalibro/i);
});

test('settings announces each privacy clear before awaiting storage deletion', () => {
    const source = fs.readFileSync('scripts/settings.js', 'utf8');
    [
        ['deleteDataButton', "emit('privacy:data-clearing')", 'await appStorage.clearAll()'],
        ['deleteSessionsButton', "emit('privacy:sessions-clearing')", "await appStorage.clearType('sessions')"],
        ['deleteProgressButton', "emit('privacy:progress-clearing')", "await appStorage.clearType('attempts')"]
    ].forEach(([handler, event, deletion]) => {
        const start = source.indexOf(handler + ".addEventListener('click'");
        const eventIndex = source.indexOf(event, start);
        const deletionIndex = source.indexOf(deletion, start);
        assert.ok(start >= 0 && eventIndex > start && deletionIndex > eventIndex, handler);
    });
});

test('settings removes legacy demographics when either related consent is revoked', () => {
    const harness = settingsHarness();
    const demographics = harness.document.getElementById('settingsIncludeDemographics');
    demographics.checked = false;
    demographics.dispatch('change');
    ['logDataAge', 'logDataInstitution', 'logDataStem'].forEach(key => {
        assert.equal(harness.localStorage.getItem(key), null, key);
    });

    harness.restoreLegacyValues();
    const feedback = harness.document.getElementById('settingsAnonymousFeedback');
    feedback.checked = false;
    feedback.dispatch('change');
    ['logDataAge', 'logDataInstitution', 'logDataStem'].forEach(key => {
        assert.equal(harness.localStorage.getItem(key), null, key);
    });
    assert.equal(demographics.checked, false);
});

test('settings always emits cleared and reports failures from privacy deletions', async () => {
    const failure = new Error('storage unavailable');
    const harness = settingsHarness({
        clearAll: async () => { throw failure; },
        clearType: async () => { throw failure; }
    });
    const cases = [
        ['Elimina dati locali', 'privacy:data-clearing', 'privacy:data-cleared', /tutti i dati locali/],
        ['Elimina sessioni', 'privacy:sessions-clearing', 'privacy:sessions-cleared', /tutte le sessioni locali/],
        ['Elimina progressi', 'privacy:progress-clearing', 'privacy:progress-cleared', /tutti i progressi locali/]
    ];

    for (const [label, clearing, cleared, statusPattern] of cases) {
        harness.events.length = 0;
        await harness.byText(label).dispatch('click');
        assert.deepEqual(harness.events, [clearing, cleared]);
        assert.match(harness.privacyStatus().textContent, statusPattern);
        assert.match(harness.privacyStatus().textContent, /Riprova/);
        if (label === 'Elimina dati locali') {
            ['logDataAge', 'logDataInstitution', 'logDataStem'].forEach(key => {
                assert.equal(harness.localStorage.getItem(key), null, key);
            });
        }
    }
});
