const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadScript(file) {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
    return context;
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

class FakeQuizOption {
    constructor() {
        this.attributes = {};
        this.className = '';
        this.classList = {
            toggle: (name, enabled) => {
                const classes = new Set(this.className.split(/\s+/).filter(Boolean));
                if (enabled) classes.add(name);
                else classes.delete(name);
                this.className = Array.from(classes).join(' ');
            },
            remove: (...names) => {
                const classes = new Set(this.className.split(/\s+/).filter(Boolean));
                names.forEach(name => classes.delete(name));
                this.className = Array.from(classes).join(' ');
            }
        };
        this.dataset = {};
        this.tabIndex = 0;
        this.focused = false;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    getAttribute(name) {
        return this.attributes[name] ?? null;
    }

    focus() {
        this.focused = true;
    }
}

class FakeQuizOptionsContainer {
    constructor() {
        this.children = [];
        this._innerHTML = '';
    }

    set innerHTML(value) {
        this._innerHTML = String(value);
        if (value === '') this.children = [];
    }

    appendChild(child) {
        this.children.push(child);
    }

    querySelectorAll(selector) {
        return selector === '.quiz-option' ? this.children : [];
    }
}

test('quiz state creates independent defaults and reads exercise preferences', () => {
    const context = loadScript('scripts/quiz-state.js');
    const first = context.LogicQuizState.create({
        isExercisesPage: true,
        highlightKey: 'highlight',
        parensKey: 'parens',
        readSetting: key => key === 'highlight'
    });
    const second = context.LogicQuizState.create({});

    assert.equal(first.highlightAtoms, true);
    assert.equal(first.differentiateParens, false);
    first.options.push({ text: 'p' });
    assert.equal(second.options.length, 0);
});

test('quiz renderer implements one roving tab stop without selecting an answer by default', () => {
    const context = {
        document: { createElement: () => new FakeQuizOption() }
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/quiz-renderer.js', 'utf8'), context);
    const state = {
        options: ['p', 'q', 'r'],
        selectedIndex: null,
        spokenlanguage: false,
        exerciseKind: 'equivalence'
    };
    const optionsEl = new FakeQuizOptionsContainer();
    const renderer = context.LogicQuizRenderer.create({
        state,
        infoEl: { hidden: true, innerHTML: '' },
        optionsEl,
        statusEl: { textContent: '' },
        colorizeAtomsInText: value => value,
        transformFormula: value => value,
        getOptionFormula: value => value
    });

    renderer.renderOptions();
    assert.deepEqual(optionsEl.children.map(option => option.tabIndex), [0, -1, -1]);
    assert.deepEqual(optionsEl.children.map(option => option.getAttribute('aria-checked')), ['false', 'false', 'false']);

    state.selectedIndex = 2;
    renderer.updateSelectionVisual({ focusIndex: 2, focus: true });
    assert.deepEqual(optionsEl.children.map(option => option.tabIndex), [-1, -1, 0]);
    assert.equal(optionsEl.children[2].getAttribute('aria-checked'), 'true');
    assert.equal(optionsEl.children[2].focused, true);
});

test('spoken atom mapping is stable across reloads and atom order', () => {
    const context = loadScript('scripts/quiz-shared.js');
    const names = ['Luca', 'Giulia', 'Sofia'];
    const actions = ['corre', 'salta', 'nuota'];
    const first = context.quizShared.buildStableSpokenMap(['q', 'P', 'r'], names, actions);
    const resumed = context.quizShared.buildStableSpokenMap(['r', 'p', 'Q'], names, actions);

    assert.deepEqual(JSON.parse(JSON.stringify(resumed)), JSON.parse(JSON.stringify(first)));
    assert.deepEqual(Object.keys(first), ['p', 'q', 'r']);
    assert.ok(Object.values(first).every(entry => entry.nome && entry.azione));
});

test('spoken translation mapping follows the API legend and falls back only when absent', () => {
    const context = loadScript('scripts/quiz-shared.js');
    const names = ['Nome fallback'];
    const actions = ['corre', 'apre la porta', 'salta'];
    const propositional = context.quizShared.resolveSpokenMap(
        ['P = Luca corre', 'Q = Giulia apre la porta'],
        ['p', 'q', 'r'],
        names,
        actions
    );
    const quantified = context.quizShared.resolveSpokenMap(
        ['A(x) = x salta'],
        ['a'],
        names,
        actions
    );

    assert.deepEqual(JSON.parse(JSON.stringify(propositional)), {
        p: { nome: 'Luca', azione: 'corre' },
        q: { nome: 'Giulia', azione: 'apre la porta' }
    });
    assert.equal(Object.hasOwn(propositional, 'r'), false);
    assert.deepEqual(JSON.parse(JSON.stringify(quantified)), {
        a: { nome: 'persona', azione: 'salta' }
    });

    const fallback = context.quizShared.resolveSpokenMap([], ['p'], names, actions);
    assert.equal(fallback.p.nome, 'Nome fallback');
});

test('quiz normalizers validate and standardize truth-value payloads', () => {
    const context = loadScript('scripts/quiz-normalizers.js');
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: value => value,
        normalizeGenerationSteps: value => Array.isArray(value) ? value : [],
        extractWrongStepsMap: () => ({})
    });
    const result = normalizers.normalizeTruthValueResult({
        result: {
            question_id: 'question-stable',
            information: ['p-true', 'q-false', 'r-true'],
            options: [
                { formula_prolog: 'p', is_true: true },
                { formula_prolog: 'q', is_true: false },
                { formula_prolog: 'r', is_true: false },
                { formula_prolog: 'and(p,q)', is_true: false }
            ]
        }
    });

    assert.equal(result.kind, 'truth-value');
    assert.equal(result.questionId, 'question-stable');
    assert.equal(result.options.filter(option => option.correct).length, 1);
    assert.equal(result.info[0], 'p è vero');
});

test('quiz normalizers preserve construction traces on every option', () => {
    const constructionContext = loadScript('scripts/formula-construction.js');
    const context = loadScript('scripts/quiz-normalizers.js');
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: value => value,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({}),
        normalizeConstruction: constructionContext.LogicFormulaConstruction.normalize,
        buildConstructionFromFormula: constructionContext.LogicFormulaConstruction.buildFromFormula,
        buildQuantifiedConstruction: constructionContext.LogicFormulaConstruction.buildQuantifiedTrace
    });
    const result = normalizers.normalizeTranslationResult({
        result: {
            question_text: 'Traduci la frase',
            info: [],
            options: [
                { formula: 'and(P,Q)', is_correct: true },
                { formula: 'or(P,Q)', is_correct: false }
            ]
        }
    });

    assert.equal(result.options.length, 2);
    assert.ok(result.options.every(option => option.construction));
    assert.equal(result.options.find(option => option.correct).construction.final_formula_prolog, 'and(P,Q)');
});

