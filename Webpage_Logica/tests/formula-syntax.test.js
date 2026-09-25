const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadSyntax() {
    const context = {};
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/formula-syntax.js', 'utf8'), context);
    return context.LogicFormulaSyntax;
}

test('symbolic formulas are converted to canonical Prolog with the documented precedence', () => {
    const syntax = loadSyntax();

    assert.equal(
        syntax.toProlog('¬p ∧ q ∨ r → s ↔ t'),
        'iff(imp(or(and(not(p),q),r),s),t)'
    );
    assert.equal(syntax.toProlog('(p ∨ q) ∧ ¬r'), 'and(or(p,q),not(r))');
    assert.equal(syntax.toProlog('p → q → r'), 'imp(p,imp(q,r))');
    assert.equal(syntax.toProlog('(p → q) → r'), 'imp(imp(p,q),r)');
});

test('legacy functional notation remains accepted and is normalized', () => {
    const syntax = loadSyntax();

    assert.equal(
        syntax.toProlog(' imp( and(p, q), not(or(r, s)) ) '),
        'imp(and(p,q),not(or(r,s)))'
    );
    assert.equal(syntax.toProlog('iff(p,or(q,r))'), 'iff(p,or(q,r))');
    assert.equal(syntax.toProlog('and(p,q) → not(r)'), 'imp(and(p,q),not(r))');
});

test('display conversion uses symbols and preserves the exact formula tree', () => {
    const syntax = loadSyntax();

    assert.equal(syntax.toDisplay('not(and(p,or(q,r)))'), '¬(p ∧ (q ∨ r))');
    assert.equal(syntax.toDisplay('and(and(p,q),r)'), 'p ∧ q ∧ r');
    assert.equal(syntax.toDisplay('and(p,and(q,r))'), 'p ∧ (q ∧ r)');
    assert.equal(syntax.toDisplay('imp(imp(p,q),r)'), '(p → q) → r');
    assert.equal(syntax.toDisplay('imp(p,imp(q,r))'), 'p → q → r');
    assert.equal(syntax.toDisplay('iff(p,iff(q,r))'), 'p ↔ (q ↔ r)');
});

test('symbolic and functional forms round-trip without changing their AST', () => {
    const syntax = loadSyntax();
    const formulas = [
        'not(and(p,or(q,r)))',
        'iff(imp(p,q),or(not(r),s_2))',
        'and(p,and(q,r))',
        'imp(imp(p,q),r)'
    ];

    formulas.forEach(formula => {
        const canonical = syntax.toProlog(formula);
        assert.equal(syntax.toProlog(syntax.toDisplay(formula)), canonical, formula);
    });
});

test('invalid identifiers, unsupported operators and wrong arities fail in Italian', () => {
    const syntax = loadSyntax();

    assert.throws(() => syntax.toProlog(''), /Inserisci una formula/);
    assert.throws(() => syntax.toProlog('P'), /Atomo non valido/);
    assert.throws(() => syntax.toProlog('_p'), /Atomo non valido/);
    assert.throws(() => syntax.toProlog('xor(p,q)'), /Operatore non supportato: "xor"/);
    assert.throws(() => syntax.toProlog('forall(x,p)'), /Operatore non supportato: "forall"/);
    assert.throws(() => syntax.toProlog('not(p,q)'), /richiede un operando/);
    assert.throws(() => syntax.toProlog('and(p)'), /richiede due operandi/);
    assert.throws(() => syntax.toProlog('and(p,q,r)'), /richiede due operandi/);
    assert.throws(() => syntax.toProlog('∀x p'), /Simbolo non riconosciuto/);
});

test('the parser rejects incomplete formulas and unconsumed input', () => {
    const syntax = loadSyntax();

    assert.throws(() => syntax.toProlog('p ∧'), /Attesa una formula o un atomo/);
    assert.throws(() => syntax.toProlog('(p ∨ q'), /Atteso "\)"/);
    assert.throws(() => syntax.toProlog('p q'), /Testo inatteso dopo la formula/);
    assert.throws(() => syntax.toProlog('and(p,,q)'), /Attesa una formula o un atomo/);
    assert.throws(() => syntax.toProlog('p & q'), /Simbolo non riconosciuto/);
});
