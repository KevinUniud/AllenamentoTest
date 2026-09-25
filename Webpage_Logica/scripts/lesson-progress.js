/* Progresso local-first delle lezioni e segnalibri per sezione. */
(function exposeLessonProgress(global) {
    'use strict';

    function initialize() {
        const lessonId = document.body && document.body.dataset.lessonId;
        if (!lessonId || !global.LogicAppStorage) return;
        const storage = global.LogicAppStorage.instance;
        const events = global.LogicAppEvents;
        let stateVersion = 0;
        let clearingInProgress = false;

        function emptyProgress() {
            return {
                version: 1,
                lessonId: lessonId,
                visited: true,
                visitedAt: Date.now(),
                completedExercises: [],
                manuallyCompleted: false,
                bookmarks: []
            };
        }

        let progress = emptyProgress();

        function save(patch) {
            if (clearingInProgress) return Promise.resolve(false);
            progress = { ...progress, ...(patch || {}), updatedAt: Date.now() };
            const operationVersion = stateVersion;
            const savedProgress = progress;
            return storage.put('lessonProgress', lessonId, savedProgress).then(function(saved) {
                const isCurrent = operationVersion === stateVersion && !clearingInProgress && progress === savedProgress;
                if (saved && isCurrent && events) events.emit('lesson:progress', savedProgress);
                return isCurrent;
            });
        }

        function sectionId(heading, index) {
            if (heading.id) return heading.id;
            const generated = lessonId + '-section-' + String(index + 1);
            heading.id = generated;
            heading.dataset.sectionId = generated;
            return generated;
        }

        function renderControls() {
            document.querySelectorAll('section[id]').forEach(function(section) {
                if (!section.dataset.sectionId) section.dataset.sectionId = section.id;
            });
            document.querySelectorAll('main h2, main h3, section h2, section h3').forEach(function(heading, index) {
                if (heading.querySelector('.lesson-bookmark-button')) return;
                const id = sectionId(heading, index);
                const title = String(heading.textContent || '').replace(/\s+/g, ' ').trim();
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'lesson-bookmark-button';
                button.dataset.sectionId = id;
                button.textContent = progress.bookmarks.some(function(item) { return item.sectionId === id; })
                    ? 'Rimuovi segnalibro'
                    : 'Salva segnalibro';
                button.addEventListener('click', function() {
                    const bookmarks = progress.bookmarks.slice();
                    const existing = bookmarks.findIndex(function(item) { return item.sectionId === id; });
                    if (existing >= 0) bookmarks.splice(existing, 1);
                    else bookmarks.push({ sectionId: id, title: title, url: location.pathname + '#' + id });
                    save({ bookmarks: bookmarks }).then(function() { renderBookmarkLabel(button, id); });
                });
                heading.appendChild(button);
            });

            if (!document.getElementById('lessonCompletionControls')) {
                const controls = document.createElement('div');
                controls.id = 'lessonCompletionControls';
                controls.className = 'rounded-box lesson-completion-controls';
                const status = document.createElement('p');
                status.id = 'lessonProgressStatus';
                const complete = document.createElement('button');
                complete.type = 'button';
                complete.id = 'lessonCompletionButton';
                complete.textContent = progress.manuallyCompleted ? 'Lezione completata' : 'Segna lezione come completata';
                complete.disabled = progress.manuallyCompleted;
                complete.addEventListener('click', function() {
                    save({ manuallyCompleted: true, completedAt: Date.now() }).then(function(saved) {
                        if (!saved) return;
                        complete.textContent = 'Lezione completata';
                        complete.disabled = true;
                        updateStatus(status);
                        if (events) events.emit('lesson:completed', progress);
                    });
                });
                controls.appendChild(status);
                controls.appendChild(complete);
                const nav = document.querySelector('.lesson-nav');
                if (nav) nav.insertAdjacentElement('beforebegin', controls);
                else document.body.appendChild(controls);
                updateStatus(status);
            }
            renderCurrentProgress();
            if (clearingInProgress) return;
            const renderVersion = stateVersion;
            storage.list('lessonProgress').then(function(items) {
                if (clearingInProgress || renderVersion !== stateVersion) return;
                clearSwitcherProgress();
                const byLesson = new Map(items.map(function(item) { return [item.lessonId, item]; }));
                document.querySelectorAll('.lesson-switcher-link').forEach(function(link) {
                    const match = link.getAttribute('href')?.match(/(?:^|\/)lezione-(\d+)(?:\.html|\/)?(?=$|[?#])/);
                    if (!match) return;
                    const item = byLesson.get('lesson-' + match[1]);
                    if (item?.manuallyCompleted && !link.textContent.includes('✓')) link.textContent += ' ✓';
                });
                const current = byLesson.get(lessonId);
                const lastBookmark = current && current.bookmarks && current.bookmarks[current.bookmarks.length - 1];
                const switcher = document.querySelector('.lesson-switcher-list');
                if (lastBookmark && switcher && !switcher.querySelector('.lesson-resume-bookmark')) {
                    const resume = document.createElement('a');
                    resume.className = 'lesson-switcher-link lesson-resume-bookmark';
                    resume.href = lastBookmark.url;
                    resume.textContent = 'Riprendi: ' + lastBookmark.title;
                    switcher.appendChild(resume);
                }
            }).catch(function() {});
        }

        function clearSwitcherProgress() {
            document.querySelectorAll('.lesson-switcher-link').forEach(function(link) {
                link.textContent = String(link.textContent || '').replace(/\s*✓\s*$/, '');
            });
            document.querySelectorAll('.lesson-resume-bookmark').forEach(function(link) { link.remove(); });
        }

        function renderCurrentProgress() {
            document.querySelectorAll('.lesson-bookmark-button').forEach(function(button) {
                renderBookmarkLabel(button, button.dataset.sectionId);
            });
            const complete = document.getElementById('lessonCompletionButton');
            if (complete) {
                complete.textContent = progress.manuallyCompleted ? 'Lezione completata' : 'Segna lezione come completata';
                complete.disabled = progress.manuallyCompleted;
            }
            updateStatus(document.getElementById('lessonProgressStatus'));
            clearSwitcherProgress();
        }

        function resetProgress(render) {
            stateVersion += 1;
            progress = emptyProgress();
            renderCurrentProgress();
            if (render) renderControls();
        }

        function beginClearing() {
            clearingInProgress = true;
            resetProgress(false);
        }

        function finishClearing() {
            clearingInProgress = false;
            resetProgress(true);
        }

        function renderBookmarkLabel(button, id) {
            button.textContent = progress.bookmarks.some(function(item) { return item.sectionId === id; })
                ? 'Rimuovi segnalibro'
                : 'Salva segnalibro';
        }

        function updateStatus(status) {
            if (!status) return;
            status.textContent = 'Esercizi superati: ' + String(progress.completedExercises.length)
                + (progress.manuallyCompleted ? '. Lezione completata.' : '. Completamento manuale non ancora segnato.');
        }

        if (events && typeof events.on === 'function') {
            ['privacy:data-clearing', 'privacy:progress-clearing'].forEach(function(name) {
                events.on(name, beginClearing);
            });
            ['privacy:data-cleared', 'privacy:progress-cleared'].forEach(function(name) {
                events.on(name, finishClearing);
            });
        }

        const loadVersion = stateVersion;
        storage.get('lessonProgress', lessonId).then(function(saved) {
            if (clearingInProgress || loadVersion !== stateVersion) return;
            if (saved) progress = { ...progress, ...saved, visited: true, visitedAt: saved.visitedAt || Date.now() };
            save();
            renderControls();
        }).catch(function() {
            if (!clearingInProgress && loadVersion === stateVersion) renderControls();
        });

        if (events) {
            events.on('lesson:answered', function(detail) {
                if (!detail || !detail.correct) return;
                const exerciseId = String(detail.exerciseId || 'exercise-' + Date.now());
                if (progress.completedExercises.includes(exerciseId)) return;
                const completed = progress.completedExercises.concat(exerciseId);
                save({ completedExercises: completed }).then(function() {
                    updateStatus(document.getElementById('lessonProgressStatus'));
                });
            });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();

    global.LogicLessonProgress = Object.freeze({ initialize: initialize });
})(window);
