/*
 * Rendering DOM basilare del quiz: informazioni, opzioni, selezione e stato.
 */
(function exposeQuizRenderer(global) {
    'use strict';

    function create(options) {
        const state = options.state;
        const infoEl = options.infoEl;
        const optionsEl = options.optionsEl;
        const statusEl = options.statusEl;

        function showInfo(items) {
            if (!Array.isArray(items) || items.length === 0) {
                infoEl.hidden = true;
                infoEl.innerHTML = '';
                return;
            }
            const htmlItems = items.map(function(item) {
                if (state.spokenlanguage) {
                    return '<li>' + options.escapeHtml(options.formatSpokenInfoLine(item)) + '</li>';
                }
                if (state.exerciseKind === 'translation') {
                    return '<li>' + options.colorizeAtomsInText(String(item)) + '</li>';
                }
                return '<li>' + options.colorizeAtomsInText(options.transformFormula(item)) + '</li>';
            }).join('');
            infoEl.innerHTML = '<p>Sappiamo che:</p><ul>' + htmlItems + '</ul>';
            infoEl.hidden = false;
        }

        function updateSelectionVisual(configuration) {
            const config = configuration || {};
            const optionNodes = Array.from(optionsEl.querySelectorAll('.quiz-option'));
            const requestedFocusIndex = Number.isInteger(config.focusIndex) ? config.focusIndex : null;
            const selectedIndex = Number.isInteger(state.selectedIndex) ? state.selectedIndex : null;
            const tabStopIndex = selectedIndex != null
                ? selectedIndex
                : (requestedFocusIndex != null ? requestedFocusIndex : (optionNodes.length > 0 ? 0 : null));

            optionNodes.forEach(function(item, index) {
                item.classList.toggle('is-selected', index === state.selectedIndex);
                item.setAttribute('aria-checked', index === state.selectedIndex ? 'true' : 'false');
                item.tabIndex = index === tabStopIndex ? 0 : -1;
            });

            if (config.focus === true && requestedFocusIndex != null && optionNodes[requestedFocusIndex]) {
                optionNodes[requestedFocusIndex].focus();
            }
        }

        function renderOptions() {
            optionsEl.innerHTML = '';
            state.options.forEach(function(option, index) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'quiz-option';
                button.setAttribute('role', 'radio');
                button.setAttribute('aria-checked', index === state.selectedIndex ? 'true' : 'false');
                button.dataset.index = String(index);
                button.innerHTML = options.colorizeAtomsInText(
                    options.transformFormula(options.getOptionFormula(option))
                );
                optionsEl.appendChild(button);
            });
            updateSelectionVisual({ focusIndex: 0 });
        }

        function setStatus(message) {
            statusEl.textContent = message || '';
        }

        function resetVisualFeedback() {
            optionsEl.querySelectorAll('.quiz-option').forEach(function(item) {
                item.classList.remove('is-correct', 'is-correct-answer', 'is-wrong', 'is-final');
            });
        }

        return Object.freeze({
            showInfo: showInfo,
            renderOptions: renderOptions,
            updateSelectionVisual: updateSelectionVisual,
            setStatus: setStatus,
            resetVisualFeedback: resetVisualFeedback
        });
    }

    global.LogicQuizRenderer = Object.freeze({ create: create });
})(window);
