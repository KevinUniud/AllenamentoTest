const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadBuilder() {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/logic-tree-builder.js', 'utf8'), context);
    return context.LogicTreeBuilder;
}

test('tree builder preserves left/right selection order and builds a full root formula', () => {
    const builder = loadBuilder().create();
    const p = builder.addAtom('p');
    const q = builder.addAtom('q');
    builder.toggleSelection(p.id);
    builder.toggleSelection(q.id);
    const conjunction = builder.applyOperator('and');

    assert.equal(conjunction.result_prolog, 'and(p,q)');
    assert.equal(conjunction.depth, 1);
    assert.deepEqual(Array.from(conjunction.operands), [p.id, q.id]);
    assert.deepEqual(Array.from(builder.getState().roots), [conjunction.id]);
    assert.equal(builder.getState().completeFormulaProlog, 'and(p,q)');
});

test('tree builder composes nested binary roots and keeps all construction nodes', () => {
    const builder = loadBuilder().create();
    const p = builder.addAtom('p');
    const q = builder.addAtom('q');
    builder.toggleSelection(p.id);
    builder.toggleSelection(q.id);
    const conjunction = builder.applyOperator('and');
    const r = builder.addAtom('r');
    builder.toggleSelection(conjunction.id);
    builder.toggleSelection(r.id);
    const implication = builder.applyOperator('imp');
    const trace = builder.getTrace();

    assert.equal(implication.result_prolog, 'imp(and(p,q),r)');
    assert.equal(implication.depth, 2);
    assert.equal(trace.steps.length, 5);
    assert.equal(trace.final_formula_prolog, 'imp(and(p,q),r)');
    assert.deepEqual(Array.from(trace.steps.at(-1).operands), [conjunction.id, r.id]);
});

test('negation creates a unary root and leaves its operand underneath', () => {
    const builder = loadBuilder().create();
    const p = builder.addAtom('p');
    builder.toggleSelection(p.id);
    const negation = builder.applyOperator('not');

    assert.equal(negation.result_prolog, 'not(p)');
    assert.equal(negation.depth, 1);
    assert.deepEqual(Array.from(negation.operands), [p.id]);
    assert.deepEqual(Array.from(builder.getState().roots), [negation.id]);
});

test('invalid atoms and incomplete operator selections never mutate the tree', () => {
    const api = loadBuilder();
    const builder = api.create();

    assert.throws(() => builder.addAtom('P'), /lettera minuscola/);
    assert.equal(builder.getState().nodes.length, 0);

    const p = builder.addAtom('p');
    const before = builder.getState();
    assert.throws(() => builder.applyOperator('and'), /due radici/);
    assert.deepEqual(builder.getState(), before);

    builder.toggleSelection(p.id);
    assert.throws(() => builder.applyOperator('or'), /due radici/);
    assert.equal(builder.getState().selected[0], p.id);
});

test('truth constants are not accepted as atoms and rejection leaves state untouched', () => {
    const builder = loadBuilder().create();
    const before = builder.getState();

    assert.throws(() => builder.addAtom('true'), /costante logica/);
    assert.deepEqual(builder.getState(), before);
    assert.throws(() => builder.addAtom('false'), /costante logica/);
    assert.deepEqual(builder.getState(), before);
    assert.throws(() => builder.addAtom('p'.repeat(41)), /limite di 40 caratteri/);
    assert.deepEqual(builder.getState(), before);

    assert.equal(builder.addAtom('p').id, 'tree-node-1');
});

test('an operator cannot create a formula longer than 500 characters or mutate state', () => {
    const builder = loadBuilder().create();
    let root = builder.addAtom('p');

    while (true) {
        const atom = builder.addAtom('q');
        builder.toggleSelection(root.id);
        builder.toggleSelection(atom.id);
        const nextLength = 'and('.length + root.result_prolog.length + 1 + atom.result_prolog.length + 1;
        if (nextLength > 500) {
            const before = builder.getState();
            assert.throws(() => builder.applyOperator('and'), /supera il limite di 500 caratteri/);
            assert.deepEqual(builder.getState(), before);
            assert.equal(builder.getTrace().steps.length, before.nodes.length);
            break;
        }
        root = builder.applyOperator('and');
    }
});

test('duplicate atoms retain unique node identities and reset clears all state', () => {
    const builder = loadBuilder().create();
    const first = builder.addAtom('p');
    const second = builder.addAtom('p');

    assert.notEqual(first.id, second.id);
    builder.toggleSelection(first.id);
    builder.toggleSelection(second.id);
    assert.equal(builder.applyOperator('iff').result_prolog, 'iff(p,p)');

    const state = builder.reset();
    assert.equal(state.nodes.length, 0);
    assert.equal(state.roots.length, 0);
    assert.equal(state.completeFormulaProlog, null);
});
