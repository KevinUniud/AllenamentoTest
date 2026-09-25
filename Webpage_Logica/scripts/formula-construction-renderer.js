/*
 * Componente DOM accessibile per mostrare la costruzione dopo la correzione.
 */
(function exposeFormulaConstructionRenderer(global) {
    'use strict';

    let panelSequence = 0;

    function create(options) {
        const settings = options || {};
        const container = settings.container || null;
        const constructionApi = global.LogicFormulaConstruction;
        const formatFormula = typeof settings.formatFormula === 'function'
            ? settings.formatFormula
            : function(value) { return String(value || ''); };

        function hide() {
            if (!container) return;
            container.hidden = true;
            container.textContent = '';
        }

        function appendTrace(parent, title, rawTrace) {
            const trace = constructionApi && constructionApi.normalize(rawTrace);
            if (!trace) return false;

            const section = document.createElement('section');
            section.className = 'formula-construction-trace';
            const heading = document.createElement('h3');
            heading.className = 'formula-construction-title';
            heading.textContent = title;
            section.appendChild(heading);

            const list = document.createElement('ol');
            list.className = 'formula-construction-steps';
            trace.steps.forEach(function(step, index) {
                const item = document.createElement('li');
                item.className = 'formula-construction-step';
                if (index === trace.steps.length - 1) item.classList.add('is-final');

                const explanation = document.createElement('span');
                explanation.className = 'formula-construction-explanation';
                explanation.textContent = constructionApi.describeStep(step);

                const formula = document.createElement('code');
                formula.className = 'formula-construction-formula';
                formula.textContent = formatFormula(step.result_prolog);

                item.appendChild(explanation);
                item.appendChild(formula);
                list.appendChild(item);
            });
            section.appendChild(list);
            parent.appendChild(section);
            return true;
        }

        function show(configuration) {
            hide();
            if (!container || !constructionApi) return;
            const config = configuration || {};
            const traces = [];
            const correct = constructionApi.normalize(config.correct);
            const selected = constructionApi.normalize(config.selected);

            if (correct) traces.push({ title: 'Costruzione della risposta corretta', trace: correct });
            if (!config.selectedIsCorrect && selected) {
                traces.push({ title: 'Costruzione della risposta selezionata', trace: selected });
            }
            if (traces.length === 0) return;

            panelSequence += 1;
            const panelId = 'formulaConstructionPanel-' + panelSequence;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'formula-construction-toggle';
            button.textContent = 'Mostra la struttura sintattica della formula';
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('aria-controls', panelId);

            const panel = document.createElement('div');
            panel.id = panelId;
            panel.className = 'formula-construction-panel';
            panel.hidden = true;
            traces.forEach(function(entry) {
                appendTrace(panel, entry.title, entry.trace);
            });

            button.addEventListener('click', function() {
                const willOpen = panel.hidden;
                panel.hidden = !willOpen;
                button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
                if (willOpen) {
                    const firstHeading = panel.querySelector('h3');
                    if (firstHeading) firstHeading.setAttribute('tabindex', '-1');
                }
            });

            container.appendChild(button);
            container.appendChild(panel);
            container.hidden = false;
        }

        hide();
        return Object.freeze({ hide: hide, show: show });
    }

    global.LogicFormulaConstructionRenderer = Object.freeze({ create: create });
})(window);
