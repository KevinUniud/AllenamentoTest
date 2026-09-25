(function initializeDashboard(global) {
    'use strict';
    const TYPE_LABELS = Object.freeze({
        equivalence: 'Equivalenze',
        'truth-value': 'Valore di verità',
        'logical-consequence': 'Conseguenza logica',
        translation: 'Traduzione',
        'quantifier-negation': 'Quantificatori'
    });
    const DIFFICULTY_LABELS = Object.freeze({
        easy: 'Facile',
        medium: 'Media',
        hard: 'Difficile'
    });

    function displayLabel(labels, value) {
        const key = String(value || '');
        return labels[key] || key.replace(/[-_]+/g, ' ');
    }

    function start() {
        const storage = global.LogicAppStorage.instance;
        const period = document.getElementById('dashboardPeriod');
        const type = document.getElementById('dashboardType');
        const difficulty = document.getElementById('dashboardDifficulty');
        const summary = document.getElementById('dashboardSummary');
        const chart = document.getElementById('dashboardChart');
        const tableBody = document.getElementById('dashboardTableBody');
        const difficultyChart = document.getElementById('dashboardDifficultyChart');
        const difficultyTableBody = document.getElementById('dashboardDifficultyTableBody');
        const empty = document.getElementById('dashboardEmpty');
        const resultSections = [
            document.getElementById('dashboardSummarySection'),
            document.getElementById('dashboardDifficultySection'),
            document.getElementById('dashboardTypeSection')
        ];
        const exportJson = document.getElementById('dashboardExportJson');
        const exportCsv = document.getElementById('dashboardExportCsv');
        const downloadChart = document.getElementById('dashboardDownloadChart');
        let allAttempts = [];
        let loadGeneration = 0;

        function filtered() {
            const days = Number(period.value || 0);
            const threshold = days ? Date.now() - days * 86400000 : 0;
            return allAttempts.filter(function(item) {
                return (!threshold || Number(item.answeredAt) >= threshold)
                    && (!type.value || item.type === type.value)
                    && (!difficulty.value || item.difficulty === difficulty.value);
            });
        }

        function render() {
            const attempts = filtered();
            const metrics = global.LogicLearningMetrics.aggregate(attempts);
            const hasResults = metrics.total > 0;
            empty.hidden = hasResults;
            empty.textContent = allAttempts.length
                ? 'Nessun tentativo corrisponde ai filtri selezionati. Prova a modificare periodo, argomento o difficoltà.'
                : 'Non ci sono ancora tentativi salvati. Abilita il salvataggio locale nelle impostazioni e completa un quiz.';
            resultSections.forEach(function(section) { section.hidden = !hasResults; });
            [exportJson, exportCsv, downloadChart].forEach(function(button) { button.disabled = !hasResults; });
            summary.innerHTML = '';
            [
                ['Tentativi', metrics.total],
                ['Corrette', metrics.correct],
                ['Precisione', Math.round(metrics.accuracy * 100) + '%'],
                ['Tempo mediano', (metrics.medianElapsedMs / 1000).toFixed(1) + ' s']
            ].forEach(function(item) {
                const card = document.createElement('div');
                card.className = 'metric-card';
                const value = document.createElement('span');
                value.className = 'metric-value';
                value.textContent = String(item[1]);
                const label = document.createElement('span');
                label.textContent = item[0];
                card.appendChild(value);
                card.appendChild(label);
                summary.appendChild(card);
            });
            global.LogicCharts.renderBars(chart, metrics.byType.map(function(group) {
                return {
                    label: displayLabel(TYPE_LABELS, group.type),
                    value: group.accuracy * 100,
                    displayValue: Math.round(group.accuracy * 100) + '%'
                };
            }), { label: 'Precisione per tipologia di domanda', maximum: 100 });
            tableBody.innerHTML = '';
            metrics.byType.forEach(function(group) {
                const row = document.createElement('tr');
                [displayLabel(TYPE_LABELS, group.type), group.total, group.correct, Math.round(group.accuracy * 100) + '%', (group.medianElapsedMs / 1000).toFixed(1) + ' s']
                    .forEach(function(value) {
                        const cell = document.createElement('td');
                        cell.textContent = String(value);
                        row.appendChild(cell);
                    });
                tableBody.appendChild(row);
            });
            global.LogicCharts.renderBars(difficultyChart, metrics.byDifficulty.map(function(group) {
                return {
                    label: displayLabel(DIFFICULTY_LABELS, group.difficulty),
                    value: group.accuracy * 100,
                    displayValue: Math.round(group.accuracy * 100) + '%'
                };
            }), { label: 'Precisione per difficoltà', maximum: 100 });
            difficultyTableBody.innerHTML = '';
            metrics.byDifficulty.forEach(function(group) {
                const row = document.createElement('tr');
                [displayLabel(DIFFICULTY_LABELS, group.difficulty), group.total, group.correct, Math.round(group.accuracy * 100) + '%']
                    .forEach(function(value) {
                        const cell = document.createElement('td'); cell.textContent = String(value); row.appendChild(cell);
                    });
                difficultyTableBody.appendChild(row);
            });
        }

        function clearAttempts() {
            loadGeneration += 1;
            allAttempts = [];
            render();
        }

        function reloadAttempts() {
            const generation = ++loadGeneration;
            return storage.list('attempts').then(function(attempts) {
                if (generation !== loadGeneration) return;
                allAttempts = attempts;
                render();
            }).catch(function() {
                if (generation !== loadGeneration) return;
                allAttempts = [];
                render();
            });
        }

        period.addEventListener('change', render);
        type.addEventListener('change', render);
        difficulty.addEventListener('change', render);
        exportJson.addEventListener('click', function() {
            global.LogicResultsExport.downloadJson({ attempts: filtered() });
        });
        exportCsv.addEventListener('click', function() {
            global.LogicResultsExport.downloadCsv(filtered());
        });
        document.getElementById('dashboardPrint').addEventListener('click', function() { global.print(); });
        downloadChart.addEventListener('click', function() {
            global.LogicCharts.downloadSvg(chart.querySelector('svg'), 'testlogica-risultati-per-tipologia.svg');
        });
        if (global.LogicAppEvents) {
            ['privacy:data-clearing', 'privacy:progress-clearing'].forEach(function(name) {
                global.LogicAppEvents.on(name, clearAttempts);
            });
            ['privacy:data-cleared', 'privacy:progress-cleared'].forEach(function(name) {
                global.LogicAppEvents.on(name, reloadAttempts);
            });
        }
        reloadAttempts();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})(window);
