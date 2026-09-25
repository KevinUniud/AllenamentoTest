const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function equivalenceTrace() {
    return {
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
}

function mutationTrace() {
    return {
        version: 1,
        strategy: 'distractor_mutation',
        source_formula_prolog: 'imp(p,q)',
        final_formula_prolog: 'and(p,q)',
        preserves_meaning: false,
        steps: [{
            index: 1,
            kind: 'mutation',
            rule: 'replace_operator_imp_with_and',
            before_prolog: 'imp(p,q)',
            after_prolog: 'and(p,q)',
            location: 'root'
        }]
    };
}

function nestedEquivalenceTrace() {
    return {
        version: 1,
        strategy: 'equivalence_rewrite',
        source_formula_prolog: 'imp(p,imp(r,q))',
        final_formula_prolog: 'or(not(p),or(not(r),q))',
        preserves_meaning: true,
        steps: [
            {
                index: 1,
                kind: 'rewrite',
                rule: 'implication_elimination',
                before_prolog: 'imp(p,imp(r,q))',
                after_prolog: 'imp(p,or(not(r),q))',
                before_subformula_prolog: 'imp(r,q)',
                after_subformula_prolog: 'or(not(r),q)',
                location: 'root.right'
            },
            {
                index: 2,
                kind: 'rewrite',
                rule: 'implication_elimination',
                before_prolog: 'imp(p,or(not(r),q))',
                after_prolog: 'or(not(p),or(not(r),q))',
                before_subformula_prolog: 'imp(p,or(not(r),q))',
                after_subformula_prolog: 'or(not(p),or(not(r),q))',
                location: 'root'
            }
        ]
    };
}

function loadTransformationModule() {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation.js', 'utf8'), context);
    return context.LogicFormulaTransformation;
}

class FakeElement {
    constructor(tagName) {
        this.tagName = String(tagName || '').toUpperCase();
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.hidden = false;
        this.className = '';
        this.id = '';
        this._textContent = '';
        this.classList = {
            add: value => {
                const classes = new Set(this.className.split(/\s+/).filter(Boolean));
                classes.add(value);
                this.className = Array.from(classes).join(' ');
            }
        };
    }

    set textContent(value) {
        this._textContent = String(value == null ? '' : value);
        if (this._textContent === '') this.children = [];
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    getAttribute(name) {
        return this.attributes[name] ?? null;
    }

    addEventListener(name, listener) {
        this.listeners[name] = listener;
    }
}

function hasClass(element, className) {
    return element.className.split(/\s+/).includes(className);
}

function descendantsWithClass(element, className) {
    const matches = [];
    if (hasClass(element, className)) matches.push(element);
    element.children.forEach(child => matches.push(...descendantsWithClass(child, className)));
    return matches;
}

test('transformation contract accepts a continuous authentic rewrite path', () => {
    const transformation = loadTransformationModule();
    const normalized = transformation.normalize(equivalenceTrace());

    assert.equal(normalized.source_formula_prolog, 'imp(p,q)');
    assert.equal(normalized.final_formula_prolog, 'or(not(p),q)');
    assert.equal(normalized.steps[0].rule, 'implication_elimination');
    assert.equal(normalized.steps[0].before_subformula_prolog, 'imp(p,q)');
    assert.equal(normalized.steps[0].after_subformula_prolog, 'or(not(p),q)');
    assert.match(transformation.describeStep(normalized.steps[0]), /eliminazione dell'implicazione/);
});

test('transformation contract describes joint biconditional negation', () => {
    const transformation = loadTransformationModule();
    const step = {
        kind: 'rewrite',
        rule: 'biconditional_negation',
        location: 'root'
    };

    assert.match(transformation.describeStep(step), /negazione simultanea/);
    assert.equal(transformation.ruleSchema(step), 'A ↔ B ⇔ (¬A ↔ ¬B)');
});

test('transformation contract preserves complete subformula pairs and safely falls back for partial pairs', () => {
    const transformation = loadTransformationModule();
    const nested = transformation.normalize(nestedEquivalenceTrace());
    assert.equal(nested.steps[0].before_subformula_prolog, 'imp(r,q)');
    assert.equal(nested.steps[0].after_subformula_prolog, 'or(not(r),q)');

    const partial = equivalenceTrace();
    partial.steps[0].before_subformula_prolog = 'imp(x,y)';
    const normalizedPartial = transformation.normalize(partial);
    assert.equal(normalizedPartial.steps[0].before_subformula_prolog, 'imp(p,q)');
    assert.equal(normalizedPartial.steps[0].after_subformula_prolog, 'or(not(p),q)');
});

test('transformation contract rejects broken, mislabeled, or inauthentic paths', () => {
    const transformation = loadTransformationModule();
    const valid = equivalenceTrace();
    const brokenChain = {
        ...valid,
        steps: [
            { ...valid.steps[0], after_prolog: 'or(q,p)' },
            {
                index: 2,
                kind: 'rewrite',
                rule: 'commutativity_or',
                before_prolog: 'or(not(p),q)',
                after_prolog: valid.final_formula_prolog,
                location: 'root'
            }
        ]
    };

    assert.equal(transformation.normalize({ ...valid, final_formula_prolog: 'and(p,q)' }), null);
    assert.equal(transformation.normalize({ ...valid, preserves_meaning: false }), null);
    assert.equal(transformation.normalize({ ...valid, steps: [{ ...valid.steps[0], kind: 'mutation' }] }), null);
    assert.equal(transformation.normalize(brokenChain), null);
    assert.equal(transformation.normalize({ construction: valid }), null);
});

test('renderer uses the reached-formula wording and shows both paths as numbered traces', () => {
    const context = {};
    context.window = context;
    context.document = { createElement: tagName => new FakeElement(tagName) };
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation-renderer.js', 'utf8'), context);
    const container = new FakeElement('div');
    const renderer = context.LogicFormulaTransformationRenderer.create({
        container: container,
        formatFormula: value => value
    });

    renderer.show({ correct: equivalenceTrace(), selected: mutationTrace(), selectedIsCorrect: false });

    assert.equal(container.hidden, false);
    assert.equal(container.children.length, 2);
    const toggle = container.children[0];
    const panel = container.children[1];
    assert.equal(toggle.textContent, 'Come è stata raggiunta la formula?');
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(toggle.getAttribute('aria-controls'), panel.id);
    assert.equal(panel.children.length, 2);
    assert.equal(panel.children[0].children[0].textContent, 'Costruzione della risposta corretta');
    const selectedTrace = panel.children[1];
    assert.equal(selectedTrace.tagName, 'SECTION');
    assert.ok(hasClass(selectedTrace, 'formula-transformation-trace'));
    assert.equal(selectedTrace.children[0].textContent, 'Costruzione della risposta selezionata');
    assert.equal(panel.hidden, true);

    toggle.listeners.click();
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(panel.hidden, false);
});

test('renderer shows the general law and its concrete application from question to correct answer', () => {
    const context = {};
    context.window = context;
    context.document = { createElement: tagName => new FakeElement(tagName) };
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation-renderer.js', 'utf8'), context);
    const container = new FakeElement('div');
    const formatted = {
        'imp(p,imp(r,q))': 'p → (r → q)',
        'imp(r,q)': 'r → q',
        'or(not(r),q)': '¬r ∨ q',
        'imp(p,or(not(r),q))': 'p → (¬r ∨ q)',
        'or(not(p),or(not(r),q))': '¬p ∨ (¬r ∨ q)'
    };
    const renderer = context.LogicFormulaTransformationRenderer.create({
        container: container,
        formatFormula: value => formatted[value] || value
    });

    renderer.show({ correct: nestedEquivalenceTrace(), selectedIsCorrect: true });

    const panel = container.children[1];
    const correctTrace = panel.children[0];
    assert.equal(correctTrace.children[0].textContent, 'Costruzione della risposta corretta');
    assert.equal(
        descendantsWithClass(correctTrace, 'formula-transformation-source')[0].children[1].textContent,
        'p → (r → q)'
    );

    const steps = descendantsWithClass(correctTrace, 'formula-transformation-step');
    assert.equal(steps.length, 2);
    assert.equal(descendantsWithClass(correctTrace, 'formula-transformation-steps')[0].tagName, 'OL');
    assert.ok(steps.every(step => step.tagName === 'LI'), 'i passaggi devono essere numerati semanticamente');
    const laws = descendantsWithClass(correctTrace, 'formula-transformation-law');
    const applications = descendantsWithClass(correctTrace, 'formula-transformation-application');
    const applicationRows = descendantsWithClass(correctTrace, 'formula-transformation-application-row');
    const results = descendantsWithClass(correctTrace, 'formula-transformation-result');
    assert.equal(laws.length, steps.length, 'ogni passaggio deve mostrare la legge generale');
    assert.equal(applications.length, steps.length, 'ogni passaggio deve mostrare l\'istanza concreta');
    assert.equal(results.length, steps.length, 'ogni passaggio deve mostrare la formula ottenuta');

    laws.forEach(law => {
        assert.match(law.textContent, /A\s*→\s*B\s*⇔\s*¬A\s*∨\s*B/);
        assert.doesNotMatch(law.textContent, /¬A\s*∧\s*B/);
    });
    assert.match(applications[0].textContent, /r → q\s*⇔\s*¬r ∨ q/);
    assert.match(applications[1].textContent, /p → \(¬r ∨ q\)\s*⇔\s*¬p ∨ \(¬r ∨ q\)/);
    assert.equal(applicationRows[0].children[0].textContent, 'Applicazione della regola: ');
    assert.equal(results[0].children[0].textContent, 'Formula completa ottenuta: ');
    assert.equal(results[0].children[1].textContent, 'p → (¬r ∨ q)');
    assert.equal(results[1].children[1].textContent, '¬p ∨ (¬r ∨ q)');

    assert.equal(nestedEquivalenceTrace().source_formula_prolog, nestedEquivalenceTrace().steps[0].before_prolog);
    assert.equal(nestedEquivalenceTrace().steps[0].after_prolog, nestedEquivalenceTrace().steps[1].before_prolog);
    assert.equal(nestedEquivalenceTrace().steps[1].after_prolog, nestedEquivalenceTrace().final_formula_prolog);
});

test('renderer stays hidden when only a construction trace is available', () => {
    const context = {};
    context.window = context;
    context.document = { createElement: tagName => new FakeElement(tagName) };
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/formula-transformation-renderer.js', 'utf8'), context);
    const container = new FakeElement('div');
    const renderer = context.LogicFormulaTransformationRenderer.create({ container: container });

    renderer.show({
        correct: {
            version: 1,
            strategy: 'ast_postorder',
            final_formula_prolog: 'and(p,q)',
            steps: []
        },
        selectedIsCorrect: true
    });

    assert.equal(container.hidden, true);
    assert.equal(container.children.length, 0);
});
