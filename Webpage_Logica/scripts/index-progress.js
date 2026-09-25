(function initializeIndexProgress(global) {
    'use strict';
    function start() {
        const target = document.getElementById('indexLessonProgress');
        if (!target || !global.LogicAppStorage) return;
        let loadGeneration = 0;

        function render(items) {
            const completed = items.filter(function(item) { return item.manuallyCompleted; }).length;
            const bookmarks = items.flatMap(function(item) { return item.bookmarks || []; });
            target.textContent = 'Lezioni completate: ' + completed + ' su 6.';
            if (bookmarks.length) {
                const link = document.createElement('a');
                link.href = bookmarks[bookmarks.length - 1].url;
                link.textContent = ' Riprendi dall’ultimo segnalibro: ' + bookmarks[bookmarks.length - 1].title;
                target.appendChild(link);
            }
        }

        function clearProgress() {
            loadGeneration += 1;
            render([]);
        }

        function reloadProgress() {
            const generation = ++loadGeneration;
            return global.LogicAppStorage.instance.list('lessonProgress').then(function(items) {
                if (generation !== loadGeneration) return;
                render(items);
            }).catch(function() {
                if (generation !== loadGeneration) return;
                target.textContent = 'Progresso locale non disponibile.';
            });
        }

        if (global.LogicAppEvents) {
            ['privacy:data-clearing', 'privacy:progress-clearing'].forEach(function(name) {
                global.LogicAppEvents.on(name, clearProgress);
            });
            ['privacy:data-cleared', 'privacy:progress-cleared'].forEach(function(name) {
                global.LogicAppEvents.on(name, reloadProgress);
            });
        }
        reloadProgress();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})(window);
