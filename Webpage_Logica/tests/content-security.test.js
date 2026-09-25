const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

function collectHtml(directory) {
    return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
        // Archived HTML is not published or consumed by the current frontend.
        if (entry.isDirectory() && ['.git', 'node_modules', '.next', 'out', 'public', '.build', 'test-results', 'playwright-report', 'old_pages'].includes(entry.name)) return [];
        const item = path.join(directory, entry.name);
        if (entry.isDirectory()) return collectHtml(item);
        return entry.name.endsWith('.html') ? [item] : [];
    });
}

test('HTML contains no inline CSS, scripts, or event handlers', () => {
    collectHtml('.').forEach(file => {
        const source = fs.readFileSync(file, 'utf8');
        assert.doesNotMatch(source, /\sstyle\s*=/i, file + ' contains style=');
        assert.doesNotMatch(source, /<style\b/i, file + ' contains a style block');
        assert.doesNotMatch(source, /\son[a-z]+\s*=/i, file + ' contains an inline event handler');
        const scripts = source.match(/<script\b[^>]*>[\s\S]*?<\/script>/gi) || [];
        scripts.forEach(script => {
            assert.match(script, /\ssrc\s*=/i, file + ' contains an inline script');
        });
    });
});

test('nginx CSP does not allow inline styles or scripts', () => {
    const config = fs.readFileSync('nginx/default.conf.template', 'utf8');
    const headers = fs.readFileSync('nginx/security-headers.conf', 'utf8');
    const csp = headers.split('\n').find(line => line.includes('Content-Security-Policy')) || '';
    assert.match(config, /include \/etc\/nginx\/security-headers\.conf;/);
    assert.doesNotMatch(csp, /unsafe-inline/);
    assert.match(csp, /style-src 'self'/);
    assert.match(csp, /script-src 'self'/);
});

test('locations with custom response headers keep the complete security policy', () => {
    const config = fs.readFileSync('nginx/default.conf.template', 'utf8');
    const headers = fs.readFileSync('nginx/security-headers.conf', 'utf8');
    const dockerfile = fs.readFileSync('Dockerfile', 'utf8');
    const required = [
        'X-Content-Type-Options',
        'X-Frame-Options',
        'Referrer-Policy',
        'Permissions-Policy',
        'Cross-Origin-Opener-Policy',
        'Cross-Origin-Resource-Policy',
        'Content-Security-Policy'
    ];
    required.forEach(header => assert.match(headers, new RegExp(`add_header ${header} `)));
    assert.match(
        dockerfile,
        /COPY nginx\/security-headers\.conf \/etc\/nginx\/security-headers\.conf/
    );

    [
        /location = \/service-worker\.js \{([\s\S]*?)\n\s*\}/,
        /location ~\* \\.\(\?:css\|js\)\$ \{([\s\S]*?)\n\s*\}/,
        /location \^~ \/api\/feedback\/charts\/ \{([\s\S]*?)\n\s*\}/
    ].forEach(pattern => {
        const location = config.match(pattern);
        assert.ok(location, `Location Nginx non trovata: ${pattern}`);
        assert.match(location[1], /include \/etc\/nginx\/security-headers\.conf;/);
    });
});
