/*
 * Modello del questionario di feedback finale.
 */
(function exposeQuizFeedback(global) {
    'use strict';

    const FIELDS = Object.freeze([
        Object.freeze({
            id: 'expectation',
            payloadKey: 'Aspettative test',
            label: 'Nel complesso, questa esercitazione ha soddisfatto le mie aspettative.'
        }),
        Object.freeze({
            id: 'aidsUtility',
            payloadKey: 'Utilità ausili',
            label: 'Gli ausili disponibili mi hanno aiutato a svolgere l\'esercitazione.'
        }),
        Object.freeze({
            id: 'lessonsUtility',
            payloadKey: 'Utilità lezioni',
            label: 'Le lezioni introduttive mi hanno aiutato ad affrontare l\'esercitazione.'
        }),
        Object.freeze({
            id: 'testDifficulty',
            payloadKey: 'Difficoltà test',
            label: 'Ho trovato difficili le domande dell\'esercitazione.',
            hint: 'Per questa affermazione, un valore alto indica una difficoltà maggiore.'
        }),
        Object.freeze({
            id: 'control',
            payloadKey: 'Controllo',
            label: 'Gli ausili non sono stati utili durante l\'esercitazione.',
            hint: 'Domanda di controllo formulata in senso negativo: leggi con attenzione prima di rispondere.'
        })
    ]);

    function isComplete(values) {
        return FIELDS.every(function(field) {
            return /^[1-5]$/.test(String(values[field.id] || ''));
        });
    }

    function isOptionalAgeValid(value, validity) {
        const state = validity && typeof validity === 'object' ? validity : {};
        if (state.badInput || state.rangeOverflow || state.rangeUnderflow || state.stepMismatch) return false;
        const raw = String(value || '').trim();
        if (raw === '') return true;
        return /^\d+$/.test(raw) && Number(raw) >= 1 && Number(raw) <= 199;
    }

    function createIdempotencyKey() {
        const cryptoApi = global.crypto;
        if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
            return cryptoApi.randomUUID();
        }

        const bytes = new Uint8Array(16);
        if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
            cryptoApi.getRandomValues(bytes);
        } else {
            for (let index = 0; index < bytes.length; index += 1) {
                bytes[index] = Math.floor(Math.random() * 256);
            }
        }
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, function(value) {
            return value.toString(16).padStart(2, '0');
        });
        return hex.slice(0, 4).join('') + '-'
            + hex.slice(4, 6).join('') + '-'
            + hex.slice(6, 8).join('') + '-'
            + hex.slice(8, 10).join('') + '-'
            + hex.slice(10).join('');
    }

    function createSubmission(options) {
        const settings = options || {};
        const postJson = settings.postJson;
        const makeKey = settings.createKey || createIdempotencyKey;
        if (typeof postJson !== 'function') throw new TypeError('postJson richiesto');

        let inFlight = false;
        let sent = false;
        let idempotencyKey = '';
        let pendingReport = null;
        let generation = 0;

        function reset() {
            generation += 1;
            inFlight = false;
            sent = false;
            idempotencyKey = '';
            pendingReport = null;
        }

        function invalidate() {
            if (inFlight || sent) return false;
            generation += 1;
            idempotencyKey = '';
            pendingReport = null;
            return true;
        }

        function submit(report) {
            if (inFlight || sent) return Promise.resolve(sent);
            if (!pendingReport) {
                pendingReport = report;
                idempotencyKey = String(makeKey());
            }
            const currentGeneration = generation;
            inFlight = true;
            return postJson('/api/revisione', pendingReport, {
                headers: { 'Idempotency-Key': idempotencyKey }
            }).then(function() {
                if (generation === currentGeneration) sent = true;
                return true;
            }).catch(function() {
                return false;
            }).finally(function() {
                if (generation === currentGeneration) inFlight = false;
            });
        }

        return Object.freeze({
            get idempotencyKey() { return idempotencyKey; },
            get inFlight() { return inFlight; },
            get sent() { return sent; },
            invalidate: invalidate,
            reset: reset,
            submit: submit
        });
    }

    global.LogicQuizFeedback = Object.freeze({
        FIELDS: FIELDS,
        createIdempotencyKey: createIdempotencyKey,
        createSubmission: createSubmission,
        isComplete: isComplete,
        isOptionalAgeValid: isOptionalAgeValid
    });
})(window);
