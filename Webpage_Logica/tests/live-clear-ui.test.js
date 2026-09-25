const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

class FakeElement {
    constructor(id) {
        this.id = id || '';
        this.children = [];
        this.listeners = new Map();
        this.hidden = false;
        this.disabled = false;
        this.value = '';
        this._textContent = '';
    }

    set textContent(value) {
        this._textContent = String(value);
        this.children = [];
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    set innerHTML(value) {
        this._textContent = String(value);
        this.children = [];
    }

    get innerHTML() {
        return this._textContent;
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    addEventListener(name, listener) {
        this.listeners.set(name, listener);
    }

    dispatch(name) {
        if (name === 'click' && this.disabled) return;
        const listener = this.listeners.get(name);
        if (listener) listener({ target: this });
    }

    querySelector() {
        return null;
    }
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => {
        resolve = resolvePromise;
        reject = rejectPromise;
    });
    return { promise, reject, resolve };
}

function createDocument(ids) {
    const elements = new Map(ids.map(id => [id, new FakeElement(id)]));
    return {
        elements,
        document: {
            readyState: 'complete',
            getElementById(id) { return elements.get(id) || null; },
            createElement() { return new FakeElement(); }
        }
    };
}

function load(context, files) {
    context.window = context;
    vm.createContext(context);
    files.forEach(file => vm.runInContext(fs.readFileSync(file, 'utf8'), context));
    return context;
}

async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
}

test('dashboard clears immediately, ignores a stale load and exports only current attempts', async () => {
    const ids = [
        'dashboardPeriod', 'dashboardType', 'dashboardDifficulty', 'dashboardSummary',
        'dashboardChart', 'dashboardTableBody', 'dashboardDifficultyChart',
        'dashboardDifficultyTableBody', 'dashboardEmpty', 'dashboardExportJson',
        'dashboardExportCsv', 'dashboardPrint', 'dashboardDownloadChart',
        'dashboardSummarySection', 'dashboardDifficultySection', 'dashboardTypeSection'
    ];
    const { document, elements } = createDocument(ids);
    const pendingLists = [];
    let exportedAttempts = null;
    const context = {
        document,
        LogicAppStorage: { instance: { list() {
            const pending = deferred();
            pendingLists.push(pending);
            return pending.promise;
        } } },
        LogicLearningMetrics: { aggregate(attempts) {
            const correct = attempts.filter(item => item.correct).length;
            const accuracy = attempts.length ? correct / attempts.length : 0;
            return {
                total: attempts.length,
                correct,
                accuracy,
                medianElapsedMs: 0,
                byType: attempts.length ? [{
                    type: attempts[0].type, total: attempts.length, correct, accuracy, medianElapsedMs: 0
                }] : [],
                byDifficulty: attempts.length ? [{
                    difficulty: attempts[0].difficulty, total: attempts.length, correct, accuracy
                }] : []
            };
        } },
        LogicCharts: {
            renderBars(container, series) { container.series = series; },
            downloadSvg() {}
        },
        LogicResultsExport: {
            downloadJson(payload) { exportedAttempts = payload.attempts; },
            downloadCsv(attempts) { exportedAttempts = attempts; }
        },
        print() {}
    };
    load(context, ['scripts/app-events.js', 'scripts/dashboard.js']);

    assert.equal(pendingLists.length, 1);
    context.LogicAppEvents.emit('privacy:progress-clearing');
    assert.equal(elements.get('dashboardSummary').children[0].children[0].textContent, '0');
    assert.equal(elements.get('dashboardSummarySection').hidden, true);
    assert.equal(elements.get('dashboardDifficultySection').hidden, true);
    assert.equal(elements.get('dashboardTypeSection').hidden, true);
    assert.equal(elements.get('dashboardExportJson').disabled, true);
    assert.match(elements.get('dashboardEmpty').textContent, /Non ci sono ancora tentativi salvati/);
    elements.get('dashboardExportJson').dispatch('click');
    assert.equal(exportedAttempts, null);

    pendingLists[0].resolve([{ type: 'translation', difficulty: 'easy', correct: true }]);
    await flushPromises();
    assert.equal(elements.get('dashboardSummary').children[0].children[0].textContent, '0');

    context.LogicAppEvents.emit('privacy:progress-cleared');
    assert.equal(pendingLists.length, 2);
    const current = [{ type: 'equivalence', difficulty: 'hard', correct: false }];
    pendingLists[1].resolve(current);
    await flushPromises();
    assert.equal(elements.get('dashboardSummarySection').hidden, false);
    assert.equal(elements.get('dashboardDifficultySection').hidden, false);
    assert.equal(elements.get('dashboardTypeSection').hidden, false);
    assert.equal(elements.get('dashboardExportJson').disabled, false);
    assert.equal(elements.get('dashboardDownloadChart').disabled, false);
    assert.equal(elements.get('dashboardTableBody').children[0].children[0].textContent, 'Equivalenze');
    assert.equal(elements.get('dashboardDifficultyTableBody').children[0].children[0].textContent, 'Difficile');
    assert.equal(elements.get('dashboardChart').series[0].label, 'Equivalenze');
    assert.equal(elements.get('dashboardDifficultyChart').series[0].label, 'Difficile');

    elements.get('dashboardType').value = 'translation';
    elements.get('dashboardType').dispatch('change');
    assert.equal(elements.get('dashboardSummarySection').hidden, true);
    assert.equal(elements.get('dashboardExportCsv').disabled, true);
    assert.match(elements.get('dashboardEmpty').textContent, /Nessun tentativo corrisponde ai filtri selezionati/);
    elements.get('dashboardType').value = '';
    elements.get('dashboardType').dispatch('change');
    elements.get('dashboardExportCsv').dispatch('click');
    assert.deepEqual(Array.from(exportedAttempts, item => item.type), ['equivalence']);
    assert.equal(elements.get('dashboardTableBody').children.length, 1);
    assert.equal(elements.get('dashboardDifficultyTableBody').children.length, 1);

    context.LogicAppEvents.emit('privacy:data-clearing');
    assert.equal(elements.get('dashboardTableBody').children.length, 0);
    assert.equal(elements.get('dashboardDifficultyTableBody').children.length, 0);
    assert.equal(elements.get('dashboardChart').series.length, 0);
    assert.equal(elements.get('dashboardDifficultyChart').series.length, 0);
    assert.equal(elements.get('dashboardSummarySection').hidden, true);
    assert.equal(elements.get('dashboardExportJson').disabled, true);
    elements.get('dashboardExportJson').dispatch('click');
    assert.deepEqual(Array.from(exportedAttempts, item => item.type), ['equivalence']);
});

