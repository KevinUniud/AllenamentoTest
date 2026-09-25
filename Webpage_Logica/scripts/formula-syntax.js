/* Conversione pura tra la notazione simbolica della UI e la sintassi Prolog dell'API. */
(function exposeFormulaSyntax(global) {
    'use strict';

    const OPERATORS = Object.freeze({
        not: Object.freeze({ arity: 1, symbol: '¬', precedence: 5 }),
        and: Object.freeze({ arity: 2, symbol: '∧', precedence: 4 }),
        or: Object.freeze({ arity: 2, symbol: '∨', precedence: 3 }),
        imp: Object.freeze({ arity: 2, symbol: '→', precedence: 2 }),
        iff: Object.freeze({ arity: 2, symbol: '↔', precedence: 1 })
    });

    const SYMBOL_TO_OPERATOR = Object.freeze({
        '¬': 'not',
        '∧': 'and',
        '∨': 'or',
        '→': 'imp',
        '↔': 'iff'
    });

    function syntaxError(message, position) {
        const suffix = Number.isInteger(position) ? ' (posizione ' + (position + 1) + ').' : '.';
        return new Error(message.replace(/[.\s]+$/, '') + suffix);
    }

    function tokenize(source) {
        const tokens = [];
        let position = 0;

        while (position < source.length) {
            const character = source[position];
            if (/\s/.test(character)) {
                position += 1;
                continue;
            }
            if (character === '(' || character === ')' || character === ',') {
                tokens.push({ type: character, value: character, position: position });
                position += 1;
                continue;
            }
            if (Object.hasOwn(SYMBOL_TO_OPERATOR, character)) {
                tokens.push({
                    type: 'operator',
                    value: SYMBOL_TO_OPERATOR[character],
                    position: position
                });
                position += 1;
                continue;
            }
            if (/[A-Za-z_]/.test(character)) {
                const start = position;
                position += 1;
                while (position < source.length && /[A-Za-z0-9_]/.test(source[position])) {
                    position += 1;
                }
                tokens.push({ type: 'identifier', value: source.slice(start, position), position: start });
                continue;
            }
            throw syntaxError('Simbolo non riconosciuto: "' + character + '"', position);
        }

        tokens.push({ type: 'end', value: '', position: source.length });
        return tokens;
    }

    function parse(source) {
        if (typeof source !== 'string' || !source.trim()) {
            throw new Error('Inserisci una formula.');
        }

        const tokens = tokenize(source);
        let index = 0;

        function current() {
            return tokens[index];
        }

        function take(type) {
            const token = current();
            if (token.type !== type) return null;
            index += 1;
            return token;
        }

        function expect(type, description) {
            const token = take(type);
            if (token) return token;
            throw syntaxError('Atteso ' + description, current().position);
        }

        function atom(token) {
            if (!/^[a-z][A-Za-z0-9_]*$/.test(token.value)) {
                throw syntaxError(
                    'Atomo non valido: usa una lettera minuscola iniziale seguita da lettere, numeri o underscore',
                    token.position
                );
            }
            return { kind: 'atom', name: token.value };
        }

        function operation(operator, operands, position) {
            const definition = OPERATORS[operator];
            if (!definition) {
                throw syntaxError('Operatore non supportato: "' + operator + '"', position);
            }
            if (operands.length !== definition.arity) {
                const expected = definition.arity === 1 ? 'un operando' : 'due operandi';
                throw syntaxError('L\'operatore "' + operator + '" richiede ' + expected, position);
            }
            if (definition.arity === 1) {
                return { kind: 'unary', operator: operator, operand: operands[0] };
            }
            return { kind: 'binary', operator: operator, left: operands[0], right: operands[1] };
        }

        function parsePrimary() {
            const opening = take('(');
            if (opening) {
                const expression = parseEquivalence();
                expect(')', '")"');
                return expression;
            }

            const identifier = take('identifier');
            if (!identifier) {
                throw syntaxError('Attesa una formula o un atomo', current().position);
            }
            if (current().type !== '(') return atom(identifier);

            take('(');
            const operands = [];
            if (current().type !== ')') {
                while (true) {
                    operands.push(parseEquivalence());
                    if (!take(',')) break;
                }
            }
            expect(')', '")"');
            return operation(identifier.value, operands, identifier.position);
        }

        function parseUnary() {
            const token = current();
            if (token.type === 'operator' && token.value === 'not') {
                index += 1;
                return operation('not', [parseUnary()], token.position);
            }
            return parsePrimary();
        }

        function parseAnd() {
            let left = parseUnary();
            while (current().type === 'operator' && current().value === 'and') {
                const token = current();
                index += 1;
                left = operation('and', [left, parseUnary()], token.position);
            }
            return left;
        }

        function parseOr() {
            let left = parseAnd();
            while (current().type === 'operator' && current().value === 'or') {
                const token = current();
                index += 1;
                left = operation('or', [left, parseAnd()], token.position);
            }
            return left;
        }

        function parseImplication() {
            const left = parseOr();
            if (current().type === 'operator' && current().value === 'imp') {
                const token = current();
                index += 1;
                return operation('imp', [left, parseImplication()], token.position);
            }
            return left;
        }

        function parseEquivalence() {
            let left = parseImplication();
            while (current().type === 'operator' && current().value === 'iff') {
                const token = current();
                index += 1;
                left = operation('iff', [left, parseImplication()], token.position);
            }
            return left;
        }

        const result = parseEquivalence();
        if (current().type !== 'end') {
            throw syntaxError('Testo inatteso dopo la formula', current().position);
        }
        return result;
    }

    function serializeProlog(node) {
        if (node.kind === 'atom') return node.name;
        if (node.kind === 'unary') {
            return node.operator + '(' + serializeProlog(node.operand) + ')';
        }
        return node.operator + '(' + serializeProlog(node.left) + ',' + serializeProlog(node.right) + ')';
    }

    function needsParentheses(node, parentOperator, side) {
        if (!parentOperator || node.kind === 'atom') return false;
        const nodePrecedence = OPERATORS[node.operator].precedence;
        const parentPrecedence = OPERATORS[parentOperator].precedence;
        if (nodePrecedence < parentPrecedence) return true;
        if (nodePrecedence > parentPrecedence) return false;
        if (parentOperator === 'imp') return side === 'left';
        if (parentOperator === 'not') return false;
        return side === 'right';
    }

    function serializeDisplay(node, parentOperator, side) {
        if (node.kind === 'atom') return node.name;

        let text;
        if (node.kind === 'unary') {
            text = OPERATORS.not.symbol + serializeDisplay(node.operand, 'not', 'operand');
        } else {
            text = serializeDisplay(node.left, node.operator, 'left')
                + ' ' + OPERATORS[node.operator].symbol + ' '
                + serializeDisplay(node.right, node.operator, 'right');
        }
        return needsParentheses(node, parentOperator, side) ? '(' + text + ')' : text;
    }

    function toProlog(source) {
        return serializeProlog(parse(source));
    }

    function toDisplay(source) {
        return serializeDisplay(parse(source), null, null);
    }

    global.LogicFormulaSyntax = Object.freeze({
        parse: parse,
        toProlog: toProlog,
        toDisplay: toDisplay
    });
})(typeof window === 'undefined' ? globalThis : window);
