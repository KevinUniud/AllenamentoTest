const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function loadClient(fetchImplementation) {
    const context = {
        AbortController,
        clearTimeout,
        fetch: fetchImplementation,
        setTimeout,
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync('scripts/api-client.js', 'utf8'), context);
    return context.LogicApi;
}

test('buildUrl normalizes relative API paths', () => {
    const api = loadClient(async () => {});
    assert.equal(api.buildUrl('/generator/test', '/api/'), '/api/generator/test');
    assert.equal(api.buildUrl('/api/revisione', '/ignored'), '/api/revisione');
});

test('postJson returns parsed payload', async () => {
    const api = loadClient(async (_url, options) => ({
        ok: true,
        status: 200,
        json: async () => ({ received: JSON.parse(options.body) })
    }));

    assert.deepEqual(await api.postJson('/api/test', { value: 3 }), { received: { value: 3 } });
});

test('postJson exposes structured HTTP errors', async () => {
    const api = loadClient(async () => ({
        ok: false,
        status: 422,
        headers: { get: name => name === 'x-request-id' ? 'request-123' : null },
        json: async () => ({ code: 'INVALID_INPUT', message: 'Input non valido' })
    }));

    await assert.rejects(api.postJson('/api/test', {}), error => {
        assert.equal(error.status, 422);
        assert.equal(error.code, 'INVALID_INPUT');
        assert.equal(error.requestId, 'request-123');
        assert.equal(error.payload.code, 'INVALID_INPUT');
        return true;
    });
});

test('network failures are normalized', async () => {
    const api = loadClient(async () => {
        throw new TypeError('fetch failed');
    });

    await assert.rejects(api.postJson('/api/test', {}), error => {
        assert.equal(error.name, 'ApiError');
        assert.equal(error.code, 'NETWORK_ERROR');
        assert.equal(error.status, 0);
        return true;
    });
});

test('timeouts abort the underlying request', async () => {
    const api = loadClient((_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
            const error = new Error('aborted');
            error.name = 'AbortError';
            reject(error);
        }, { once: true });
    }));

    await assert.rejects(api.postJson('/api/test', {}, { timeoutMs: 1 }), error => {
        assert.equal(error.code, 'REQUEST_TIMEOUT');
        return true;
    });
});
