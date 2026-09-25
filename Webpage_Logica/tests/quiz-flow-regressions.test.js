const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');

function extractListener(source, marker) {
    const markerIndex = source.indexOf(marker);
    assert.ok(markerIndex >= 0, 'listener non trovato: ' + marker);
    const start = source.indexOf('function', markerIndex);
    const bodyStart = source.indexOf('{', start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error('corpo listener non terminato: ' + marker);
}

test('URL configuration is followed by a counter synchronization', () => {
    const initializationStart = quizSource.lastIndexOf('showIntro();');
    const initialization = quizSource.slice(initializationStart);
    const applyIndex = initialization.indexOf('applyUrlConfiguration();');
    const syncIndex = initialization.indexOf('syncTypeCountTotal();', applyIndex);

    assert.ok(initializationStart >= 0);
    assert.ok(applyIndex >= 0);
    assert.ok(syncIndex > applyIndex);
});

test('spoken mode keeps translation enabled in batch and fallback flows', () => {
    assert.doesNotMatch(quizSource, /questionTypes:\s*spokenlanguageMode\s*\?/);
    assert.doesNotMatch(quizSource, /availableLoaders\s*=\s*state\.spokenlanguage\s*\?/);
    assert.match(quizSource, /questionTypes:\s*currentQuizConfig\.questionTypes/);
    assert.match(quizSource, /LogicQuizConfig\.allowedOperations\(currentQuizConfig\)/);
    assert.match(quizSource, /buildAtomSpokenMap\(parsed\)/);
    assert.match(quizSource, /quizShared\.resolveSpokenMap\(/);
});

test('batch fallback preserves and consumes the configured operation plan', () => {
    const catchStart = quizSource.indexOf('catch (batchErr)');
    const catchEnd = quizSource.indexOf('// Se batch non ha fornito risposta valida', catchStart);
    const catchBlock = quizSource.slice(catchStart, catchEnd);

    assert.ok(catchStart >= 0 && catchEnd > catchStart);
    assert.doesNotMatch(catchBlock, /batchOperationsPlan = \[\]/);
    assert.match(catchBlock, /loadFallbackExercise\(batchCacheIndex\)/);
    assert.match(quizSource, /function loadFallbackExercise\(planIndex\)[\s\S]*?batchOperationsPlan\[normalizedIndex\]/);
    assert.match(quizSource, /resolveFallbackOperation\([\s\S]*?planned && planned\.operation/);
});

test('advancing clears persisted selection and resume restores the original start time', () => {
    assert.match(quizSource, /currentExercise \+= 1;\s*state\.selectedIndex = null;/);
    assert.match(quizSource, /persistSession\(\{ currentIndex: currentExercise, phase: 'check', selectedIndex: null \}\)/);
    assert.match(quizSource, /activeSession = session;\s*quizStartTimestamp = Number\(session\.createdAt\) \|\| Date\.now\(\);/);
});

test('Enter delegates the selected option to the single primary action while Space only selects', () => {
    const keydownStart = quizSource.indexOf("optionsEl.addEventListener('keydown'");
    const keydownEnd = quizSource.indexOf("actionButton.addEventListener('click'", keydownStart);
    const keydownBlock = quizSource.slice(keydownStart, keydownEnd);

    assert.ok(keydownStart >= 0 && keydownEnd > keydownStart);
    assert.match(keydownBlock, /const option = evt\.target\.closest\('\.quiz-option'\)/);
    assert.match(keydownBlock, /evt\.key === 'Enter'/);
    assert.match(keydownBlock, /evt\.stopPropagation\(\)/);
    assert.match(keydownBlock, /if \(evt\.repeat\) return;/);
    assert.match(keydownBlock, /state\.mode === 'check' && state\.selectedIndex === optionIndex && !actionButton\.disabled/);
    assert.match(keydownBlock, /state\.mode === 'next'[\s\S]*?activateQuizPrimaryAction\(\);/);
    assert.match(keydownBlock, /activateQuizPrimaryAction\(\);/);
    assert.match(keydownBlock, /evt\.key === ' '[\s\S]*?selectIndex\(optionIndex, true\)/);
    assert.doesNotMatch(keydownBlock, /actionButton\.click\(\)/);
    assert.doesNotMatch(quizSource, /actionButton\.addEventListener\('keydown'/);
    assert.match(quizSource, /state\.selectedIndex = null;[\s\S]*?renderOptions\(\)/);
    assert.match(quizSource, /function selectIndex\(idx, shouldFocus\)[\s\S]*?actionButton\.disabled = false;/);
});

test('option Enter selects, checks, then advances without bubbling or key-repeat duplicates', () => {
    const state = {
        locked: false,
        mode: 'check',
        selectedIndex: null,
        options: [{}, {}]
    };
    const actionButton = { disabled: true };
    let checks = 0;
    let advances = 0;
    const selections = [];
    const context = {
        state,
        actionButton,
        moveSelection() {},
        selectIndex(index, shouldFocus) {
            selections.push({ index, shouldFocus });
            state.selectedIndex = index;
            actionButton.disabled = false;
        },
        activateQuizPrimaryAction() {
            if (actionButton.disabled) return;
            if (state.mode === 'check') {
                checks += 1;
                state.locked = true;
                state.mode = 'next';
                return;
            }
            if (state.mode === 'next') advances += 1;
        }
    };
    const handler = vm.runInNewContext(
        '(' + extractListener(quizSource, "optionsEl.addEventListener('keydown'") + ')',
        context
    );
    function keyboardEvent(key, index) {
        let prevented = false;
        let propagationStopped = false;
        return {
            event: {
                key,
                repeat: false,
                target: { closest: () => ({ dataset: { index: String(index) } }) },
                preventDefault() { prevented = true; },
                stopPropagation() { propagationStopped = true; }
            },
            wasPrevented: () => prevented,
            wasPropagationStopped: () => propagationStopped
        };
    }

    const firstEnter = keyboardEvent('Enter', 0);
    handler(firstEnter.event);
    assert.equal(firstEnter.wasPrevented(), true);
    assert.equal(firstEnter.wasPropagationStopped(), true);
    assert.deepEqual(selections, [{ index: 0, shouldFocus: true }]);
    assert.equal(checks, 0);

    const secondEnter = keyboardEvent('Enter', 0);
    handler(secondEnter.event);
    assert.equal(secondEnter.wasPrevented(), true);
    assert.equal(secondEnter.wasPropagationStopped(), true);
    assert.equal(checks, 1);

    const repeatedEnter = keyboardEvent('Enter', 0);
    repeatedEnter.event.repeat = true;
    handler(repeatedEnter.event);
    assert.equal(checks, 1);
    assert.equal(advances, 0);

    const nextEnter = keyboardEvent('Enter', 0);
    handler(nextEnter.event);
    assert.equal(advances, 1);

    state.locked = false;
    state.mode = 'check';
    state.selectedIndex = 0;
    actionButton.disabled = false;
    const enterOnAnotherOption = keyboardEvent('Enter', 1);
    handler(enterOnAnotherOption.event);
    assert.equal(checks, 1);
    assert.equal(advances, 1);
    assert.deepEqual(selections.at(-1), { index: 1, shouldFocus: true });

    const space = keyboardEvent(' ', 1);
    handler(space.event);
    assert.equal(space.wasPrevented(), true);
    assert.equal(checks, 1);
    assert.equal(advances, 1);
});

test('primary action keeps native Enter activation and advances exactly once in next mode', () => {
    assert.doesNotMatch(quizSource, /actionButton\.addEventListener\('keydown'/);
    assert.match(quizSource, /actionButton\.addEventListener\('click', activateQuizPrimaryAction\)/);

    const state = { mode: 'next', selectedIndex: 1 };
    let currentExercise = 1;
    const totalExercises = 3;
    let titleUpdates = 0;
    let loads = 0;
    const persisted = [];
    const handler = vm.runInNewContext(
        '(' + extractListener(quizSource, 'function activateQuizPrimaryAction') + ')',
        {
            state,
            actionButton: { disabled: false },
            currentExercise,
            totalExercises,
            updateTestTitle() { titleUpdates += 1; },
            persistSession(value) { persisted.push(value); },
            loadExercise() { loads += 1; },
            showCompletion() { throw new Error('non deve completare prima dell’ultima domanda'); },
            checkAnswer() { throw new Error('non deve ricontrollare una risposta già verificata'); }
        }
    );

    handler();

    assert.equal(state.selectedIndex, null);
    assert.equal(titleUpdates, 1);
    assert.equal(loads, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(persisted)), [
        { currentIndex: 2, phase: 'check', selectedIndex: null }
    ]);

    let completions = 0;
    const finalHandler = vm.runInNewContext(
        '(' + extractListener(quizSource, 'function activateQuizPrimaryAction') + ')',
        {
            state: { mode: 'next' },
            actionButton: { disabled: false },
            currentExercise: 3,
            totalExercises: 3,
            showCompletion() { completions += 1; },
            checkAnswer() { throw new Error('non deve ricontrollare la risposta finale'); },
            updateTestTitle() { throw new Error('non deve caricare una domanda oltre il totale'); },
            persistSession() {},
            loadExercise() {}
        }
    );
    finalHandler();
    assert.equal(completions, 1);
});

test('checking from an option moves focus to the next-question button before another Enter', () => {
    const start = quizSource.indexOf('function checkAnswer()');
    const end = quizSource.indexOf('function renderReview()', start);
    const checkBlock = quizSource.slice(start, end);

    assert.ok(start >= 0 && end > start);
    assert.match(checkBlock, /const optionHadKeyboardFocus = optionsEl\.contains\(document\.activeElement\)/);
    assert.match(checkBlock, /setRenderedOptionsLocked\(true\);[\s\S]*?state\.mode = 'next';[\s\S]*?if \(optionHadKeyboardFocus && !actionButton\.disabled\) \{\s*actionButton\.focus\(\)/);
});

test('global Enter advances from the active quiz but ignores native controls and handled events', () => {
    assert.match(quizSource, /a\[href\], summary, button:not\(\.quiz-option\)/);
    assert.match(quizSource, /\[role="button"\]:not\(\.quiz-option\)/);

    const state = { mode: 'next' };
    const actionButton = { disabled: false };
    const testEl = { hidden: false };
    let activations = 0;
    const handler = vm.runInNewContext(
        '(' + extractListener(quizSource, "document.addEventListener('keydown'") + ')',
        {
            state,
            actionButton,
            testEl,
            activateQuizPrimaryAction() { activations += 1; }
        }
    );

    function eventFor(overrides) {
        let prevented = false;
        return {
            event: {
                key: 'Enter',
                defaultPrevented: false,
                repeat: false,
                target: { closest: () => null },
                preventDefault() { prevented = true; },
                ...(overrides || {})
            },
            wasPrevented: () => prevented
        };
    }

    const bodyEnter = eventFor();
    handler(bodyEnter.event);
    assert.equal(bodyEnter.wasPrevented(), true);
    assert.equal(activations, 1);

    handler(eventFor({ defaultPrevented: true }).event);
    handler(eventFor({ repeat: true }).event);
    handler(eventFor({ target: { closest: () => ({ tagName: 'INPUT' }) } }).event);
    handler(eventFor({ target: { closest: selector => selector.includes('summary') ? { tagName: 'SUMMARY' } : null } }).event);
    handler(eventFor({ target: { closest: selector => selector.includes('[role="button"]') ? { role: 'button' } : null } }).event);
    assert.equal(activations, 1);

    testEl.hidden = true;
    handler(eventFor().event);
    assert.equal(activations, 1);
});

test('exercise markup labels the radio group and exposes a disabled primary check action initially', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    assert.match(html, /id="quizOptions"[^>]*role="radiogroup"[^>]*aria-labelledby="quizQuestion"/);
    assert.doesNotMatch(html, /id="quizOptions"[^>]*tabindex=/);
    assert.match(html, /id="quizActionButton"[^>]*disabled>Controlla la risposta<\/button>/);
});

test('exercise page restores the compact configuration without losing accessibility fixes', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    const css = fs.readFileSync('styles/quiz.css', 'utf8');
    assert.match(html, /id="quizIntroTitle">Impostazioni<\/h1>/);
    assert.doesNotMatch(html, /quiz-config-sections|quiz-config-section-heading|quiz-choice-card/);
    assert.match(html, /id="quizReviewNav"[^>]*class="rounded-box lesson-nav"/);
    ['Modalità:', 'Difficoltà:', 'Valore di verità', 'Formule di riferimento'].forEach(label => {
        assert.match(html, new RegExp(label));
    });
    assert.doesNotMatch(html, /Profilo:/);
    assert.equal((html.match(/Modalità:/g) || []).length, 1);
    assert.match(html, /<input id="quizMode" type="hidden" value="practice">/);
    assert.match(html, /<output id="quizQuestionCount"[^>]*aria-live="polite"[^>]*>10<\/output>/);
    assert.doesNotMatch(html, /<input id="quizQuestionCount"/);
    assert.match(html, /<fieldset id="quizQuestionTypes" class="quiz-config-group">/);
    assert.match(html, /id="quizStartButton"[^>]*>Inizia il quiz<\/button>/);
    assert.match(css, /\.quiz-box\s*\{[\s\S]*?max-width:\s*760px;[\s\S]*?margin:\s*24px auto;/);
    assert.match(css, /\.quiz-review-title\s*\{[\s\S]*?display:\s*flex;[\s\S]*?gap:\s*6px;/);
    assert.match(css, /\.quiz-review-answer-row\s*\{[\s\S]*?display:\s*flex;[\s\S]*?gap:\s*6px;/);
    assert.match(css, /lesson-radio-option:has\(\.lesson-radio-input:focus-visible\)/);
    assert.match(css, /body\.quiz-formulas-mode\s*\{[\s\S]*?padding-inline:\s*64px;/);
    assert.match(css, /\.quiz-question-total\s*\{[\s\S]*?font-weight:\s*700;/);
});

test('responsive quiz layouts keep existing controls contained and non-overlapping', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    const quizCss = fs.readFileSync('styles/quiz.css', 'utf8');
    const componentsCss = fs.readFileSync('styles/components.css', 'utf8');
    const reviewStart = html.indexOf('<div id="quizReviewNav"');
    const reviewEnd = html.indexOf('</div>', reviewStart);
    const reviewMarkup = html.slice(reviewStart, reviewEnd);

    assert.equal((reviewMarkup.match(/class="lesson-nav-btn"/g) || []).length, 7);
    assert.match(componentsCss, /\.lesson-nav\s*\{[\s\S]*?display:\s*flex;[\s\S]*?flex-wrap:\s*wrap/);
    assert.match(componentsCss, /\.lesson-nav-btn\s*\{[\s\S]*?position:\s*static;[\s\S]*?transform:\s*none/);
    assert.match(componentsCss, /#quizReviewNav\s*\{[\s\S]*?display:\s*flex;[\s\S]*?flex-wrap:\s*wrap/);
    assert.match(componentsCss, /#quizReviewNav \.quiz-export-summary\s*\{[\s\S]*?flex:\s*0 0 100%/);
    assert.match(componentsCss, /#quizReviewNav \.lesson-nav-btn\s*\{[\s\S]*?flex:\s*1 1 11rem;[\s\S]*?min-width:\s*0/);
    assert.match(quizCss, /\.quiz-test-layout\.with-formulas\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*minmax\(0, 56fr\) minmax\(0, 44fr\)/);
    assert.match(quizCss, /\.quiz-formulas-pane\s*\{[\s\S]*?min-width:\s*0/);
    assert.match(quizCss, /#quizActionButton\s*\{[\s\S]*?margin:\s*12px auto 0/);
    assert.match(quizCss, /\.quiz-config-group label\s*\{[\s\S]*?grid-template-columns:\s*auto minmax\(0, 1fr\) minmax\(4rem, 5rem\)/);
    assert.match(quizCss, /@media \(max-width:\s*380px\)[\s\S]*?\.quiz-config-group label\s*\{[\s\S]*?grid-template-columns:\s*auto minmax\(0, 1fr\)/);
    assert.match(quizCss, /@media \(max-width:\s*380px\)[\s\S]*?\[data-quiz-type-count\]\s*\{[\s\S]*?grid-column:\s*2/);
});

test('completion removes the formulas split after hiding the test', () => {
    const start = quizSource.indexOf('function showCompletion()');
    const end = quizSource.indexOf('// Ripristina stato iniziale', start);
    const block = quizSource.slice(start, end);
    const hideTest = block.indexOf('testEl.hidden = true');
    const applyLayout = block.indexOf('applyFormulasLayout()', hideTest);
    const renderReview = block.indexOf('renderReview()', hideTest);

    assert.ok(start >= 0 && end > start);
    assert.ok(hideTest >= 0);
    assert.ok(applyLayout > hideTest);
    assert.ok(renderReview > applyLayout);
});

test('quiz timer remains absent from the configurator while it has the hidden attribute', () => {
    const css = fs.readFileSync('styles/quiz.css', 'utf8');
    assert.match(css, /\.quiz-timer\[hidden\]\s*\{\s*display:\s*none;\s*\}/);
});

test('quiz demographics avoid localStorage and cleared sessions reset the resume state', () => {
    assert.doesNotMatch(quizSource, /localStorage\.(?:getItem|setItem|removeItem)\(['"]logData/);
    assert.match(quizSource, /LogicQuizReport\.readDemographics\(\{[\s\S]*?age:\s*logDataAgeInput/);
    assert.match(quizSource, /LogicAppEvents\.on\('privacy:sessions-clearing', clearActiveSessionState\)/);
    assert.match(quizSource, /LogicAppEvents\.on\('privacy:sessions-cleared', clearActiveSessionState\)/);
    assert.match(quizSource, /LogicAppEvents\.on\('privacy:data-clearing', clearActiveSessionState\)/);
    assert.match(quizSource, /LogicAppEvents\.on\('privacy:data-cleared', clearActiveSessionState\)/);
    assert.match(quizSource, /function clearActiveSessionState\(\)[\s\S]*?activeSession = null;[\s\S]*?resumePanelEl\.hidden = true;/);
});

test('feedback is optional, retryable and accessible without changing report construction', () => {
    const html = fs.readFileSync('esercizi/esercitazione.html', 'utf8');
    const css = fs.readFileSync('styles/quiz.css', 'utf8');
    const reviewStart = html.indexOf('<div id="quizReview"');
    const demographicsStart = html.indexOf('id="quizLogDataSection"');

    assert.ok(reviewStart >= 0 && demographicsStart > reviewStart);
    assert.match(html, /id="quizLogDataSection"[^>]*aria-labelledby="quizLogDataLegend"[^>]*hidden/);
    assert.match(html, /<fieldset>\s*<legend id="quizLogDataLegend">Dati demografici facoltativi<\/legend>/);
    assert.match(quizSource, /document\.createElement\('fieldset'\)/);
    assert.match(quizSource, /document\.createElement\('legend'\)/);
    assert.match(quizSource, /statusLine\.setAttribute\('role', 'status'\)/);
    assert.match(quizSource, /Invia la valutazione e mostra i risultati/);
    assert.match(quizSource, /Salta e mostra i risultati/);
    assert.match(quizSource, /Riprova l\\'invio e mostra i risultati/);
    assert.match(quizSource, /skipButton\.addEventListener\('click',[\s\S]*?showReviewPage\(\)/);
    assert.match(quizSource, /if \(!ok\) \{[\s\S]*?submitButton\.disabled = false;[\s\S]*?submitButton\.focus\(\)/);
    assert.match(quizSource, /if \(!validateOptionalDemographics\(statusNode\)\) return;[\s\S]*?submitReviewReport\(buildReviewReport\(feedbackValues\)\)/);
    assert.match(quizSource, /function validateOptionalDemographics\(statusNode\)[\s\S]*?aria-invalid[\s\S]*?logDataAgeInput\.focus\(\)[\s\S]*?return false;/);
    assert.doesNotMatch(quizSource, /function validateLogDataSettings/);
    assert.match(quizSource, /LogicQuizReport\.buildReport\(\{[\s\S]*?feedbackFields: FEEDBACK_FIELDS/);
    assert.match(css, /\.quiz-feedback-radio-choice\s*\{[\s\S]*?min-width:\s*44px;[\s\S]*?min-height:\s*44px;/);
    assert.match(css, /html:has\(\.quiz-feedback-panel\),\s*body:has\(\.quiz-feedback-panel\)\s*\{\s*overflow-x:\s*clip;/);
    assert.match(css, /\.quiz-feedback-radio-group\s*\{[\s\S]*?grid-template-columns:\s*repeat\(auto-fit, minmax\(44px, 1fr\)\);[\s\S]*?inline-size:\s*100%;[\s\S]*?min-inline-size:\s*0;[\s\S]*?overflow-x:\s*auto;/);
    assert.match(css, /\.quiz-feedback-actions \.btn-wide\s*\{[\s\S]*?min-height:\s*44px;/);
    assert.match(css, /\.quiz-feedback-note,[\s\S]*?\.quiz-feedback-question-hint\s*\{[\s\S]*?text-align:\s*left;/);
    assert.match(css, /\.quiz-feedback-intro,[\s\S]*?\.quiz-feedback-status\s*\{[\s\S]*?text-align:\s*left;/);
    assert.match(css, /@media \(max-width: 560px\)[\s\S]*?#quizReviewTitle\s*\{[\s\S]*?overflow-wrap:\s*anywhere;[\s\S]*?\.quiz-feedback-actions\s*\{[\s\S]*?flex-direction:\s*column;/);
});

test('privacy revocation clears transient demographics and exits an open feedback panel', () => {
    const syncStart = quizSource.indexOf('function syncPrivacyVisibility()');
    const syncEnd = quizSource.indexOf('function buildApiUrl', syncStart);
    const syncBlock = quizSource.slice(syncStart, syncEnd);

    assert.ok(syncStart >= 0 && syncEnd > syncStart);
    assert.match(syncBlock, /if \(!includeDemographics\) \{[\s\S]*?logDataAgeInput\.value = '';[\s\S]*?logDataInstitutionSelect\.value = '';[\s\S]*?logDataStemSelect\.value = '';/);
    assert.match(syncBlock, /if \(onFeedbackPage && !window\.LogicPrivacy\.canSendFeedback\(\)\) \{[\s\S]*?showReviewPage\(\);[\s\S]*?return;/);
    assert.match(quizSource, /LogicAppEvents\.on\('privacy:changed', syncPrivacyVisibility\)/);
});

test('lesson section IDs match their case-sensitive filenames', () => {
    ['4', '5'].forEach(number => {
        const html = fs.readFileSync('lezioni/lezione-' + number + '.html', 'utf8');
        assert.match(html, new RegExp('<body data-lesson-id="lesson-' + number + '">'));
        assert.match(html, new RegExp('<section id="lezione-' + number + '">'));
    });
});