test('error notebook stays empty when an initial stale list resolves after data clearing', async () => {
    const ids = [
        'errorNotebookList', 'errorNotebookEmpty', 'errorTypeFilter', 'errorStateFilter',
        'errorOrderFilter', 'errorPeriodFilter', 'clearErrorNotebook'
    ];
    const { document, elements } = createDocument(ids);
    const pendingLists = [];
    const storage = { clearType: async () => true };
    const context = {
        document,
        LogicAppStorage: { instance: storage },
        LogicErrorNotebook: { create() {
            return {
                list() {
                    const pending = deferred();
                    pendingLists.push(pending);
                    return pending.promise;
                },
                remove: async () => true,
                setReviewState: async () => true
            };
        } }
    };
    load(context, ['scripts/app-events.js', 'scripts/error-notebook-page.js']);

    context.LogicAppEvents.emit('privacy:data-clearing');
    assert.equal(elements.get('errorNotebookList').children.length, 0);
    assert.equal(elements.get('errorNotebookEmpty').hidden, false);

    pendingLists[0].resolve([{
        errorId: 'stale', type: 'translation', difficulty: 'easy', question: 'stale',
        selectedAnswer: 'a', correctAnswer: 'b', count: 1, lastSeenAt: Date.now(), reviewState: 'review'
    }]);
    await flushPromises();
    assert.equal(elements.get('errorNotebookList').children.length, 0);

    context.LogicAppEvents.emit('privacy:data-cleared');
    assert.equal(pendingLists.length, 2);
    pendingLists[1].resolve([]);
    await flushPromises();
    assert.equal(elements.get('errorNotebookList').children.length, 0);
    assert.equal(elements.get('errorNotebookEmpty').hidden, false);
});

test('home progress resets live and cannot be repopulated by a stale IndexedDB read', async () => {
    const { document, elements } = createDocument(['indexLessonProgress']);
    const pendingLists = [];
    const context = {
        document,
        LogicAppStorage: { instance: { list() {
            const pending = deferred();
            pendingLists.push(pending);
            return pending.promise;
        } } }
    };
    load(context, ['scripts/app-events.js', 'scripts/index-progress.js']);

    context.LogicAppEvents.emit('privacy:progress-clearing');
    assert.equal(elements.get('indexLessonProgress').textContent, 'Lezioni completate: 0 su 6.');

    pendingLists[0].resolve([{
        manuallyCompleted: true,
        bookmarks: [{ title: 'Segnalibro vecchio', url: './lezioni/lezione-1.html' }]
    }]);
    await flushPromises();
    assert.equal(elements.get('indexLessonProgress').textContent, 'Lezioni completate: 0 su 6.');

    context.LogicAppEvents.emit('privacy:progress-cleared');
    assert.equal(pendingLists.length, 2);
    pendingLists[1].resolve([]);
    await flushPromises();
    assert.equal(elements.get('indexLessonProgress').textContent, 'Lezioni completate: 0 su 6.');
    assert.equal(elements.get('indexLessonProgress').children.length, 0);
});
