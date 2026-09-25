/* Aggregazioni pure condivise da dashboard e adattività. */
(function exposeLearningMetrics(global) {
    'use strict';

    function median(values) {
        const sorted = values.filter(Number.isFinite).slice().sort(function(a, b) { return a - b; });
        if (!sorted.length) return 0;
        const middle = Math.floor(sorted.length / 2);
        return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
    }

    function aggregate(attempts) {
        const list = Array.isArray(attempts) ? attempts : [];
        const byType = {};
        const byDifficulty = {};
        list.forEach(function(item) {
            const type = String(item.type || 'unknown');
            if (!byType[type]) byType[type] = { type: type, total: 0, correct: 0, elapsed: [] };
            byType[type].total += 1;
            if (item.correct) byType[type].correct += 1;
            byType[type].elapsed.push(Number(item.elapsedMs) || 0);
            const difficulty = String(item.difficulty || 'unknown');
            if (!byDifficulty[difficulty]) byDifficulty[difficulty] = { difficulty: difficulty, total: 0, correct: 0, elapsed: [] };
            byDifficulty[difficulty].total += 1;
            if (item.correct) byDifficulty[difficulty].correct += 1;
            byDifficulty[difficulty].elapsed.push(Number(item.elapsedMs) || 0);
        });
        const totalCorrect = list.filter(function(item) { return item.correct; }).length;
        return {
            total: list.length,
            correct: totalCorrect,
            accuracy: list.length ? totalCorrect / list.length : 0,
            medianElapsedMs: median(list.map(function(item) { return Number(item.elapsedMs) || 0; })),
            byType: Object.values(byType).map(function(group) {
                return {
                    type: group.type,
                    total: group.total,
                    correct: group.correct,
                    accuracy: group.total ? group.correct / group.total : 0,
                    medianElapsedMs: median(group.elapsed)
                };
            }),
            byDifficulty: Object.values(byDifficulty).map(function(group) {
                return {
                    difficulty: group.difficulty,
                    total: group.total,
                    correct: group.correct,
                    accuracy: group.total ? group.correct / group.total : 0,
                    medianElapsedMs: median(group.elapsed)
                };
            })
        };
    }

    global.LogicLearningMetrics = Object.freeze({ aggregate: aggregate, median: median });
})(window);
