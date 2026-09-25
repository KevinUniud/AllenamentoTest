/*
 * Contratto e funzioni pure per le tracce di costruzione delle formule.
 */
(function exposeFormulaConstruction(global) {
    'use strict';

    const VERSION = 1;
    const VALID_KINDS = new Set(['atom', 'predicate', 'unary', 'binary', 'quantifier']);
    const BINARY_LABELS = {
        and: 'congiunzione',
        or: 'disgiunzione',
        imp: 'implicazione',
        iff: 'doppia implicazione'
    };

    function cleanDetails(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
        const details = {};
        Object.keys(raw).forEach(function(key) {
            const value = raw[key];
            if (typeof value === 'string' || typeof value === 'number') {
                details[String(key)] = String(value);
            }
        });
        return details;
    }

    function normalize(raw) {
        if (!raw || typeof raw !== 'object' || raw.version !== VERSION || !Array.isArray(raw.steps)) {
            return null;
        }
        const finalFormula = String(raw.final_formula_prolog || '').trim();
        const strategy = String(raw.strategy || '').trim();
        if (!finalFormula || !strategy || raw.steps.length === 0) return null;

        const knownNodes = new Set();
        const steps = [];
        for (let position = 0; position < raw.steps.length; position += 1) {
            const source = raw.steps[position];
            if (!source || typeof source !== 'object') return null;
            const nodeId = String(source.node_id || '').trim();
            const kind = String(source.kind || '').trim();
            const result = String(source.result_prolog || '').trim();
            const operands = Array.isArray(source.operands)
                ? source.operands.map(function(item) { return String(item || '').trim(); }).filter(Boolean)
                : [];
            if (!nodeId || !VALID_KINDS.has(kind) || !result || knownNodes.has(nodeId)) return null;
            if (operands.some(function(node) { return !knownNodes.has(node); })) return null;

            const operator = source.operator == null ? null : String(source.operator).trim() || null;
            const depth = Number.isInteger(source.depth) && source.depth >= 0 ? source.depth : 0;
            steps.push({
                index: position + 1,
                node_id: nodeId,
                kind: kind,
                operator: operator,
                operands: operands,
                result_prolog: result,
                depth: depth,
                details: cleanDetails(source.details)
            });
            knownNodes.add(nodeId);
        }

        if (steps[steps.length - 1].result_prolog !== finalFormula) return null;
        return {
            version: VERSION,
            strategy: strategy,
            final_formula_prolog: finalFormula,
            steps: steps
        };
    }

    function describeStep(step) {
        if (!step || typeof step !== 'object') return 'Costruisci il passaggio successivo.';
        if (step.kind === 'atom') {
            return 'Introduci l\'atomo ' + (step.details.name || step.result_prolog) + '.';
        }
        if (step.kind === 'predicate') {
            return 'Costruisci il predicato ' + step.result_prolog + '.';
        }
        if (step.kind === 'unary' && step.operator === 'not') {
            return 'Applica la negazione al risultato precedente.';
        }
        if (step.kind === 'binary') {
            const label = BINARY_LABELS[step.operator] || ('operatore ' + (step.operator || 'binario'));
            return 'Combina i due risultati precedenti con la ' + label + '.';
        }
        if (step.kind === 'quantifier') {
            const variable = step.details.bound_variable || 'x';
            if (step.operator === 'forall') {
                return 'Applica il quantificatore universale alla variabile ' + variable + '.';
            }
            if (step.operator === 'exists') {
                return 'Applica il quantificatore esistenziale alla variabile ' + variable + '.';
            }
        }
        return 'Ottieni il risultato del passaggio.';
    }

    function parseTerm(source) {
        const text = String(source || '').trim();
        let index = 0;

        function skipSpaces() {
            while (index < text.length && /\s/.test(text[index])) index += 1;
        }

        function parseIdentifier() {
            skipSpaces();
            const start = index;
            while (index < text.length && /[A-Za-z0-9_]/.test(text[index])) index += 1;
            const identifier = text.slice(start, index);
            if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(identifier)) throw new Error('Identificatore non valido');
            return identifier;
        }

        function consume(token) {
            skipSpaces();
            if (text.slice(index, index + token.length) !== token) throw new Error('Token mancante');
            index += token.length;
        }

        function term() {
            const name = parseIdentifier();
            skipSpaces();
            if (text[index] !== '(') return { name: name, arguments: [] };
            consume('(');
            const argumentsList = [term()];
            skipSpaces();
            while (text[index] === ',') {
                consume(',');
                argumentsList.push(term());
                skipSpaces();
            }
            consume(')');
            return { name: name, arguments: argumentsList };
        }

        const result = term();
        skipSpaces();
        if (index !== text.length) throw new Error('Testo non consumato');
        return result;
    }

    function renderTerm(term) {
        if (!term.arguments.length) return term.name;
        return term.name + '(' + term.arguments.map(renderTerm).join(',') + ')';
    }

    function termDepth(term) {
        if (!term.arguments.length || !['not', 'and', 'or', 'imp', 'iff', 'forall', 'exists'].includes(term.name)) {
            return 0;
        }
        if (term.name === 'forall' || term.name === 'exists') return 1 + termDepth(term.arguments[1]);
        return 1 + Math.max.apply(null, term.arguments.map(termDepth));
    }

    function buildFromFormula(formula) {
        let root;
        try {
            root = parseTerm(formula);
        } catch (_) {
            return null;
        }
        const steps = [];

        function append(nodeId, kind, operator, operands, result, depth, details) {
            steps.push({
                index: steps.length + 1,
                node_id: nodeId,
                kind: kind,
                operator: operator,
                operands: operands,
                result_prolog: result,
                depth: depth,
                details: details || {}
            });
            return nodeId;
        }

        function visit(term, nodeId) {
            const rendered = renderTerm(term);
            if (!term.arguments.length) {
                return append(nodeId, 'atom', null, [], rendered, 0, { name: term.name });
            }
            if (term.name === 'not' && term.arguments.length === 1) {
                const childId = nodeId + '.operand';
                visit(term.arguments[0], childId);
                return append(nodeId, 'unary', 'not', [childId], rendered, termDepth(term));
            }
            if (['and', 'or', 'imp', 'iff'].includes(term.name) && term.arguments.length === 2) {
                const leftId = nodeId + '.left';
                const rightId = nodeId + '.right';
                visit(term.arguments[0], leftId);
                visit(term.arguments[1], rightId);
                return append(nodeId, 'binary', term.name, [leftId, rightId], rendered, termDepth(term));
            }
            if (['forall', 'exists'].includes(term.name) && term.arguments.length === 2 && !term.arguments[0].arguments.length) {
                const bodyId = nodeId + '.body';
                visit(term.arguments[1], bodyId);
                return append(nodeId, 'quantifier', term.name, [bodyId], rendered, termDepth(term), {
                    bound_variable: term.arguments[0].name
                });
            }
            return append(nodeId, 'predicate', term.name, [], rendered, 0, {
                name: term.name,
                arguments: term.arguments.map(renderTerm).join(',')
            });
        }

        visit(root, 'root');
        return normalize({
            version: VERSION,
            strategy: 'client_term_postorder',
            final_formula_prolog: renderTerm(root),
            steps: steps
        });
    }

    function buildQuantifiedTrace(quantifier, baseFormula, negated, finalFormula, baseFormulaSource) {
        const base = String(baseFormula || '').trim() || 'p';
        const source = String(baseFormulaSource || '').trim();
        const quantifierName = quantifier === '∀' || quantifier === 'forall' ? 'forall' : 'exists';
        const finalText = String(finalFormula || '').trim();
        const baseTrace = source ? buildFromFormula(source) : null;
        const baseRootId = 'root.body' + (negated ? '.operand' : '');
        const steps = baseTrace
            ? baseTrace.steps.map(function(step, index) {
                function remapNode(nodeId) {
                    return baseRootId + (nodeId === 'root' ? '' : nodeId.slice('root'.length));
                }
                return {
                    index: index + 1,
                    node_id: remapNode(step.node_id),
                    kind: step.kind,
                    operator: step.operator,
                    operands: step.operands.map(remapNode),
                    result_prolog: step.result_prolog,
                    depth: step.depth,
                    details: step.details
                };
            })
            : [{
                index: 1,
                node_id: baseRootId,
                kind: 'atom',
                operator: null,
                operands: [],
                result_prolog: base,
                depth: 0,
                details: { name: base }
            }];
        let bodyId = baseRootId;
        let bodyDepth = steps[steps.length - 1].depth;
        if (negated) {
            bodyId = 'root.body';
            bodyDepth += 1;
            steps.push({
                index: steps.length + 1,
                node_id: bodyId,
                kind: 'unary',
                operator: 'not',
                operands: [baseRootId],
                result_prolog: baseTrace ? 'not(' + baseTrace.final_formula_prolog + ')' : '¬(' + base + ')',
                depth: bodyDepth,
                details: {}
            });
        }
        steps.push({
            index: steps.length + 1,
            node_id: 'root',
            kind: 'quantifier',
            operator: quantifierName,
            operands: [bodyId],
            result_prolog: finalText,
            depth: bodyDepth + 1,
            details: { bound_variable: 'x' }
        });
        return normalize({
            version: VERSION,
            strategy: 'client_quantifier_rule',
            final_formula_prolog: finalText,
            steps: steps
        });
    }

    global.LogicFormulaConstruction = Object.freeze({
        VERSION: VERSION,
        normalize: normalize,
        describeStep: describeStep,
        buildFromFormula: buildFromFormula,
        buildQuantifiedTrace: buildQuantifiedTrace
    });
})(window);
