(function initializeErrorNotebookPage(global) {
    'use strict';
    function start() {
        const notebook = global.LogicErrorNotebook.create({ storage: global.LogicAppStorage.instance });
        const list = document.getElementById('errorNotebookList');
        const empty = document.getElementById('errorNotebookEmpty');
        const typeFilter = document.getElementById('errorTypeFilter');
        const stateFilter = document.getElementById('errorStateFilter');
        const orderFilter = document.getElementById('errorOrderFilter');
        const periodFilter = document.getElementById('errorPeriodFilter');
        let errors = [];
        let loadGeneration = 0;

        function filtered() {
            const days = Number(periodFilter.value || 0);
            const threshold = days ? Date.now() - days * 86400000 : 0;
            const values = errors.filter(function(item) {
                return (!typeFilter.value || item.type === typeFilter.value)
                    && (!stateFilter.value || item.reviewState === stateFilter.value)
                    && (!threshold || Number(item.lastSeenAt) >= threshold);
            });
            values.sort(function(left, right) {
                return orderFilter.value === 'count'
                    ? Number(right.count) - Number(left.count)
                    : Number(right.lastSeenAt) - Number(left.lastSeenAt);
            });
            return values;
        }

        function render() {
            const values = filtered();
            list.innerHTML = '';
            empty.hidden = values.length > 0;
            values.forEach(function(item) {
                const card = document.createElement('article');
                card.className = 'study-card';
                const title = document.createElement('h2');
                title.textContent = item.type + ' · ' + String(item.count) + (Number(item.count) === 1 ? ' errore' : ' errori');
                const question = document.createElement('p');
                question.textContent = item.question;
                const answers = document.createElement('p');
                answers.textContent = 'Hai risposto: ' + item.selectedAnswer + '. Soluzione: ' + item.correctAnswer + '.';
                const date = document.createElement('p');
                date.textContent = 'Ultima occorrenza: ' + new Date(item.lastSeenAt).toLocaleString('it-IT');
                const stateLabel = document.createElement('label');
                stateLabel.textContent = 'Stato di ripasso ';
                const state = document.createElement('select');
                [['review', 'Da rivedere'], ['learning', 'In apprendimento'], ['mastered', 'Consolidato']].forEach(function(optionData) {
                    const option = document.createElement('option');
                    option.value = optionData[0];
                    option.textContent = optionData[1];
                    option.selected = item.reviewState === optionData[0];
                    state.appendChild(option);
                });
                state.addEventListener('change', function() {
                    notebook.setReviewState(item.errorId, state.value).then(reload);
                });
                stateLabel.appendChild(state);
                const retry = document.createElement('a');
                retry.className = 'lesson-nav-btn';
                retry.href = '../esercizi/esercitazione.html?type=' + encodeURIComponent(item.type) + '&difficulty=' + encodeURIComponent(item.difficulty);
                retry.textContent = 'Genera una variante';
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.textContent = 'Elimina';
                remove.addEventListener('click', function() { notebook.remove(item.errorId).then(reload); });
                card.appendChild(title);
                card.appendChild(question);
                card.appendChild(answers);
                card.appendChild(date);
                card.appendChild(stateLabel);
                const correctTransformation = item.transformationCorrect || item.transformation || null;
                const selectedTransformation = item.transformationSelected || null;
                if (correctTransformation || selectedTransformation) {
                    const trace = document.createElement('div');
                    trace.className = 'formula-transformation';
                    card.appendChild(trace);
                    global.LogicFormulaTransformationRenderer.create({ container: trace }).show({
                        correct: correctTransformation,
                        selected: selectedTransformation,
                        selectedIsCorrect: false
                    });
                }
                const actions = document.createElement('div');
                actions.className = 'quiz-inline-actions';
                actions.appendChild(retry);
                actions.appendChild(remove);
                card.appendChild(actions);
                list.appendChild(card);
            });
        }

        function clearErrors() {
            loadGeneration += 1;
            errors = [];
            render();
        }

        function reload() {
            const generation = ++loadGeneration;
            return notebook.list().then(function(items) {
                if (generation !== loadGeneration) return;
                errors = items;
                render();
            }).catch(function() {
                if (generation !== loadGeneration) return;
                errors = [];
                render();
            });
        }

        typeFilter.addEventListener('change', render);
        stateFilter.addEventListener('change', render);
        orderFilter.addEventListener('change', render);
        periodFilter.addEventListener('change', render);
        document.getElementById('clearErrorNotebook').addEventListener('click', function() {
            global.LogicAppStorage.instance.clearType('errors').then(reload);
        });
        if (global.LogicAppEvents) {
            ['privacy:data-clearing', 'privacy:progress-clearing'].forEach(function(name) {
                global.LogicAppEvents.on(name, clearErrors);
            });
            ['privacy:data-cleared', 'privacy:progress-cleared'].forEach(function(name) {
                global.LogicAppEvents.on(name, reload);
            });
        }
        reload();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})(window);
