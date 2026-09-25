/* Contratti versionati condivisi da quiz, progressi, errori ed esportazione. */
(function exposeDataContracts(global) {
    'use strict';

    const SCHEMA_VERSION = 1;
    const MAX_QUIZ_QUESTIONS = 100;
    const QUESTION_TYPES = Object.freeze([
        'equivalence',
        'truth-value',
        'logical-consequence',
        'translation',
        'quantifier-negation'
    ]);
    const DIFFICULTIES = Object.freeze(['easy', 'medium', 'hard']);
    const MODES = Object.freeze(['practice', 'exam']);

    function clampInteger(value, minimum, maximum, fallback) {
        const number = Number(value);
        if (!Number.isFinite(number)) return fallback;
        return Math.min(maximum, Math.max(minimum, Math.round(number)));
    }

    function createId(prefix) {
        if (global.crypto && typeof global.crypto.randomUUID === 'function') {
            return String(prefix || 'id') + '-' + global.crypto.randomUUID();
        }
        return String(prefix || 'id') + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    function normalizeQuizConfig(raw) {
        const source = raw && typeof raw === 'object' ? raw : {};
        const requestedTypes = Array.isArray(source.questionTypes) ? source.questionTypes : QUESTION_TYPES;
        const questionTypes = Array.from(new Set(requestedTypes.filter(function(type) {
            return QUESTION_TYPES.includes(type);
        })));
        const typeCounts = {};
        if (source.typeCounts && typeof source.typeCounts === 'object') {
            QUESTION_TYPES.forEach(function(type) {
                typeCounts[type] = clampInteger(source.typeCounts[type], 0, MAX_QUIZ_QUESTIONS, 0);
            });
        }
        const configuredTotal = Object.values(typeCounts).reduce(function(total, count) { return total + count; }, 0);
        return {
            version: SCHEMA_VERSION,
            preset: ['practice', 'exam', 'custom'].includes(source.preset) ? source.preset : 'practice',
            mode: MODES.includes(source.mode) ? source.mode : 'practice',
            questionCount: clampInteger(configuredTotal || source.questionCount, 1, MAX_QUIZ_QUESTIONS, 10),
            timeMinutes: clampInteger(source.timeMinutes, 1, 240, 20),
            difficulty: DIFFICULTIES.includes(source.difficulty) ? source.difficulty : 'medium',
            questionTypes: questionTypes.length ? questionTypes : ['equivalence'],
            typeCounts: typeCounts,
            adaptive: source.mode !== 'exam' && Boolean(source.adaptive),
            showConstruction: source.mode !== 'exam' && source.showConstruction !== false,
            spokenLanguage: Boolean(source.spokenLanguage),
            showImages: Boolean(source.showImages)
        };
    }

    function createSession(raw) {
        const source = raw && typeof raw === 'object' ? raw : {};
        const now = Number(source.updatedAt) || Date.now();
        return {
            version: SCHEMA_VERSION,
            sessionId: String(source.sessionId || createId('session')),
            status: ['active', 'completed', 'abandoned'].includes(source.status) ? source.status : 'active',
            createdAt: Number(source.createdAt) || now,
            updatedAt: now,
            expiresAt: Number(source.expiresAt) || now + (30 * 24 * 60 * 60 * 1000),
            config: normalizeQuizConfig(source.config),
            currentIndex: clampInteger(source.currentIndex, 0, 1000, 0),
            phase: source.phase === 'next' ? 'next' : 'check',
            selectedIndex: source.selectedIndex == null ? null : clampInteger(source.selectedIndex, 0, 1000, 0),
            remainingSeconds: Math.max(0, Number(source.remainingSeconds) || 0),
            operationPlan: Array.isArray(source.operationPlan) ? source.operationPlan : [],
            questions: Array.isArray(source.questions) ? source.questions : [],
            answers: Array.isArray(source.answers) ? source.answers : []
        };
    }

    function createAttempt(raw) {
        const source = raw && typeof raw === 'object' ? raw : {};
        return {
            version: SCHEMA_VERSION,
            attemptId: String(source.attemptId || createId('attempt')),
            sessionId: String(source.sessionId || ''),
            questionId: String(source.questionId || ''),
            type: String(source.type || 'unknown'),
            difficulty: DIFFICULTIES.includes(source.difficulty) ? source.difficulty : 'medium',
            answeredAt: Number(source.answeredAt) || Date.now(),
            elapsedMs: Math.max(0, Number(source.elapsedMs) || 0),
            correct: Boolean(source.correct),
            hintsUsed: Math.max(0, Number(source.hintsUsed) || 0),
            question: String(source.question || ''),
            selectedAnswer: String(source.selectedAnswer || ''),
            correctAnswer: String(source.correctAnswer || '')
        };
    }

    function errorKey(attempt) {
        const item = attempt || {};
        return [item.type || 'unknown', item.questionId || item.question || '', item.correctAnswer || ''].join('|');
    }

    global.LogicDataContracts = Object.freeze({
        DIFFICULTIES: DIFFICULTIES,
        MAX_QUIZ_QUESTIONS: MAX_QUIZ_QUESTIONS,
        MODES: MODES,
        QUESTION_TYPES: QUESTION_TYPES,
        SCHEMA_VERSION: SCHEMA_VERSION,
        clampInteger: clampInteger,
        createAttempt: createAttempt,
        createId: createId,
        createSession: createSession,
        errorKey: errorKey,
        normalizeQuizConfig: normalizeQuizConfig
    });
})(window);
