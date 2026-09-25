import { mkdir, writeFile } from 'node:fs/promises';
import { PAGE_ROUTES } from '../src/lib/pages.mjs';

await mkdir('.build', { recursive: true });
const routes = PAGE_ROUTES.map(({ file, route }) => {
  const redirect = `return 308 ${route}$is_args$args;`;
  if (!file.endsWith('index.html')) return `location = /${file} { ${redirect} }`;
  // Nginx internally resolves / to /index.html. Redirect only explicit legacy
  // requests: redirecting the internal index would send the canonical URL into a loop.
  const originalPath = '/' + file.replaceAll('.', '[.]');
  return `location = /${file} {
    if ($request_uri ~ "^${originalPath}([?]|$)") { ${redirect} }
    try_files $uri =404;
}`;
});
await writeFile('.build/legacy-routes.conf', '# Generated from the page catalogue.\n' + routes.join('\n') + '\n');
console.log(`Compatibilità di ${routes.length} URL HTML generata.`);
