(function() {
    /*
     * Utility condivise per quiz:
     * parsing formule, normalizzazione, conversioni e helper random.
     */

    /**
     * Alterna il tipo di parentesi per distinguere i livelli annidati.
     * @pre text e stringa o valore convertibile a stringa.
     * @post Restituisce una stringa equivalente in cui i livelli usano (), [] o {}.
     */
    function differentiateParentheses(text) {
        const source = String(text || '');
        const opens = ['(', '[', '{'];
        const closes = [')', ']', '}'];
        let depth = 0;
        let maxDepth = 0;

        for (let i = 0; i < source.length; i += 1) {
            const ch = source[i];
            if (ch === '(') {
                depth += 1;
                if (depth > maxDepth) maxDepth = depth;
            } else if (ch === ')') {
                depth = Math.max(0, depth - 1);
            }
        }

        depth = 0;
        const kindStack = [];
        let out = '';
        for (let i = 0; i < source.length; i += 1) {
            const ch = source[i];
            if (ch === '(') {
                const level = depth + 1;
                const kind = ((maxDepth - level) % 3 + 3) % 3;
                out += opens[kind];
                kindStack.push(kind);
                depth += 1;
                continue;
            }
            if (ch === ')') {
                depth = Math.max(0, depth - 1);
                const kind = kindStack.length > 0 ? kindStack.pop() : 0;
                out += closes[kind];
                continue;
            }
            out += ch;
        }
        return out;
    }

    /**
     * Effettua un parse robusto di un intero positivo.
     * @pre fallback e un numero intero positivo.
     * @post Restituisce sempre un intero >= 1 oppure fallback.
     */
    function parsePositiveInt(value, fallback) {
        const n = Number(value);
        if (!Number.isFinite(n)) return fallback;
        const rounded = Math.floor(n);
        if (rounded < 1) return fallback;
        return rounded;
    }

    function tokenizeFormula(input) {
        const tokens = [];
        let i = 0;
        while (i < input.length) {
            const c = input[i];
            if (/\s/.test(c)) {
                i += 1;
                continue;
            }
            if (c === '(' || c === ')' || c === ',') {
                tokens.push(c);
                i += 1;
                continue;
            }
            let j = i;
            while (j < input.length && /[A-Za-z0-9_]/.test(input[j])) {
                j += 1;
            }
            if (j === i) {
                i += 1;
                continue;
            }
            tokens.push(input.slice(i, j));
            i = j;
        }
        return tokens;
    }

    function parsePrologFormula(input) {
        const tokens = tokenizeFormula(input || '');
        let idx = 0;

        function parseNode() {
            if (idx >= tokens.length) return null;
            const token = tokens[idx];

            if (token === '(' || token === ')' || token === ',') {
                return null;
            }

            idx += 1;
            if (tokens[idx] === '(') {
                idx += 1;
                const args = [];
                while (idx < tokens.length && tokens[idx] !== ')') {
                    const arg = parseNode();
                    if (arg) args.push(arg);
                    if (tokens[idx] === ',') idx += 1;
                }
                if (tokens[idx] === ')') idx += 1;
                return { type: 'call', name: token.toLowerCase(), args: args };
            }

            return { type: 'var', name: token };
        }

        return parseNode();
    }

    function serializePrologFormula(ast) {
        if (!ast) return '';
        if (ast.type === 'var') return String(ast.name || '');
        if (ast.type !== 'call') return '';
        return String(ast.name || '') + '(' + (ast.args || []).map(serializePrologFormula).join(',') + ')';
    }

    /**
     * Restituisce lo scheletro positivo di una formula Prolog.
     *
     * È usato soltanto per scegliere la base, ancora non mostrata, degli
     * esercizi di negazione dei quantificatori in forma parlata. La rimozione
     * opera sull'AST e non sul testo finale: domanda, opzioni e construction
     * trace vengono quindi ricostruiti tutti dalla stessa formula.
     */
    function removeFormulaNegations(formula) {
        const source = String(formula || '').trim();
        if (!source) return '';
        const ast = parsePrologFormula(source);
        if (!ast) return source;

        function visit(node) {
            if (!node || node.type === 'var') return node;
            if (node.type !== 'call') return node;
            const args = node.args || [];
            if (node.name === 'not' && args.length === 1) {
                return visit(args[0]);
            }
            return {
                type: 'call',
                name: node.name,
                args: args.map(visit)
            };
        }

        return serializePrologFormula(visit(ast)) || source;
    }

    /**
     * Rende leggibili anche le formule Prolog di sessioni parlate precedenti.
     * Quando due negazioni cadono sullo stesso ramo, le porta fino agli atomi
     * mediante equivalenze logiche (non tramite sostituzioni della frase).
     * Non cambia mai la formula salvata, la risposta o il payload API.
     */
    function spokenFriendlyPrologFormula(formula) {
        const source = String(formula || '').trim();
        if (!source || !/^[A-Za-z0-9_,()\s]+$/.test(source)) return source;
        const ast = parsePrologFormula(source);
        if (!ast || serializePrologFormula(ast).toLowerCase() !== source.replace(/\s+/g, '').toLowerCase()) {
            return source;
        }

        function excessiveNegation(node, count) {
            if (!node || node.type !== 'call') return false;
            const nextCount = count + (node.name === 'not' ? 1 : 0);
            if (nextCount > 1) return true;
            return (node.args || []).some(function(arg) {
                return excessiveNegation(arg, nextCount);
            });
        }

        if (!excessiveNegation(ast, 0)) return source;

        function call(name, left, right) {
            return { type: 'call', name: name, args: right === undefined ? [left] : [left, right] };
        }

        function normalize(node, negated) {
            if (!node || node.type !== 'call') {
                return negated ? call('not', node) : node;
            }
            const args = node.args || [];
            if (node.name === 'not' && args.length === 1) {
                return normalize(args[0], !negated);
            }
            if ((node.name === 'and' || node.name === 'or') && args.length === 2) {
                const operator = negated ? (node.name === 'and' ? 'or' : 'and') : node.name;
                return call(operator, normalize(args[0], negated), normalize(args[1], negated));
            }
            if ((node.name === 'forall' || node.name === 'exists') && args.length === 2) {
                const quantifier = negated ? (node.name === 'forall' ? 'exists' : 'forall') : node.name;
                return call(quantifier, args[0], normalize(args[1], negated));
            }
            if (node.name === 'imp' && args.length === 2) {
                // Una implicazione non negata resta in forma compatta.
                // La sua negazione equivale ad A ∧ ¬B.
                return negated
                    ? call('and', normalize(args[0], false), normalize(args[1], true))
                    : call('imp', normalize(args[0], false), normalize(args[1], false));
            }
            if ((node.name === 'iff' || node.name === 'equiv') && args.length === 2) {
                // Solo la forma negativa richiede l'espansione XOR.
                return negated
                    ? call('or',
                        call('and', normalize(args[0], false), normalize(args[1], true)),
                        call('and', normalize(args[0], true), normalize(args[1], false)))
                    : call(node.name, normalize(args[0], false), normalize(args[1], false));
            }
            // Predicati/operazioni sconosciute non si riscrivono: la negazione
            // può restare davanti a un atomo, senza inventare una legge logica.
            return negated ? call('not', node) : node;
        }

        return serializePrologFormula(normalize(ast, false)) || source;
    }

    function formatAst(ast, parentPrec, parentName, side) {
        if (!ast) return '';

        if (ast.type === 'var') {
            return ast.name;
        }

        if (ast.type !== 'call') {
            return '';
        }

        const name = ast.name;
        const args = ast.args || [];

        if (name === 'not' && args.length === 1) {
            const inner = formatAst(args[0], 4, name, 'operand');
            const text = '¬' + inner;
            return parentPrec > 4 ? '(' + text + ')' : text;
        }

        if ((name === 'forall' || name === 'exists') && args.length === 2) {
            const quantifier = name === 'forall' ? '∀' : '∃';
            const variable = String(formatAst(args[0], -1, name, 'variable') || '').trim().toLowerCase();
            const bodyRaw = String(formatAst(args[1], -1, name, 'body') || '').trim();
            // Le parentesi finali di un predicato (es. R(x)) non indicano che
            // l'intero corpo sia già racchiuso: delimitiamo sempre lo scope.
            const body = bodyRaw ? '(' + bodyRaw + ')' : '()';
            return quantifier + variable + ' ' + body;
        }

        const binaryMap = {
            and: { symbol: '∧', prec: 3 },
            or: { symbol: '∨', prec: 2 },
            imp: { symbol: '→', prec: 1 },
            equiv: { symbol: '↔', prec: 0 },
            iff: { symbol: '↔', prec: 0 }
        };

        const op = binaryMap[name];
        if (op && args.length === 2) {
            const left = formatAst(args[0], op.prec, name, 'left');
            const right = formatAst(args[1], op.prec, name, 'right');
            const text = left + ' ' + op.symbol + ' ' + right;
            let needsParens = parentPrec > op.prec;
            if (parentPrec === op.prec) {
                // Mantiene lo stesso raggruppamento del Laboratorio: l'implicazione
                // e associativa a destra, gli altri operatori sono resi a sinistra.
                needsParens = parentName === 'imp' ? side === 'left' : side === 'right';
            }
            return needsParens ? '(' + text + ')' : text;
        }

        const renderedArgs = args.map(function(arg) {
            return formatAst(arg, -1, name, 'argument');
        }).join(', ');
        return name + '(' + renderedArgs + ')';
    }

    /**
     * Traduce la formula Prolog nella notazione logica leggibile.
     * @pre formula e una stringa Prolog-like oppure vuota.
     * @post Restituisce una stringa renderizzata con simboli logici o la formula originale se non parsabile.
     */
    function prologToLogical(formula) {
        if (!formula || typeof formula !== 'string') return '';
        const ast = parsePrologFormula(formula);
        const rendered = formatAst(ast, -1).trim();
        return rendered || formula;
    }

    /**
     * Miscelazione Fisher-Yates non distruttiva.
     * @pre arr e un array.
     * @post Restituisce un nuovo array con gli stessi elementi in ordine casuale.
     */
    function shuffle(arr) {
        const out = arr.slice();
        for (let i = out.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            const tmp = out[i];
            out[i] = out[j];
            out[j] = tmp;
        }
        return out;
    }

    /**
     * Estrae un elemento casuale da un array.
     * @pre arr contiene almeno un elemento.
     * @post Restituisce uno degli elementi presenti in arr.
     */
    function pickRandom(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    /**
     * Normalizza un nome per ottenere una chiave stabile indipendente da maiuscole/spazi.
     * @pre value e una stringa o un valore convertibile a stringa.
     * @post Restituisce una chiave in lowercase, trim e normalizzazione Unicode.
     */
    function normalizeNameKey(value) {
        return String(value || '')
            .normalize('NFKC')
            .trim()
            .toLowerCase();
    }

    /**
     * Verifica se un'etichetta rappresenta un riferimento generico a persona.
     * @pre value e una stringa o un valore convertibile a stringa.
     * @post Restituisce true per label generiche come "persona" o "la persona".
     */
    function isGenericPersonLabel(value) {
        const key = normalizeNameKey(value).replace(/\s+/g, ' ');
        return key === 'persona' || key === 'la persona';
    }

    /**
     * Hash deterministico non crittografico per mappare stringhe a interi.
     * @pre input e una stringa.
     * @post Restituisce un intero senza segno stabile tra esecuzioni.
     */
    function stableStringHash(input) {
        let hash = 5381;
        for (let i = 0; i < input.length; i += 1) {
            hash = ((hash << 5) + hash) ^ input.charCodeAt(i);
        }
        return hash >>> 0;
    }

    /**
     * Restituisce un colore deterministico per un nome.
     * @pre palette e un array non vuoto di colori CSS validi.
     * @post Stesso nome normalizzato produce sempre lo stesso colore della palette.
     */
    function getDeterministicNameColor(name, palette) {
        const key = normalizeNameKey(name);
        if (!key || !Array.isArray(palette) || palette.length === 0) return '';
        const index = stableStringHash(key) % palette.length;
        return palette[index];
    }

    /**
     * Associa in modo deterministico atomi, nomi e azioni per la forma parlata.
     * @pre atoms, names e actions sono array; nomi e azioni possono essere vuoti.
     * @post Lo stesso insieme di atomi e le stesse liste producono sempre la stessa mappa.
     */
    function buildStableSpokenMap(atoms, names, actions) {
        const namePool = Array.isArray(names) ? names.filter(Boolean).map(String) : [];
        const actionPool = Array.isArray(actions) ? actions.filter(Boolean).map(String) : [];
        if (namePool.length === 0 || actionPool.length === 0) return {};

        const orderedAtoms = Array.from(new Set((Array.isArray(atoms) ? atoms : [])
            .map(normalizeNameKey)
            .filter(Boolean)))
            .sort();
        const map = {};
        const signature = orderedAtoms.join('|');
        const nameOffset = stableStringHash('names|' + signature) % namePool.length;
        const actionOffset = stableStringHash('actions|' + signature) % actionPool.length;

        orderedAtoms.forEach(function(atom, index) {
            map[atom] = {
                nome: namePool[(nameOffset + index) % namePool.length],
                azione: actionPool[(actionOffset + index) % actionPool.length]
            };
        });
        return map;
    }

    /**
     * Converte le righe di legenda API (es. "P = Luca corre") nella mappa parlata.
     * @pre infoLines e actions sono array; le righe non conformi vengono ignorate.
     * @post Restituisce soltanto le associazioni esplicitamente presenti nella legenda.
     */
    function buildSpokenMapFromLegend(infoLines, actions) {
        const actionPool = (Array.isArray(actions) ? actions : [])
            .filter(Boolean)
            .map(String)
            .sort(function(left, right) { return right.length - left.length; });
        const map = {};
        if (!Array.isArray(infoLines)) return map;

        infoLines.forEach(function(line) {
            const match = String(line || '').match(
                /^\s*([A-Za-z][A-Za-z0-9_]*)(?:\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\))?\s*(?:=|:)\s*(.+?)\s*$/
            );
            if (!match) return;

            const atom = normalizeNameKey(match[1]);
            const variable = normalizeNameKey(match[2]);
            const description = String(match[3] || '').trim();
            const normalizedDescription = normalizeNameKey(description);
            let action = actionPool.find(function(candidate) {
                const normalizedAction = normalizeNameKey(candidate);
                return normalizedDescription === normalizedAction
                    || normalizedDescription.endsWith(' ' + normalizedAction);
            }) || '';
            let subject = action ? description.slice(0, description.length - action.length).trim() : '';

            if (!action) {
                const fallback = description.match(/^(\S+)\s+(.+)$/);
                if (!fallback) return;
                subject = fallback[1];
                action = fallback[2].trim();
            }
            if (!atom || !subject || !action) return;

            map[atom] = {
                nome: variable && normalizeNameKey(subject) === variable ? 'persona' : subject,
                azione: action
            };
        });
        return map;
    }

    /**
     * Risolve la mappa parlata privilegiando la legenda API rispetto al fallback stabile.
     * @post Il fallback viene usato solo quando nessuna riga di legenda e valida.
     */
    function resolveSpokenMap(infoLines, atoms, names, actions) {
        const legendMap = buildSpokenMapFromLegend(infoLines, actions);
        if (Object.keys(legendMap).length > 0) return legendMap;
        return buildStableSpokenMap(atoms, names, actions);
    }

    window.quizShared = {
        differentiateParentheses: differentiateParentheses,
        parsePositiveInt: parsePositiveInt,
        tokenizeFormula: tokenizeFormula,
        parsePrologFormula: parsePrologFormula,
        serializePrologFormula: serializePrologFormula,
        removeFormulaNegations: removeFormulaNegations,
        spokenFriendlyPrologFormula: spokenFriendlyPrologFormula,
        formatAst: formatAst,
        prologToLogical: prologToLogical,
        shuffle: shuffle,
        pickRandom: pickRandom,
        normalizeNameKey: normalizeNameKey,
        isGenericPersonLabel: isGenericPersonLabel,
        getDeterministicNameColor: getDeterministicNameColor,
        buildStableSpokenMap: buildStableSpokenMap,
        buildSpokenMapFromLegend: buildSpokenMapFromLegend,
        resolveSpokenMap: resolveSpokenMap
    };
})();
