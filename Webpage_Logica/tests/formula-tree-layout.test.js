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
                const classes = new Set(this.className.split(/\s+/).filter(Boolean));
                classes.add(value);
                this.className = Array.from(classes).join(' ');
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

function loadTreeModule() {
    const context = {
        document: { createElementNS: (_namespace, tagName) => new FakeElement(tagName) }
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/formula-tree.js', 'utf8'), context);
    return context.LogicFormulaTree;
}

function positionOf(group) {
    const match = group.getAttribute('transform').match(/^translate\(([-\d.]+) ([-\d.]+)\)$/);
    return { x: Number(match[1]), y: Number(match[2]) };
}

function groupsById(svg) {
    return new Map(svg.children
        .filter(child => child.tagName === 'G')
        .map(group => [group.getAttribute('data-node-id'), group]));
}

const TRACE = { steps: [
    { index: 1, node_id: 'root.left.left', kind: 'atom', result_prolog: 'p', depth: 0, operands: [] },
    { index: 2, node_id: 'root.left.right', kind: 'atom', result_prolog: 'q', depth: 0, operands: [] },
    { index: 3, node_id: 'root.left', kind: 'binary', operator: 'and', result_prolog: 'and(p,q)', depth: 1, operands: ['root.left.left', 'root.left.right'] },
    { index: 4, node_id: 'root.right.left', kind: 'atom', result_prolog: 'r', depth: 0, operands: [] },
    { index: 5, node_id: 'root.right.right', kind: 'atom', result_prolog: 's', depth: 0, operands: [] },
    { index: 6, node_id: 'root.right', kind: 'binary', operator: 'or', result_prolog: 'or(r,s)', depth: 1, operands: ['root.right.left', 'root.right.right'] },
    { index: 7, node_id: 'root', kind: 'binary', operator: 'imp', result_prolog: 'imp(and(p,q),or(r,s))', depth: 2, operands: ['root.left', 'root.right'] }
] };

test('recursive tree layout keeps the root above and preserves left-to-right operand order', () => {
    const tree = loadTreeModule();
    const container = new FakeElement('div');
    tree.render(container, TRACE);

    const groups = groupsById(container.children[0]);
    const root = positionOf(groups.get('root'));
    const left = positionOf(groups.get('root.left'));
    const right = positionOf(groups.get('root.right'));
    const leftLeaf = positionOf(groups.get('root.left.left'));
    const rightLeaf = positionOf(groups.get('root.left.right'));

    assert.ok(root.y < left.y && root.y < right.y);
    assert.ok(left.x < right.x);
    assert.ok(leftLeaf.x < rightLeaf.x);
    assert.equal(groups.get('root').children[0].tagName, 'CIRCLE');
});

test('tree renders complete multiline symbolic labels without ellipses', () => {
    const tree = loadTreeModule();
    const container = new FakeElement('div');
    const formatted = {
        'and(p,q)': 'p ∧ q',
        'or(r,s)': 'r ∨ s',
        'imp(and(p,q),or(r,s))': '(p ∧ q) → (r ∨ s)'
    };
    tree.render(container, TRACE, {
        fullLabels: true,
        maxLabelChars: 8,
        formatFormula: value => formatted[value] || value
    });

    const rootGroup = groupsById(container.children[0]).get('root');
    const text = rootGroup.children.find(child => child.tagName === 'TEXT');
    const renderedLabel = text.children.map(line => line.textContent).join('');

    assert.ok(text.children.length > 1);
    assert.equal(renderedLabel.replace(/\s/g, ''), formatted['imp(and(p,q),or(r,s))'].replace(/\s/g, ''));
    assert.doesNotMatch(renderedLabel, /…|\.\.\./);
    assert.equal(text.getAttribute('data-full-label'), formatted['imp(and(p,q),or(r,s))']);
    assert.equal(rootGroup.children[0].tagName, 'RECT');
    assert.equal(container.children[0].getAttribute('width'), '760');
});

test('selected and available nodes expose state classes, aria-pressed and selection callbacks', () => {
    const tree = loadTreeModule();
    const container = new FakeElement('div');
    const detail = new FakeElement('p');
    const selected = [];
    tree.render(container, TRACE, {
        detailElement: detail,
        formatFormula: value => value === 'imp(and(p,q),or(r,s))' ? '(p ∧ q) → (r ∨ s)' : value,
        selectedNodeIds: ['root'],
        availableRootIds: new Set(['root']),
        onSelect: node => selected.push(node.id)
    });

    const groups = groupsById(container.children[0]);
    const left = groups.get('root.left');
    const root = groups.get('root');
    assert.equal(root.getAttribute('role'), 'button');
    assert.equal(root.getAttribute('tabindex'), '0');
    assert.equal(root.getAttribute('aria-pressed'), 'true');
    assert.match(root.className, /\bis-selected\b/);
    assert.match(root.className, /\bis-available\b/);

    assert.equal(left.getAttribute('role'), 'img');
    assert.equal(left.getAttribute('aria-disabled'), 'true');
    assert.equal(left.getAttribute('tabindex'), null);
    assert.equal(left.getAttribute('aria-pressed'), null);
    assert.equal(Object.hasOwn(left.listeners, 'click'), false);
    assert.equal(Object.hasOwn(left.listeners, 'keydown'), false);

    root.listeners.click();
    assert.match(detail.textContent, /Operatore: →/);
    assert.doesNotMatch(detail.textContent, /Operatore: imp/);
    let prevented = false;
    root.listeners.keydown({ key: 'Enter', preventDefault: () => { prevented = true; } });
    assert.deepEqual(selected, ['root', 'root']);
    assert.equal(prevented, true);
});

test('read-only trees remain keyboard-accessible without exposing a selection state', () => {
    const tree = loadTreeModule();
    const container = new FakeElement('div');
    const detail = new FakeElement('p');
    tree.render(container, TRACE, { detailElement: detail });

    const svg = container.children[0];
    const root = groupsById(svg).get('root');
    assert.equal(svg.getAttribute('role'), 'group');
    assert.equal(root.getAttribute('role'), 'button');
    assert.equal(root.getAttribute('tabindex'), '0');
    assert.equal(root.getAttribute('aria-pressed'), null);

    root.listeners.click();
    assert.match(detail.textContent, /Passaggio 7/);
});

test('graph edges retain the operand index used by the renderer', () => {
    const graph = loadTreeModule().toGraph(TRACE);
    const rootEdges = graph.edges.filter(edge => edge.to === 'root');
    assert.deepEqual(Array.from(rootEdges, edge => [edge.from, edge.operandIndex]), [
        ['root.left', 0],
        ['root.right', 1]
    ]);
});