test('quantifier-negation options bind every generated atom to x', () => {
    const constructionContext = loadScript('scripts/formula-construction.js');
    const context = loadScript('scripts/quiz-normalizers.js');
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: value => value,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({}),
        normalizeConstruction: constructionContext.LogicFormulaConstruction.normalize,
        buildConstructionFromFormula: constructionContext.LogicFormulaConstruction.buildFromFormula,
        buildQuantifiedConstruction: constructionContext.LogicFormulaConstruction.buildQuantifiedTrace
    });

    const result = normalizers.buildQuantifiedNegationOptions(
        '∀',
        'p ∧ (q → r)',
        'and(p,imp(q,r))'
    );

    assert.equal(result.question, 'Qual\'è la negazione di "∀x (P(x) ∧ (Q(x) → R(x)))"?');
    assert.deepEqual(Array.from(result.options, option => option.text), [
        '∃x ¬(P(x) ∧ (Q(x) → R(x)))',
        '∀x ¬(P(x) ∧ (Q(x) → R(x)))',
        '∃x (P(x) ∧ (Q(x) → R(x)))'
    ]);
    assert.equal(result.options.filter(option => option.correct).length, 1);
    assert.ok(result.options.every(option => !/\b[pqr]\b(?!\s*\()/i.test(option.text)));

    const correct = result.options.find(option => option.correct);
    assert.deepEqual(
        Array.from(correct.construction.steps, step => step.kind),
        ['predicate', 'predicate', 'predicate', 'binary', 'binary', 'unary', 'quantifier']
    );
    assert.equal(correct.construction.steps.at(-1).details.bound_variable, 'x');
});

