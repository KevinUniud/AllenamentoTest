const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const test = require('node:test');

const compose = fs.readFileSync('compose.server.yml', 'utf8');
const environment = fs.readFileSync('.env.server.example', 'utf8');
const edge = fs.readFileSync('deploy/nginx-edge.example.conf', 'utf8');
const dockerignore = fs.readFileSync('.dockerignore', 'utf8');
const dockerfile = fs.readFileSync('Dockerfile', 'utf8');
const deployScript = fs.readFileSync('ops/server-deploy.sh', 'utf8');

test('server compose tags both images and isolates API and feedback networks', () => {
    assert.match(compose, /testlogica-web\}:\$\{RELEASE_TAG:/);
    assert.match(compose, /testlogica-feedback\}:\$\{RELEASE_TAG:/);
    assert.match(compose, /BACKEND_NETWORK_NAME:\?Impostare BACKEND_NETWORK_NAME/);
    assert.match(compose, /backend:\n\s+external: true/);
    assert.match(compose, /feedback-internal:\n\s+internal: true/);
    assert.match(compose, /web-loopback:\n\s+driver: bridge/);
    assert.match(compose, /API_UPSTREAM: \$\{API_UPSTREAM:-http:\/\/api-logica:5000\}/);
    assert.match(compose, /org\.opencontainers\.image\.revision: \$\{WEB_RELEASE_REVISION/);
    assert.match(compose, /org\.opencontainers\.image\.revision: \$\{FEEDBACK_RELEASE_REVISION/);
    assert.match(environment, /^WEB_RELEASE_REVISION=replace-with-web-source-revision$/m);
    assert.match(environment, /^FEEDBACK_RELEASE_REVISION=replace-with-feedback-source-revision$/m);

    const feedbackService = compose.match(/\n  feedback:\n([\s\S]*?)\n  webpage-logica:/);
    assert.ok(feedbackService);
    assert.doesNotMatch(feedbackService[1], /\n\s+ports:/);
    assert.doesNotMatch(feedbackService[1], /web-loopback/);

    const webService = compose.match(/\n  webpage-logica:\n([\s\S]*?)\nnetworks:/);
    assert.ok(webService);
    assert.match(webService[1], /- web-loopback/);
});

test('server Web binds loopback and all runtimes have bounded resources', () => {
    assert.match(dockerfile, /^FROM nginx:1\.30\.4-alpine@sha256:[0-9a-f]{64}$/m);
    assert.match(compose, /WEB_BIND_ADDRESS:-127\.0\.0\.1/);
    assert.match(environment, /^WEB_BIND_ADDRESS=127\.0\.0\.1$/m);
    assert.match(compose, /read_only: true/g);
    assert.match(compose, /no-new-privileges:true/g);
    assert.match(compose, /cap_drop:\n\s+- ALL/g);
    assert.match(compose, /pids_limit:/g);
    assert.match(compose, /mem_limit:/g);
    assert.match(compose, /cpus:/g);
    assert.match(compose, /max-size: 10m/g);
    assert.match(compose, /stop_grace_period: \$\{FEEDBACK_STOP_GRACE_SECONDS:-960\}s/);
    assert.match(environment, /^FEEDBACK_STOP_GRACE_SECONDS=960$/m);
});

test('edge owns HTTPS, HSTS and per-client feedback throttling', () => {
    assert.match(edge, /listen 443 ssl http2;/);
    assert.match(edge, /Strict-Transport-Security/);
    assert.match(edge, /limit_req_zone \$binary_remote_addr/);
    assert.match(edge, /location = \/api\/revisione/);
    assert.match(edge, /location \/api\/ \{/);
    assert.match(edge, /limit_req zone=testlogica_api_per_client burst=120 nodelay;/);
    assert.match(edge, /limit_conn testlogica_api_connections 32;/);
    assert.match(edge, /access_log off;/);
    assert.match(edge, /proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;/);
    assert.match(edge, /ssl_protocols TLSv1\.2 TLSv1\.3;/);
    assert.match(edge, /proxy_read_timeout 130s;/);
});

test('build context excludes server environments and operational state', () => {
    assert.equal(dockerignore.split('\n')[0], '*');
    assert.doesNotMatch(dockerignore, /!\.env/);
    assert.doesNotMatch(dockerignore, /!ops/);
    assert.doesNotMatch(dockerignore, /!deploy/);
    assert.doesNotMatch(dockerignore, /!(?:node_modules|out|public|\.next|\.build)(?:\/|\n)/);
    ['package.json', 'package-lock.json', 'next.config.mjs', 'tsconfig.json', 'src/**'].forEach(name => {
        assert.ok(dockerignore.split('\n').includes(`!${name}`), `${name} must enter the build context`);
    });
});

test('multi-stage build publishes only the verified Next export and generated Nginx configuration', () => {
    assert.match(dockerfile, /^FROM node:24\.13\.0-alpine@sha256:[0-9a-f]{64} AS build$/m);
    assert.match(dockerfile, /COPY package\.json package-lock\.json \.\//);
    assert.match(dockerfile, /RUN npm ci --no-audit --no-fund/);
    assert.match(dockerfile, /RUN npm run build/);
    const runtime = dockerfile.slice(dockerfile.lastIndexOf('FROM nginx:'));
    assert.match(runtime, /COPY --from=build \/app\/out\/ \/usr\/share\/nginx\/html\//);
    assert.match(runtime, /COPY --from=build \/app\/\.build\/csp-map\.conf \/etc\/nginx\/csp-map\.conf/);
    assert.match(runtime, /COPY --from=build \/app\/\.build\/legacy-routes\.conf \/etc\/nginx\/legacy-routes\.conf/);
    assert.doesNotMatch(runtime, /COPY (?:\. |src|scripts|package|node_modules)|next start|npm /);
});

test('Nginx applies per-page CSP, legacy redirects and immutable Next asset caching', () => {
    const nginx = fs.readFileSync('nginx/default.conf.template', 'utf8');
    const headers = fs.readFileSync('nginx/security-headers.conf', 'utf8');
    assert.ok(nginx.indexOf('include /etc/nginx/csp-map.conf;') < nginx.indexOf('server {'));
    assert.match(nginx, /server \{[\s\S]*include \/etc\/nginx\/legacy-routes\.conf;/);
    assert.match(nginx, /error_page 404 \/404\.html;/);
    assert.match(headers, /script-src 'self'\$testlogica_script_hashes;/);
    assert.match(headers, /style-src 'self'\$testlogica_style_hashes;/);
    assert.doesNotMatch(headers, /unsafe-inline|unsafe-eval/);
    const nextAssets = nginx.match(/location \^~ \/_next\/static\/ \{([\s\S]*?)\n\s*\}/);
    assert.ok(nextAssets);
    assert.match(nextAssets[1], /include \/etc\/nginx\/security-headers\.conf;/);
    assert.match(nextAssets[1], /Cache-Control "public, max-age=31536000, immutable"/);
    assert.match(nextAssets[1], /try_files \$uri =404;/);
});

test('deployment state defaults outside both release repositories', () => {
    assert.match(environment, /^DEPLOY_STATE_DIR=\/srv\/testlogica\/shared\/state\/web-feedback$/m);
    assert.match(environment, /^FEEDBACK_DATA_DIR=\/srv\/testlogica\/shared\/feedback-data$/m);
    assert.match(environment, /^API_PROXY_TIMEOUT_SECONDS=125$/m);
    assert.match(deployScript, /recover_failed_release/);
    assert.match(deployScript, /Primo deploy non validato: arresto dello stack/);
    assert.match(deployScript, /Ripristino automatico della release Web\/feedback/);
    assert.match(deployScript, /server_compose down --remove-orphans/);
});

test('a rejected candidate keeps the previous rollback target', () => {
    const candidateSmoke = deployScript.indexOf(
        '"$script_dir/server-smoke.sh" --env-file "$SERVER_ENV_FILE"'
    );
    const rollbackPromotion = deployScript.indexOf(
        'cp "$state_dir/active.env" "$state_dir/rollback.env.tmp"'
    );
    const activePromotion = deployScript.indexOf(
        'cp "$SERVER_ENV_FILE" "$state_dir/active.env.tmp"'
    );

    assert.ok(candidateSmoke >= 0);
    assert.ok(rollbackPromotion > candidateSmoke);
    assert.ok(activePromotion > rollbackPromotion);
});

test('server environment file wins over conflicting exported application variables', () => {
    const probe = childProcess.spawnSync(
        'sh',
        ['-c', '. ./ops/server-common.sh; server_env_value RELEASE_TAG', 'ops/server-test'],
        {
            cwd: process.cwd(),
            encoding: 'utf8',
            env: {
                ...process.env,
                RELEASE_TAG: 'ambient-must-not-win',
                COMPOSE_PROJECT_NAME: 'ambient-must-not-win',
                SERVER_ENV_FILE: `${process.cwd()}/.env.server.example`
            }
        }
    );
    assert.equal(probe.status, 0, probe.stderr);
    assert.equal(probe.stdout.trim(), 'replace-with-release-id');
});
