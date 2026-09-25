/* Adattivita trasparente, deterministica e limitata a un livello per volta. */
(function exposeAdaptiveEngine(global) {
    'use strict';

    const LEVELS = ['easy', 'medium', 'hard'];

    function recommend(attempts, currentDifficulty) {
        const current = LEVELS.includes(currentDifficulty) ? currentDifficulty : 'medium';
        const recent = (Array.isArray(attempts) ? attempts : []).slice(-8);
        if (recent.length < 4) {
            return { difficulty: current, changed: false, reason: 'Servono almeno quattro risposte per adattare la difficolta.' };
        }
        const metrics = global.LogicLearningMetrics.aggregate(recent);
        const averageHints = recent.reduce(function(total, attempt) {
            return total + (Number(attempt.hintsUsed) || 0);
        }, 0) / recent.length;
        const index = LEVELS.indexOf(current);
        if (metrics.accuracy >= 0.8 && metrics.medianElapsedMs <= 120000 && averageHints <= 0.5 && index < LEVELS.length - 1) {
            return {
                difficulty: LEVELS[index + 1],
                changed: true,
                reason: 'La precisione recente e almeno dell’80%, il tempo mediano e sotto due minuti e quasi non usi aiuti.'
            };
        }
        if ((metrics.accuracy <= 0.45 || averageHints >= 2) && index > 0) {
            return {
                difficulty: LEVELS[index - 1],
                changed: true,
                reason: metrics.accuracy <= 0.45
                    ? 'La precisione recente e inferiore al 46%.'
                    : 'Nelle risposte recenti hai usato in media almeno due aiuti.'
            };
        }
        return { difficulty: current, changed: false, reason: 'La difficolta attuale e coerente con i risultati recenti.' };
    }

    global.LogicAdaptiveEngine = Object.freeze({ LEVELS: LEVELS, recommend: recommend });
})(window);