test('spoken quantifier negation derives question, options and construction from a positive AST base', () => {
    const constructionContext = loadScript('scripts/formula-construction.js');
    const sharedContext = loadScript('scripts/quiz-shared.js');
    const context = loadScript('scripts/quiz-normalizers.js');
    const source = 'not(and(not(not(p)),not(or(q,r))))';
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: sharedContext.quizShared.prologToLogical,
        removeFormulaNegations: sharedContext.quizShared.removeFormulaNegations,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({}),
        normalizeConstruction: constructionContext.LogicFormulaConstruction.normalize,
        buildConstructionFromFormula: constructionContext.LogicFormulaConstruction.buildFromFormula,
        buildQuantifiedConstruction: constructionContext.LogicFormulaConstruction.buildQuantifiedTrace
    });

    assert.equal(sharedContext.quizShared.removeFormulaNegations(source), 'and(p,or(q,r))');

    const spoken = normalizers.buildQuantifiedNegationOptions(
        '∀',
        sharedContext.quizShared.prologToLogical(source),
        source,
        true
    );
    assert.equal(spoken.question, 'Qual\'è la negazione di "∀x (P(x) ∧ (Q(x) ∨ R(x)))"?');
    assert.deepEqual(Array.from(spoken.options, option => option.text), [
        '∃x ¬(P(x) ∧ (Q(x) ∨ R(x)))',
        '∀x ¬(P(x) ∧ (Q(x) ∨ R(x)))',
        '∃x (P(x) ∧ (Q(x) ∨ R(x)))'
    ]);
    spoken.options.forEach(option => {
        assert.equal(option.construction.final_formula_prolog, option.text);
        assert.ok(option.construction.steps.every(step => !/not\(not\(/.test(step.result_prolog)));
    });

    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const spokenContext = {
        state: { spokenlanguage: true },
        atomSpokenMap: {
            p: { nome: 'Sofia', azione: 'ascolta' },
            q: { nome: 'Chiara', azione: 'corre' },
            r: { nome: 'Martina', azione: 'nuota' }
        },
        normalizeFormulaAtoms: value => String(value || ''),
        extractQuantifiedVariables: value => Array.from(
            String(value || '').matchAll(/[∀∃]\s*([A-Za-z][A-Za-z0-9_]*)/g),
            match => match[1]
        ),
        normalizeAtomLookupKey: value => String(value || '').split('(')[0].trim().toLowerCase(),
        formatSpokenAction: value => String(value || ''),
        pluralizeAction: value => String(value || '')
    };
    const applySpokenTransform = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'applySpokenTransform') + ')',
        spokenContext
    );
    spoken.options.forEach(option => {
        const rendered = applySpokenTransform(option.text);
        assert.doesNotMatch(rendered, /(?:non è vero che\s+){2,}/i);
    });

    const symbolic = normalizers.buildQuantifiedNegationOptions(
        '∀',
        sharedContext.quizShared.prologToLogical(source),
        source,
        false
    );
    assert.match(symbolic.question, /¬¬P\(x\)/);
});

