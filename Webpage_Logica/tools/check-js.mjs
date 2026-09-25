import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';


const scriptsDirectory = 'scripts';
const files = readdirSync(scriptsDirectory)
    .filter(name => name.endsWith('.js'))
    .sort()
    .map(name => join(scriptsDirectory, name));
files.push('service-worker.js');
readdirSync('tools')
    .filter(name => name.endsWith('.mjs'))
    .sort()
    .forEach(name => files.push(join('tools', name)));

for (const file of files) {
    const result = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
    if (result.status !== 0) {
        process.stderr.write(result.stderr || result.stdout || `Controllo fallito: ${file}\n`);
        process.exit(result.status || 1);
    }
}

console.log(`Sintassi valida per ${files.length} script JavaScript.`);
