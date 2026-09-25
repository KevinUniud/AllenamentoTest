const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadConstructionModule() {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/formula-construction.js', 'utf8'), context);
    return context.LogicFormulaConstruction;
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
        this._textContent = String(value || '');
        if (this._textContent === '') this.children = [];
    }

    get textContent() {
        return this._textContent;
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

    querySelector(selector) {
        if (selector === 'h3' && this.tagName === 'H3') return this;
        for (const child of this.children) {
            const match = child.querySelector(selector);
            if (match) return match;
        }
        return null;
    }
}

test('formula construction fallback builds a deterministic postorder trace', () => {
    const construction = loadConstructionModule();
    const trace = construction.buildFromFormula('imp(and(p,q),not(r))');

    assert.equal(trace.version, 1);
    assert.deepEqual(
        Array.from(trace.steps, step => step.result_prolog),
        ['p', 'q', 'and(p,q)', 'r', 'not(r)', 'imp(and(p,q),not(r))']
    );
    assert.equal(trace.steps.at(-1).node_id, 'root');
});

test('formula construction supports predicates and quantifiers', () => {
    const construction = loadConstructionModule();
    const trace = construction.buildFromFormula('forall(x,imp(A(x),B(x)))');

    assert.deepEqual(
        Array.from(trace.steps, step => step.kind),
        ['predicate', 'predicate', 'binary', 'quantifier']
    );
    assert.equal(trace.steps.at(-1).details.bound_variable, 'x');
    assert.match(construction.describeStep(trace.steps.at(-1)), /universale/);
});

test('invalid or inconsistent construction traces fail safely', () => {
    const construction = loadConstructionModule();
    const valid = construction.buildFromFormula('and(p,q)');
    const brokenFinal = { ...valid, final_formula_prolog: 'or(p,q)' };
    const brokenOperands = {
        ...valid,
        steps: valid.steps.map((step, index) => index === 0 ? { ...step, operands: ['missing'] } : step)
    };

    assert.equal(construction.normalize(brokenFinal), null);
    assert.equal(construction.normalize(brokenOperands), null);
    assert.equal(construction.buildFromFormula('and(p,q'), null);
});

test('local quantified-negation choices use the same trace contract', () => {
    const construction = loadConstructionModule();
    const trace = construction.buildQuantifiedTrace(
        '∃',
        'p ∧ q',
        true,
        '∃x ¬(p ∧ q)',
        'and(p,q)'
    );

    assert.equal(trace.final_formula_prolog, '∃x ¬(p ∧ q)');
    assert.deepEqual(
        Array.from(trace.steps, step => step.kind),
        ['atom', 'atom', 'binary', 'unary', 'quantifier']
    );
    assert.equal(trace.steps[2].result_prolog, 'and(p,q)');
    assert.equal(trace.steps.at(-1).operator, 'exists');
});

test('renderer keeps the explanation hidden until its accessible toggle is opened', () => {
    const context = {};
    context.window = context;
    context.document = { createElement: tagName => new FakeElement(tagName) };
    vm.runInNewContext(fs.readFileSync('scripts/formula-construction.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/formula-construction-renderer.js', 'utf8'), context);
    const container = new FakeElement('div');
    const trace = context.LogicFormulaConstruction.buildFromFormula('and(p,q)');
    const renderer = context.LogicFormulaConstructionRenderer.create({
        container: container,
        formatFormula: value => value
    });

    assert.equal(container.hidden, true);
    renderer.show({ correct: trace, selected: trace, selectedIsCorrect: true });

    assert.equal(container.hidden, false);
    assert.equal(container.children.length, 2);
    const toggle = container.children[0];
    const panel = container.children[1];
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(panel.hidden, true);
    assert.equal(panel.children[0].children[1].children.length, 3);

    toggle.listeners.click();
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(panel.hidden, false);
});