test('legacy spoken exercises show an equivalent formula without repeated negation phrases', () => {
    const shared = loadScript('scripts/quiz-shared.js').quizShared;
    const source = 'not(or(not(not(r)),or(not(p),q)))';
    const normalized = shared.spokenFriendlyPrologFormula(source);
    assert.notEqual(normalized, source);

    function evaluate(node, values) {
        if (node.type === 'var') return Boolean(values[node.name]);
        const args = node.args || [];
        if ((node.name === 'forall' || node.name === 'exists') && args.length === 2) {
            const variable = args[0].name;
            const results = [0, 1].map(person => evaluate(args[1], {
                ...values,
                __bound: { ...(values.__bound || {}), [variable]: person }
            }));
            return node.name === 'forall' ? results.every(Boolean) : results.some(Boolean);
        }
        if (['p', 'q', 'r'].includes(node.name) && args.length === 1) {
            return Boolean(values[node.name + ':' + values.__bound[args[0].name]]);
        }
        if (node.name === 'not') return !evaluate(args[0], values);
        if (node.name === 'and') return evaluate(args[0], values) && evaluate(args[1], values);
        if (node.name === 'or') return evaluate(args[0], values) || evaluate(args[1], values);
        if (node.name === 'imp') return !evaluate(args[0], values) || evaluate(args[1], values);
        if (node.name === 'iff' || node.name === 'equiv') return evaluate(args[0], values) === evaluate(args[1], values);
        throw new Error('Operatore inatteso: ' + node.name);
    }

    [
        source,
        'not(and(not(not(p)),not(or(q,r))))',
        'not(imp(not(p),or(q,r)))',
        'not(iff(not(p),and(q,r)))',
        'not(and(not(not(R(x))),not(or(P(x),Q(x))))',
        'not(forall(x,not(and(P(x),Q(x)))))'
    ].forEach(formula => {
        const originalAst = shared.parsePrologFormula(formula);
        const normalizedAst = shared.parsePrologFormula(shared.spokenFriendlyPrologFormula(formula));
        const quantified = /\([PQR]\(x\)|forall|exists/.test(formula);
        for (let mask = 0; mask < (quantified ? 64 : 8); mask += 1) {
            const values = quantified
                ? Object.fromEntries(['p:0', 'q:0', 'r:0', 'p:1', 'q:1', 'r:1']
                    .map((key, index) => [key, Boolean(mask & (1 << index))]))
                : { p: Boolean(mask & 1), q: Boolean(mask & 2), r: Boolean(mask & 4) };
            if (quantified) values.__bound = { x: 0 };
            assert.equal(evaluate(normalizedAst, values), evaluate(originalAst, values), formula + ', assegnazione ' + mask);
        }
    });

    // È il percorso di display usato dal renderer quiz e dalla revisione:
    // la formula Prolog dell'opzione resta identica nella cache della sessione.
    const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
    const context = {
        state: { spokenlanguage: true },
        quizShared: shared,
        normalizeGenerationSteps: () => [],
        displayFormulaText: value => shared.prologToLogical(value),
        getQuantifiedTraceFormula: () => null,
        atomSpokenMap: {
            p: { nome: 'Sofia', azione: 'ascolta' },
            q: { nome: 'Chiara', azione: 'corre' },
            r: { nome: 'Martina', azione: 'nuota' }
        },
        normalizeFormulaAtoms: value => String(value || ''),
        extractQuantifiedVariables: value => Array.from(
            String(value || '').matchAll(/[∀∃]\s*([A-Za-z][A-Za-z0-9_]*)/g),
            match => match[1]
        ),
        normalizeAtomLookupKey: value => String(value || '').split('(')[0].trim().toLowerCase(),
        formatSpokenAction: value => String(value || ''),
        pluralizeAction: value => String(value || '')
    };
    context.getOptionFormulaSource = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'getOptionFormulaSource') + ')', context
    );
    const getOptionDisplayFormula = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'getOptionDisplayFormula') + ')', context
    );
    const applySpokenTransform = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'applySpokenTransform') + ')', context
    );
    const option = { text: source, correct: true };
    const legacyDisplay = applySpokenTransform(shared.prologToLogical(source));
    assert.match(legacyDisplay, /(?:non è vero che\s+){3}/i);
    const visibleDisplay = applySpokenTransform(getOptionDisplayFormula(option));
    assert.equal(option.text, source);
    assert.doesNotMatch(visibleDisplay, /(?:non è vero che\s+){2,}/i);
    assert.match(visibleDisplay, /Martina nuota/);
    assert.match(visibleDisplay, /Sofia ascolta/);

    const predicateSource = 'not(and(not(not(R(x))),not(or(P(x),Q(x)))))';
    const predicateDisplay = applySpokenTransform(getOptionDisplayFormula({ text: predicateSource }));
    assert.doesNotMatch(predicateDisplay, /(?:non è vero che\s+){2,}/i);
    assert.match(predicateDisplay, /Martina nuota/);

    const quantifiedSource = 'not(forall(x,not(and(P(x),Q(x)))))';
    const quantifiedDisplay = applySpokenTransform(getOptionDisplayFormula({ text: quantifiedSource }));
    assert.doesNotMatch(quantifiedDisplay, /(?:non è vero che\s+){2,}/i);
    assert.match(quantifiedDisplay, /Esiste una persona/i);

    context.displayFormulaText = value => shared.prologToLogical(value);
    const getSpokenQuestionText = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'getSpokenQuestionText') + ')', context
    );
    const question = getSpokenQuestionText({
        kind: 'equivalence',
        question: 'Quale formula è equivalente a "' + shared.prologToLogical(source) + '":',
        questionConstruction: { final_formula_prolog: source }
    });
    assert.doesNotMatch(applySpokenTransform(question), /(?:non è vero che\s+){2,}/i);
    assert.match(question, /¬r/i);
    const cachedQuestion = getSpokenQuestionText({
        kind: 'equivalence',
        question: 'Quale formula è equivalente a "' + shared.prologToLogical(source) + '":',
        imageFormulaSteps: { question: ['p', source] }
    });
    assert.doesNotMatch(applySpokenTransform(cachedQuestion), /(?:non è vero che\s+){2,}/i);

    // Le formule nuove che rispettano già il filtro del generatore non sono riscritte.
    const fresh = 'not(or(p,and(q,r)))';
    assert.equal(shared.spokenFriendlyPrologFormula(fresh), fresh);
    assert.doesNotMatch(
        applySpokenTransform(getOptionDisplayFormula({ text: fresh })),
        /(?:non è vero che\s+){2,}/i
    );

    // Le opzioni locali dei quantificatori erano invece già simboliche nella
    // sessione. Il trace del corpo permette un display equivalente senza
    // riscrivere `option.text` né scartare la sessione.
    const construction = loadScript('scripts/formula-construction.js').LogicFormulaConstruction;
    const normalizer = loadScript('scripts/quiz-normalizers.js').LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: shared.prologToLogical,
        removeFormulaNegations: shared.removeFormulaNegations,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({}),
        normalizeConstruction: construction.normalize,
        buildConstructionFromFormula: construction.buildFromFormula,
        buildQuantifiedConstruction: construction.buildQuantifiedTrace
    });
    const oldQuantifier = normalizer.buildQuantifiedNegationOptions(
        '∀', shared.prologToLogical(source), source, false
    );
    context.prologToLogical = shared.prologToLogical;
    context.shouldKeepRawFormula = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'shouldKeepRawFormula') + ')', context
    );
    context.normalizeFormulaAtoms = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'normalizeFormulaAtoms') + ')', context
    );
    context.displayFormulaText = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'displayFormulaText') + ')', context
    );
    context.getQuantifiedTraceFormula = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'getQuantifiedTraceFormula') + ')', context
    );
    const oldOption = oldQuantifier.options.find(option => option.correct);
    const savedText = oldOption.text;
    const oldSpokenOption = applySpokenTransform(savedText);
    assert.match(oldSpokenOption, /(?:non è vero che\s+){2,}/i);
    const restoredOption = applySpokenTransform(getOptionDisplayFormula(oldOption));
    assert.doesNotMatch(restoredOption, /(?:non è vero che\s+){2,}/i);
    assert.equal(oldOption.text, savedText);
    assert.equal(oldOption.construction.final_formula_prolog, savedText);
    oldQuantifier.options.forEach(option => {
        assert.ok(context.getQuantifiedTraceFormula(option));
        assert.doesNotMatch(
            applySpokenTransform(getOptionDisplayFormula(option)),
            /(?:non è vero che\s+){2,}/i
        );
    });

    const restoredQuestion = getSpokenQuestionText({
        kind: 'quantifier-negation',
        question: oldQuantifier.question,
        options: oldQuantifier.options
    });
    assert.doesNotMatch(applySpokenTransform(restoredQuestion), /(?:non è vero che\s+){2,}/i);
    assert.notEqual(restoredQuestion, oldQuantifier.question);
    assert.equal(getOptionDisplayFormula({ text: savedText }), savedText);
});

