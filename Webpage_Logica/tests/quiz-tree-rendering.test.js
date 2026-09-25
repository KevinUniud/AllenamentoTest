const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

class FakeElement {
    constructor(tagName) {
        this.tagName = String(tagName || '').toUpperCase();
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.className = '';
        this._textContent = '';
        this.classList = {
            add: value => {
                const names = new Set(this.className.split(/\s+/).filter(Boolean));
                names.add(value);
                this.className = Array.from(names).join(' ');
            }
        };
    }

    set innerHTML(value) {
        if (String(value) === '') this.children = [];
    }

    set textContent(value) {
        this._textContent = String(value || '');
        if (this._textContent === '') this.children = [];
    }

    get textContent() {
        return this._textContent;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    getAttribute(name) {
        return this.attributes[name] ?? null;
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    addEventListener(name, listener) {
        this.listeners[name] = listener;
    }
}

function loadModules() {
    const context = {
        document: {
            createElementNS: (_namespace, tagName) => new FakeElement(tagName)
        }
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/quiz-shared.js', 'utf8'), context);
    vm.runInNewContext(fs.readFileSync('scripts/formula-tree.js', 'utf8'), context);
    return context;
}

function groups(svg) {
    return svg.children.filter(child => child.tagName === 'G');
}

test('quiz review requests the same complete symbolic tree rendering used by the laboratory', () => {
    const source = fs.readFileSync('scripts/quiz.js', 'utf8');
    const start = source.indexOf('if (entry.constructionCorrect)');
    const end = source.indexOf('reviewListEl.appendChild(item)', start);
    const block = source.slice(start, end);

    assert.ok(start >= 0 && end > start);
    assert.match(block, /treeContainer\.className = 'sandbox-tree'/);
    assert.match(block, /treeDetail\.className = 'sandbox-tree-detail'/);
    assert.match(
        block,
        /LogicFormulaTree\.render\(treeContainer, entry\.constructionCorrect, \{[\s\S]*?formatFormula: displayFormulaText,[\s\S]*?fullLabels: true/
    );
    assert.match(block, /treeContainer\.scrollLeft = Math\.max/);
});

test('quiz tree labels contain every quantified formula in symbols without truncation', () => {
    const context = loadModules();
    const trace = { steps: [
        { index: 1, node_id: 'r', kind: 'atom', result_prolog: 'R(x)', depth: 0, operands: [] },
        { index: 2, node_id: 'q', kind: 'atom', result_prolog: 'Q(x)', depth: 0, operands: [] },
        { index: 3, node_id: 'left', kind: 'binary', operator: 'or', result_prolog: 'or(R(x),Q(x))', depth: 1, operands: ['r', 'q'] },
        { index: 4, node_id: 's', kind: 'atom', result_prolog: 'S(x)', depth: 0, operands: [] },
        { index: 5, node_id: 'p', kind: 'atom', result_prolog: 'P(x)', depth: 0, operands: [] },
        { index: 6, node_id: 'right', kind: 'binary', operator: 'iff', result_prolog: 'iff(S(x),P(x))', depth: 1, operands: ['s', 'p'] },
        { index: 7, node_id: 'body', kind: 'binary', operator: 'and', result_prolog: 'and(or(R(x),Q(x)),iff(S(x),P(x)))', depth: 2, operands: ['left', 'right'] },
        { index: 8, node_id: 'negated', kind: 'unary', operator: 'not', result_prolog: 'not(and(or(R(x),Q(x)),iff(S(x),P(x))))', depth: 3, operands: ['body'] },
        { index: 9, node_id: 'root', kind: 'quantifier', operator: 'forall', result_prolog: 'forall(x,not(and(or(R(x),Q(x)),iff(S(x),P(x)))))', depth: 4, operands: ['negated'] }
    ] };
    const container = new FakeElement('div');

    context.LogicFormulaTree.render(container, trace, {
        formatFormula: context.quizShared.prologToLogical,
        fullLabels: true
    });

    const labels = groups(container.children[0]).map(group => {
        const text = group.children.find(child => child.tagName === 'TEXT');
        return {
            full: text.getAttribute('data-full-label'),
            visible: text.children.map(line => line.textContent).join(' ')
        };
    });
    const root = labels.at(-1);

    assert.match(root.full, /^∀x /);
    assert.match(root.full, /¬/);
    assert.match(root.full, /∧/);
    assert.match(root.full, /∨/);
    assert.match(root.full, /↔/);
    labels.forEach(label => {
        assert.doesNotMatch(label.full, /\b(?:not|and|or|iff|forall)\s*\(/i);
        assert.doesNotMatch(label.visible, /…|\.\.\./);
    });
});

test('quiz symbolic formatting preserves the same grouping used by the laboratory', () => {
    const context = loadModules();

    assert.equal(context.quizShared.prologToLogical('imp(imp(p,q),r)'), '(p → q) → r');
    assert.equal(context.quizShared.prologToLogical('imp(p,imp(q,r))'), 'p → q → r');
    assert.equal(context.quizShared.prologToLogical('and(p,and(q,r))'), 'p ∧ (q ∧ r)');
    assert.equal(context.quizShared.prologToLogical('or(p,or(q,r))'), 'p ∨ (q ∨ r)');
    assert.equal(
        context.quizShared.prologToLogical('forall(x,imp(imp(P(x),Q(x)),R(x)))'),
        '∀x ((p(x) → q(x)) → r(x))'
    );
});
