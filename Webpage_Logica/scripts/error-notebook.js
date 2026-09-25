/* Registrazione deduplicata degli errori e stato di ripasso. */
(function exposeErrorNotebook(global) {
    'use strict';

    function create(options) {
        const settings = options || {};
        const storage = settings.storage || global.LogicAppStorage.instance;
        const contracts = settings.contracts || global.LogicDataContracts;

        async function record(attempt, extra) {
            if (!attempt || attempt.correct) return null;
            const key = contracts.errorKey(attempt);
            const previous = await storage.get('errors', key);
            const metadata = extra || {};
            const next = {
                version: 1,
                errorId: key,
                questionId: attempt.questionId,
                type: attempt.type,
                difficulty: attempt.difficulty,
                question: attempt.question,
                selectedAnswer: attempt.selectedAnswer,
                correctAnswer: attempt.correctAnswer,
                construction: metadata.construction || (previous && previous.construction) || null,
                transformationCorrect: metadata.transformationCorrect || metadata.transformation ||
                    (previous && (previous.transformationCorrect || previous.transformation)) || null,
                transformationSelected: metadata.transformationSelected ||
                    (previous && previous.transformationSelected) || null,
                count: previous ? Number(previous.count || 0) + 1 : 1,
                firstSeenAt: previous ? previous.firstSeenAt : attempt.answeredAt,
                lastSeenAt: attempt.answeredAt,
                reviewState: previous ? previous.reviewState : 'review'
            };
            await storage.put('errors', key, next);
            return next;
        }

        async function setReviewState(errorId, state) {
            const current = await storage.get('errors', errorId);
            if (!current) return null;
            const next = { ...current, reviewState: ['review', 'learning', 'mastered'].includes(state) ? state : 'review' };
            await storage.put('errors', errorId, next);
            return next;
        }

        return Object.freeze({
            list: function() { return storage.list('errors'); },
            record: record,
            remove: function(id) { return storage.remove('errors', id); },
            setReviewState: setReviewState
        });
    }

    global.LogicErrorNotebook = Object.freeze({ create: create });
})(window);
