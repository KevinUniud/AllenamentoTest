(function exposeLogicApi(global) {
    'use strict';

    class ApiError extends Error {
        constructor(message, status, payload, code, requestId, cause) {
            super(message);
            this.name = 'ApiError';
            this.status = status || 0;
            this.payload = payload || null;
            this.code = code || (payload && payload.code) || 'API_ERROR';
            this.requestId = requestId || (payload && payload.request_id) || null;
            if (cause) this.cause = cause;
        }
    }

    function normalizeBase(rawBase) {
        const base = String(rawBase || '').trim();
        return (base || '/api').replace(/\/+$/, '');
    }

    function buildUrl(path, rawBase) {
        const value = String(path || '');
        if (/^https?:\/\//i.test(value) || value.startsWith('/api/')) return value;
        return normalizeBase(rawBase === undefined ? global.LOGIC_API_BASE_URL : rawBase)
            + '/' + value.replace(/^\/+/, '');
    }

    async function requestJson(url, options) {
        const settings = options || {};
        const timeoutMs = Number(settings.timeoutMs) > 0 ? Number(settings.timeoutMs) : 15000;
        const controller = new AbortController();
        const externalSignal = settings.signal;
        let timedOut = false;
        const abortFromCaller = function abortFromCaller() {
            controller.abort();
        };
        if (externalSignal) {
            if (externalSignal.aborted) controller.abort();
            else externalSignal.addEventListener('abort', abortFromCaller, { once: true });
        }
        const timeoutId = global.setTimeout(function abortRequest() {
            timedOut = true;
            controller.abort();
        }, timeoutMs);

        try {
            const response = await global.fetch(url, {
                method: settings.method || 'GET',
                headers: Object.assign({ Accept: 'application/json' }, settings.headers || {}),
                body: settings.body,
                signal: controller.signal
            });

            let payload = null;
            try {
                payload = await response.json();
            } catch (_) {
                payload = null;
            }

            if (!response.ok) {
                const detail = payload && (payload.message || payload.detail);
                const requestId = response.headers && typeof response.headers.get === 'function'
                    ? response.headers.get('x-request-id')
                    : null;
                throw new ApiError(
                    detail || ('HTTP ' + response.status),
                    response.status,
                    payload,
                    payload && payload.code,
                    requestId
                );
            }
            if (payload === null) {
                throw new ApiError('Risposta JSON non valida', response.status, null, 'INVALID_JSON');
            }
            return payload;
        } catch (error) {
            if (error && error.name === 'AbortError') {
                throw new ApiError(
                    timedOut ? 'Richiesta scaduta' : 'Richiesta annullata',
                    0,
                    null,
                    timedOut ? 'REQUEST_TIMEOUT' : 'REQUEST_ABORTED',
                    null,
                    error
                );
            }
            if (error instanceof ApiError) throw error;
            throw new ApiError('Servizio non raggiungibile', 0, null, 'NETWORK_ERROR', null, error);
        } finally {
            global.clearTimeout(timeoutId);
            if (externalSignal) externalSignal.removeEventListener('abort', abortFromCaller);
        }
    }

    function postJson(url, payload, options) {
        const settings = options || {};
        return requestJson(url, {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, settings.headers || {}),
            body: JSON.stringify(payload),
            timeoutMs: settings.timeoutMs,
            signal: settings.signal
        });
    }

    global.LogicApi = Object.freeze({ ApiError, buildUrl, normalizeBase, postJson, requestJson });
})(window);
