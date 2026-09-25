/* Modello puro per costruire formule proposizionali collegando le radici dell'albero. */
(function exposeLogicTreeBuilder(global) {
    'use strict';

    const ATOM_PATTERN = /^[a-z][A-Za-z0-9_]*$/;
    const MAX_ATOM_LENGTH = 40;
    const MAX_FORMULA_LENGTH = 500;
    const RESERVED_ATOMS = new Set(['true', 'false']);
    const OPERATORS = Object.freeze({
        not: Object.freeze({ arity: 1, symbol: '¬', label: 'negazione' }),
        and: Object.freeze({ arity: 2, symbol: '∧', label: 'congiunzione' }),
        or: Object.freeze({ arity: 2, symbol: '∨', label: 'disgiunzione' }),
        imp: Object.freeze({ arity: 2, symbol: '→', label: 'implicazione' }),
        iff: Object.freeze({ arity: 2, symbol: '↔', label: 'doppia implicazione' })
    });

    function copyNode(node) {
        return {
            id: node.id,
            kind: node.kind,
            operator: node.operator,
            operands: node.operands.slice(),
            result_prolog: node.result_prolog,
            depth: node.depth,
            details: Object.assign({}, node.details)
        };
    }

    function create() {
        let sequence = 0;
        let nodes = [];
        let roots = [];
        let selected = [];

        function nodeById(id) {
            return nodes.find(function(node) { return node.id === id; }) || null;
        }

        function state() {
            const completed = roots.length === 1 ? nodeById(roots[0]) : null;
            return {
                nodes: nodes.map(copyNode),
                roots: roots.slice(),
                selected: selected.slice(),
                completeFormulaProlog: completed ? completed.result_prolog : null
            };
        }

        function trace() {
            const snapshot = state();
            return {
                version: 1,
                strategy: 'client_tree_builder',
                final_formula_prolog: snapshot.completeFormulaProlog || '',
                steps: snapshot.nodes.map(function(node, index) {
                    return {
                        index: index + 1,
                        node_id: node.id,
                        kind: node.kind,
                        operator: node.operator,
                        operands: node.operands,
                        result_prolog: node.result_prolog,
                        depth: node.depth,
                        details: node.details
                    };
                })
            };
        }

        function addAtom(rawName) {
            const name = String(rawName || '').trim();
            if (!ATOM_PATTERN.test(name)) {
                throw new Error('L\'atomo deve iniziare con una lettera minuscola e contenere solo lettere, numeri o underscore.');
            }
            if (name.length > MAX_ATOM_LENGTH) {
                throw new Error('Il nome dell\'atomo supera il limite di ' + MAX_ATOM_LENGTH + ' caratteri.');
            }
            if (RESERVED_ATOMS.has(name)) {
                throw new Error(name + ' è una costante logica e non può essere usata come nome di un atomo.');
            }
            sequence += 1;
            const node = {
                id: 'tree-node-' + sequence,
                kind: 'atom',
                operator: null,
                operands: [],
                result_prolog: name,
                depth: 0,
                details: { name: name }
            };
            nodes.push(node);
            roots.push(node.id);
            selected = [];
            return copyNode(node);
        }

        function toggleSelection(rawId) {
            const id = String(rawId || '');
            if (!roots.includes(id)) {
                throw new Error('Puoi collegare soltanto le radici disponibili.');
            }
            if (selected.includes(id)) {
                selected = selected.filter(function(item) { return item !== id; });
                return state();
            }
            if (selected.length >= 2) {
                throw new Error('Puoi selezionare al massimo due radici.');
            }
            selected.push(id);
            return state();
        }

        function applyOperator(rawOperator) {
            const operator = String(rawOperator || '');
            const definition = OPERATORS[operator];
            if (!definition) throw new Error('Operatore non supportato.');
            if (selected.length !== definition.arity) {
                const required = definition.arity === 1 ? 'una radice' : 'due radici, prima quella sinistra e poi quella destra';
                throw new Error('Per la ' + definition.label + ' seleziona ' + required + '.');
            }

            const operands = selected.map(nodeById);
            if (operands.some(function(node) { return !node; })) {
                throw new Error('La selezione non è più disponibile.');
            }
            const result = definition.arity === 1
                ? operator + '(' + operands[0].result_prolog + ')'
                : operator + '(' + operands[0].result_prolog + ',' + operands[1].result_prolog + ')';
            if (result.length > MAX_FORMULA_LENGTH) {
                throw new Error('La formula risultante supera il limite di ' + MAX_FORMULA_LENGTH + ' caratteri.');
            }
            sequence += 1;
            const node = {
                id: 'tree-node-' + sequence,
                kind: definition.arity === 1 ? 'unary' : 'binary',
                operator: operator,
                operands: operands.map(function(item) { return item.id; }),
                result_prolog: result,
                depth: 1 + Math.max.apply(null, operands.map(function(item) { return item.depth; })),
                details: {}
            };
            nodes.push(node);
            roots = roots.filter(function(id) { return !selected.includes(id); });
            roots.push(node.id);
            selected = [];
            return copyNode(node);
        }

        function reset() {
            sequence = 0;
            nodes = [];
            roots = [];
            selected = [];
            return state();
        }

        return Object.freeze({
            addAtom: addAtom,
            applyOperator: applyOperator,
            getState: state,
            getTrace: trace,
            reset: reset,
            toggleSelection: toggleSelection
        });
    }

    global.LogicTreeBuilder = Object.freeze({
        ATOM_PATTERN: ATOM_PATTERN,
        MAX_ATOM_LENGTH: MAX_ATOM_LENGTH,
        MAX_FORMULA_LENGTH: MAX_FORMULA_LENGTH,
        OPERATORS: OPERATORS,
        create: create
    });
})(window);
