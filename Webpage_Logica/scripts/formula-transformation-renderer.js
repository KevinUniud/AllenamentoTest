/* Componente DOM accessibile per mostrare come una risposta è stata raggiunta. */
(function exposeFormulaTransformationRenderer(global) {
    'use strict';

    let panelSequence = 0;

    function create(options) {
        const settings = options || {};
        const container = settings.container || null;
        const transformationApi = global.LogicFormulaTransformation;
        const formatFormula = typeof settings.formatFormula === 'function'
            ? settings.formatFormula
            : function(value) { return String(value || ''); };

        function hide() {
            if (!container) return;
            container.hidden = true;
            container.textContent = '';
        }

        function appendFormula(parent, labelText, formulaText, className, shouldFormat, valueClassName) {
            const row = document.createElement('p');
            row.className = className;
            const label = document.createElement('span');
            label.className = 'formula-transformation-label';
            label.textContent = labelText + ': ';
            const formula = document.createElement('code');
            formula.className = 'formula-transformation-formula'
                + (valueClassName ? ' ' + valueClassName : '');
            formula.textContent = shouldFormat === false ? formulaText : formatFormula(formulaText);
            row.appendChild(label);
            row.appendChild(formula);
            parent.appendChild(row);
        }

        function formattedRelation(step) {
            return formatFormula(step.before_subformula_prolog || step.before_prolog)
                + ' ' + transformationApi.relationSymbol(step) + ' '
                + formatFormula(step.after_subformula_prolog || step.after_prolog);
        }

        function appendTrace(parent, title, rawTrace) {
            const trace = transformationApi && transformationApi.normalize(rawTrace);
            if (!trace) return false;

            const section = document.createElement('section');
            section.className = 'formula-transformation-trace';
            const heading = document.createElement('h3');
            heading.className = 'formula-transformation-title';
            heading.textContent = title;
            section.appendChild(heading);
            appendFormula(section, 'Formula della domanda', trace.source_formula_prolog, 'formula-transformation-source');

            const list = document.createElement('ol');
            list.className = 'formula-transformation-steps';
            trace.steps.forEach(function(step, index) {
                const item = document.createElement('li');
                item.className = 'formula-transformation-step';
                if (index === trace.steps.length - 1) item.classList.add('is-final');

                const ruleHeading = document.createElement('h4');
                ruleHeading.className = 'formula-transformation-rule';
                const ruleName = transformationApi.ruleLabel(step.rule);
                ruleHeading.textContent = 'Regola: ' + (ruleName || (
                    step.kind === 'mutation' ? 'modifica non equivalente' : 'riscrittura equivalente'
                ));
                const explanation = document.createElement('span');
                explanation.className = 'formula-transformation-explanation';
                explanation.textContent = transformationApi.describeStep(step);
                item.appendChild(ruleHeading);
                item.appendChild(explanation);
                appendFormula(
                    item,
                    'Schema generale',
                    transformationApi.ruleSchema(step),
                    'formula-transformation-law-row',
                    false,
                    'formula-transformation-law'
                );
                appendFormula(
                    item,
                    'Applicazione della regola',
                    formattedRelation(step),
                    'formula-transformation-application-row',
                    false,
                    'formula-transformation-application'
                );
                appendFormula(
                    item,
                    'Formula completa ottenuta',
                    step.after_prolog,
                    'formula-transformation-result'
                );
                if (step.kind === 'mutation') {
                    const warning = document.createElement('p');
                    warning.className = 'formula-transformation-non-equivalence';
                    warning.textContent = 'Attenzione: questo passaggio non conserva l\'equivalenza logica.';
                    item.appendChild(warning);
                }
                list.appendChild(item);
            });
            section.appendChild(list);

            const outcome = trace.preserves_meaning
                ? 'Ogni passaggio conserva il significato della formula iniziale.'
                : 'Il percorso mostra dove la risposta selezionata smette di essere equivalente alla formula iniziale.';
            const note = document.createElement('p');
            note.className = 'formula-transformation-outcome';
            note.textContent = outcome;
            section.appendChild(note);
            parent.appendChild(section);
            return true;
        }

        function show(configuration) {
            hide();
            if (!container || !transformationApi) return;
            const config = configuration || {};
            const traces = [];
            const correct = transformationApi.normalize(config.correct);
            const selected = transformationApi.normalize(config.selected);
            if (correct) traces.push({ title: 'Costruzione della risposta corretta', trace: correct });
            if (!config.selectedIsCorrect && selected) {
                traces.push({ title: 'Costruzione della risposta selezionata', trace: selected });
            }
            if (traces.length === 0) return;

            panelSequence += 1;
            const panelId = 'formulaTransformationPanel-' + panelSequence;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'formula-transformation-toggle';
            button.textContent = 'Come è stata raggiunta la formula?';
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('aria-controls', panelId);

            const panel = document.createElement('div');
            panel.id = panelId;
            panel.className = 'formula-transformation-panel';
            panel.hidden = true;
            traces.forEach(function(entry) {
                appendTrace(panel, entry.title, entry.trace);
            });

            button.addEventListener('click', function() {
                const willOpen = panel.hidden;
                panel.hidden = !willOpen;
                button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
            });

            container.appendChild(button);
            container.appendChild(panel);
            container.hidden = false;
        }

        hide();
        return Object.freeze({ hide: hide, show: show });
    }

    global.LogicFormulaTransformationRenderer = Object.freeze({ create: create });
})(window);
