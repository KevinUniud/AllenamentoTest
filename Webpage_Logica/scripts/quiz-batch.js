/*
 * Trasporto e riallineamento delle risposte batch rispetto al piano locale.
 */
(function exposeQuizBatch(global) {
    'use strict';

    async function fetchQuestions(operations, dependencies) {
        const apiQuestions = [];
        const apiIndexToPlanIndex = [];
        operations.forEach(function(entry, planIndex) {
            if (!entry || entry.localOnly) return;
            apiQuestions.push({ operation: entry.operation, payload: entry.payload });
            apiIndexToPlanIndex.push(planIndex);
        });

        const alignedResults = new Array(operations.length).fill(null);
        if (apiQuestions.length === 0) return alignedResults;

        const requestedBatchSize = Math.floor(Number(dependencies.batchSize));
        const batchSize = Number.isFinite(requestedBatchSize) && requestedBatchSize > 0
            ? Math.min(requestedBatchSize, apiQuestions.length)
            : apiQuestions.length;
        const timeoutMs = Number(dependencies.timeoutMs) > 0 ? Number(dependencies.timeoutMs) : 120000;

        for (let offset = 0; offset < apiQuestions.length; offset += batchSize) {
            const chunk = apiQuestions.slice(offset, offset + batchSize);
            const payload = await dependencies.postJson(
                dependencies.buildApiUrl('generator/multiple-questions'),
                { questions: chunk },
                { timeoutMs: timeoutMs }
            );
            const payloadRoot = payload && typeof payload === 'object' && payload.result && typeof payload.result === 'object'
                ? payload.result
                : payload;
            const questions = Array.isArray(payloadRoot && payloadRoot.questions)
                ? payloadRoot.questions
                : (Array.isArray(payload && payload.results) ? payload.results : null);
            if (!questions) throw new Error('Batch response format invalid: missing questions array');

            questions.forEach(function(item, position) {
                if (!item || typeof item !== 'object') return;
                const rawIndex = Number(item.index);
                const chunkIndex = Number.isInteger(rawIndex) ? rawIndex : position;
                if (chunkIndex < 0 || chunkIndex >= chunk.length) return;
                const apiIndex = offset + chunkIndex;
                const planIndex = apiIndexToPlanIndex[apiIndex];
                const result = Object.prototype.hasOwnProperty.call(item, 'result') ? item.result : item;
                const isOk = Object.prototype.hasOwnProperty.call(item, 'status') ? item.status === 'ok' : Boolean(result);
                alignedResults[planIndex] = isOk ? result : null;
            });
        }
        return alignedResults;
    }

    global.LogicQuizBatch = Object.freeze({ fetchQuestions: fetchQuestions });
})(window);