test('quiz normalizers preserve only valid explicit transformation paths', () => {
    const constructionContext = loadScript('scripts/formula-construction.js');
    const transformationContext = loadScript('scripts/formula-transformation.js');
    const context = loadScript('scripts/quiz-normalizers.js');
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: value => value,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({}),
        normalizeConstruction: constructionContext.LogicFormulaConstruction.normalize,
        buildConstructionFromFormula: constructionContext.LogicFormulaConstruction.buildFromFormula,
        buildQuantifiedConstruction: constructionContext.LogicFormulaConstruction.buildQuantifiedTrace,
        normalizeTransformation: transformationContext.LogicFormulaTransformation.normalize
    });
    const transformation = {
        version: 1,
        strategy: 'equivalence_rewrite',
        source_formula_prolog: 'imp(p,q)',
        final_formula_prolog: 'or(not(p),q)',
        preserves_meaning: true,
        steps: [{
            index: 1,
            kind: 'rewrite',
            rule: 'implication_elimination',
            before_prolog: 'imp(p,q)',
            after_prolog: 'or(not(p),q)',
            location: 'root'
        }]
    };
    const result = normalizers.normalizeEquivalenceResult({
        result: {
            question_prolog: 'imp(p,q)',
            options: [
                { formula_prolog: 'or(not(p),q)', is_correct: true, transformation: transformation },
                { formula_prolog: 'and(p,q)', is_correct: false, transformation: transformation }
            ]
        }
    });

    assert.equal(result.options.find(option => option.correct).transformation.final_formula_prolog, 'or(not(p),q)');
    assert.equal(result.options.find(option => !option.correct).transformation, null);
    assert.ok(result.options.every(option => option.construction));
});

test('quiz normalizers reject incomplete logical-consequence payloads', () => {
    const context = loadScript('scripts/quiz-normalizers.js');
    const normalizers = context.LogicQuizNormalizers.create({
        shuffle: values => values.slice(),
        prologToLogical: value => value,
        normalizeGenerationSteps: () => [],
        extractWrongStepsMap: () => ({})
    });

    assert.equal(normalizers.normalizeLogicalConsequenceResult({ result: { options: [] } }), null);
});
