(function initializeLogicSandbox(global) {
    'use strict';

    function start() {
        const input = document.getElementById('sandboxFormula');
        const compareInput = document.getElementById('sandboxCompareFormula');
        const status = document.getElementById('sandboxStatus');
        const localPreview = document.getElementById('sandboxConstruction');
        const tree = document.getElementById('sandboxTree');
        const treeDetail = document.getElementById('sandboxTreeDetail');
        const result = document.getElementById('sandboxResult');
        const atomInput = document.getElementById('sandboxTreeAtom');
        const builderStatus = document.getElementById('sandboxTreeBuilderStatus');
        const syntax = global.LogicFormulaSyntax;
        const builderApi = global.LogicTreeBuilder;
        const constructionApi = global.LogicFormulaConstruction;
        const constructionRendererApi = global.LogicFormulaConstructionRenderer;
        const treeApi = global.LogicFormulaTree;
        if (!syntax || !builderApi || !constructionApi || !constructionRendererApi || !treeApi || !global.LogicApi) {
            status.textContent = 'Il laboratorio non è disponibile: moduli di analisi mancanti.';
            return;
        }
        const builder = builderApi.create();
        const constructionRenderer = constructionRendererApi.create({
            container: localPreview,
            formatFormula: formatFormula
        });
        let controller = null;
        let requestSequence = 0;
        let builderMode = false;
        let activeFormulaInput = input;

        function cancelAnalysis() {
            requestSequence += 1;
            if (controller) controller.abort();
            controller = null;
        }

        function formatFormula(value) {
            try {
                return syntax.toDisplay(String(value || ''));
            } catch (_) {
                return String(value || '');
            }
        }

        function validateFormula(value) {
            const formula = String(value || '').trim();
            if (!formula) throw new Error('Inserisci una formula.');
            if (formula.length > 500) throw new Error('La formula supera il limite di 500 caratteri.');
            const prolog = syntax.toProlog(formula);
            if (prolog.length > 500) throw new Error('La formula normalizzata supera il limite di 500 caratteri.');
            if (!constructionApi.buildFromFormula(prolog)) {
                throw new Error('La formula non produce una struttura logica valida.');
            }
            return prolog;
        }

        function clearTree() {
            tree.innerHTML = '';
            treeDetail.textContent = '';
        }

        function centerTreeCanvas() {
            tree.scrollLeft = Math.max(0, (tree.scrollWidth - tree.clientWidth) / 2);
            tree.scrollTop = 0;
        }

        function showConstruction(prolog) {
            const trace = constructionApi.buildFromFormula(prolog);
            if (!trace) throw new Error('La formula non produce una struttura logica valida.');
            constructionRenderer.show({ correct: trace, selectedIsCorrect: true });
            return trace;
        }

        function preview() {
            cancelAnalysis();
            tree.classList.remove('is-builder-mode');
            constructionRenderer.hide();
            clearTree();
            try {
                const prolog = validateFormula(input.value);
                const trace = showConstruction(prolog);
                treeApi.render(tree, trace, {
                    detailElement: treeDetail,
                    formatFormula: formatFormula,
                    fullLabels: true
                });
                centerTreeCanvas();
                status.textContent = 'Sintassi riconosciuta. Puoi avviare una verifica.';
                return trace;
            } catch (error) {
                status.textContent = error.message;
                return null;
            }
        }

        function builderMessage(state) {
            const byId = new Map(state.nodes.map(function(node) { return [node.id, node]; }));
            if (state.nodes.length === 0) return 'L\'albero è vuoto. Aggiungi un atomo per iniziare.';
            if (state.selected.length === 2) {
                return 'Sinistra: ' + formatFormula(byId.get(state.selected[0]).result_prolog)
                    + '. Destra: ' + formatFormula(byId.get(state.selected[1]).result_prolog)
                    + '. Ora scegli un operatore binario.';
            }
            if (state.selected.length === 1) {
                return 'Prima radice selezionata: ' + formatFormula(byId.get(state.selected[0]).result_prolog)
                    + '. Seleziona la radice destra oppure applica ¬.';
            }
            if (state.roots.length === 1) {
                return 'Formula pronta: ' + formatFormula(state.completeFormulaProlog)
                    + '. Puoi analizzarla o aggiungere un altro atomo.';
            }
            return state.roots.length + ' radici disponibili. Seleziona prima quella sinistra e poi quella destra.';
        }

        function syncBuilderFormula(state) {
            constructionRenderer.hide();
            if (state.completeFormulaProlog) {
                input.value = formatFormula(state.completeFormulaProlog);
                showConstruction(state.completeFormulaProlog);
                status.textContent = 'Formula costruita dall\'albero e pronta per l\'analisi.';
                return;
            }
            input.value = '';
            status.textContent = state.nodes.length
                ? 'Completa i collegamenti per ottenere una sola formula.'
                : 'Inserisci una formula oppure costruiscila dall\'albero.';
        }

        function restoreBuilderFocus(target, state) {
            if (!target) return;
            if (target === 'binary-operator') {
                const binaryOperator = document.querySelector('#sandboxTreeOperators [data-tree-operator="and"]');
                if (binaryOperator) binaryOperator.focus();
                return;
            }
            const available = new Set(state.roots);
            const groups = tree.querySelectorAll('[data-node-id]');
            for (let index = 0; index < groups.length; index += 1) {
                if (groups[index].getAttribute('data-node-id') === target && available.has(target)) {
                    groups[index].focus();
                    return;
                }
            }
        }

        function renderBuilder(focusTarget) {
            const state = builder.getState();
            tree.classList.add('is-builder-mode');
            clearTree();
            builderStatus.textContent = builderMessage(state);
            syncBuilderFormula(state);
            if (state.nodes.length === 0) return;
            treeApi.render(tree, builder.getTrace(), {
                detailElement: treeDetail,
                formatFormula: formatFormula,
                fullLabels: true,
                selectedNodeIds: state.selected,
                availableRootIds: state.roots,
                onSelect: function(node) {
                    try {
                        const nextState = builder.toggleSelection(node.id);
                        cancelAnalysis();
                        renderBuilder(nextState.selected.length === 2 ? 'binary-operator' : node.id);
                    } catch (error) {
                        builderStatus.textContent = error.message;
                    }
                }
            });
            centerTreeCanvas();
            restoreBuilderFocus(focusTarget, state);
        }

        async function request(path, payload) {
            cancelAnalysis();
            const sequence = requestSequence;
            const requestController = new AbortController();
            controller = requestController;
            status.textContent = 'Analisi in corso…';
            result.textContent = '';
            try {
                const response = await global.LogicApi.postJson(path, payload, { signal: requestController.signal, timeoutMs: 20000 });
                if (sequence !== requestSequence) return;
                renderResult(response.result);
                status.textContent = 'Analisi completata.';
            } catch (error) {
                if (sequence !== requestSequence) return;
                if (error.code === 'REQUEST_ABORTED') return;
                status.textContent = error.message + (error.requestId ? ' (richiesta ' + error.requestId + ')' : '');
            } finally {
                if (sequence === requestSequence && controller === requestController) controller = null;
            }
        }

        function displayResultValue(value) {
            if (typeof value === 'string' && /(?:not|and|or|imp|iff)\s*\(/.test(value)) {
                return formatFormula(value);
            }
            if (Array.isArray(value)) return value.map(displayResultValue);
            if (value && typeof value === 'object') {
                const output = {};
                Object.keys(value).forEach(function(key) { output[key] = displayResultValue(value[key]); });
                return output;
            }
            return value;
        }

        function renderResult(value) {
            result.innerHTML = '';
            if (value && Array.isArray(value.vars) && Array.isArray(value.rows)) {
                const wrap = document.createElement('div');
                wrap.className = 'table';
                const table = document.createElement('table');
                const caption = document.createElement('caption');
                caption.textContent = 'Tabella di verità della formula';
                const head = document.createElement('thead');
                const headRow = document.createElement('tr');
                value.vars.concat(['Risultato']).forEach(function(name) {
                    const cell = document.createElement('th'); cell.textContent = String(name); headRow.appendChild(cell);
                });
                head.appendChild(headRow);
                const body = document.createElement('tbody');
                value.rows.forEach(function(row) {
                    const values = {};
                    (row.valuation || []).forEach(function(entry) {
                        const parts = String(entry).split('-'); values[parts[0]] = parts[1];
                    });
                    const tableRow = document.createElement('tr');
                    value.vars.map(function(name) { return values[name] || ''; }).concat([row.result]).forEach(function(cellValue) {
                        const cell = document.createElement('td'); cell.textContent = String(cellValue); tableRow.appendChild(cell);
                    });
                    body.appendChild(tableRow);
                });
                table.appendChild(caption); table.appendChild(head); table.appendChild(body); wrap.appendChild(table); result.appendChild(wrap);
                return;
            }
            const output = document.createElement('pre');
            output.textContent = JSON.stringify(displayResultValue(value), null, 2);
            result.appendChild(output);
        }

        function analyze(path) {
            try {
                const prolog = validateFormula(input.value);
                input.value = formatFormula(prolog);
                request(path, { expr: prolog, timeout: 10 });
            } catch (error) { status.textContent = error.message; }
        }

        function normalizeFormulaField(field) {
            if (!field.value.trim()) return;
            try {
                field.value = formatFormula(validateFormula(field.value));
            } catch (_) {
                /* L'errore completo resta affidato all'anteprima o al pulsante di analisi. */
            }
        }

        function resetBuilderForManualInput() {
            if (!builderMode) return;
            builderMode = false;
            builder.reset();
            builderStatus.textContent = 'La formula è in modifica manuale. Aggiungi un atomo per iniziare un nuovo albero.';
        }

        function insertSymbol(target, symbol) {
            const start = target.selectionStart;
            const end = target.selectionEnd;
            const selectedText = target.value.slice(start, end).trim();
            let insertion;
            if (symbol === '¬') {
                insertion = selectedText ? '¬(' + selectedText + ')' : '¬';
            } else {
                insertion = selectedText ? selectedText + ' ' + symbol + ' ' : ' ' + symbol + ' ';
            }
            target.setRangeText(insertion, start, end, 'end');
            target.focus();
            if (target === input) {
                resetBuilderForManualInput();
                preview();
            } else {
                cancelAnalysis();
                result.innerHTML = '';
                status.textContent = 'Formula di confronto modificata. Avvia una nuova analisi.';
            }
        }

        input.addEventListener('input', function() {
            resetBuilderForManualInput();
            preview();
        });
        compareInput.addEventListener('input', function() {
            cancelAnalysis();
            result.innerHTML = '';
            status.textContent = 'Formula di confronto modificata. Avvia una nuova analisi.';
        });
        [input, compareInput].forEach(function(field) {
            field.addEventListener('focus', function() { activeFormulaInput = field; });
            field.addEventListener('blur', function() { normalizeFormulaField(field); });
        });
        document.getElementById('sandboxSymbols').addEventListener('click', function(event) {
            const button = event.target.closest('[data-symbol]');
            if (!button) return;
            insertSymbol(activeFormulaInput, button.dataset.symbol);
        });
        document.getElementById('sandboxTreeAddAtom').addEventListener('click', function() {
            try {
                const node = builder.addAtom(atomInput.value);
                cancelAnalysis();
                builderMode = true;
                atomInput.value = '';
                result.innerHTML = '';
                renderBuilder();
                treeDetail.textContent = 'Atomo aggiunto: ' + formatFormula(node.result_prolog) + '.';
                atomInput.focus();
            } catch (error) {
                builderStatus.textContent = error.message;
                atomInput.focus();
            }
        });
        atomInput.addEventListener('keydown', function(event) {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            document.getElementById('sandboxTreeAddAtom').click();
        });
        document.getElementById('sandboxTreeOperators').addEventListener('click', function(event) {
            const button = event.target.closest('[data-tree-operator]');
            if (!button) return;
            try {
                const node = builder.applyOperator(button.dataset.treeOperator);
                cancelAnalysis();
                result.innerHTML = '';
                renderBuilder();
                treeDetail.textContent = 'Nuova radice: ' + formatFormula(node.result_prolog) + '.';
            } catch (error) {
                builderStatus.textContent = error.message;
            }
        });
        document.getElementById('sandboxTreeReset').addEventListener('click', function() {
            cancelAnalysis();
            builderMode = true;
            builder.reset();
            input.value = '';
            result.innerHTML = '';
            renderBuilder();
            atomInput.focus();
        });
        document.getElementById('sandboxVariables').addEventListener('click', function() { analyze('/api/prolog-bridge/logic/vars-in-formula'); });
        document.getElementById('sandboxTruthTable').addEventListener('click', function() { analyze('/api/prolog-bridge/logic/truth-table-auto'); });
        document.getElementById('sandboxTautology').addEventListener('click', function() { analyze('/api/prolog-bridge/equivalence/tautology'); });
        document.getElementById('sandboxRewrite').addEventListener('click', function() { analyze('/api/prolog-bridge/rewrite/rewrite-path'); });
        document.getElementById('sandboxCompare').addEventListener('click', function() {
            try {
                const left = validateFormula(input.value);
                const right = validateFormula(compareInput.value);
                input.value = formatFormula(left);
                compareInput.value = formatFormula(right);
                request('/api/prolog-bridge/equivalence/equiv', {
                    left: left,
                    right: right,
                    timeout: 10
                });
            } catch (error) { status.textContent = error.message; }
        });
        document.getElementById('sandboxClear').addEventListener('click', function() {
            cancelAnalysis();
            builderMode = false;
            builder.reset();
            input.value = '';
            compareInput.value = '';
            atomInput.value = '';
            result.innerHTML = '';
            constructionRenderer.hide();
            clearTree();
            tree.classList.remove('is-builder-mode');
            builderStatus.textContent = 'L\'albero è vuoto. Aggiungi un atomo per iniziare.';
            status.textContent = 'Inserisci una formula oppure costruiscila dall\'albero.';
        });

        status.textContent = 'Inserisci una formula oppure costruiscila dall\'albero.';
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})(window);
