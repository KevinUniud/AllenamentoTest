import { test as base, expect, type Page } from '@playwright/test';
import { PAGE_ROUTES, readPage } from '../../src/lib/pages.mjs';

const test = base.extend<{ diagnostics: void }>({
  diagnostics: [async ({ page, baseURL }, use) => {
    const scriptErrors: string[] = [];
    const hydrationErrors: string[] = [];
    const cspViolations: string[] = [];
    page.on('pageerror', error => scriptErrors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && /hydrat|Content Security Policy|violat.*(?:script-src|style-src)/i.test(message.text())) {
        hydrationErrors.push(message.text());
      }
    });
    await page.exposeFunction('__recordMigrationCsp', (detail: string) => cspViolations.push(detail));
    await page.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', event => {
        const report = (window as unknown as { __recordMigrationCsp: (detail: string) => Promise<void> }).__recordMigrationCsp;
        void report(`${event.effectiveDirective}: ${event.blockedURI}`);
      });
    });
    const origin = new URL(baseURL!).origin;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort('blockedbyclient');
      if (url.pathname.startsWith('/api/')) {
        return route.fulfill({ status: 503, json: { detail: 'Servizio non disponibile: fixture browser.' } });
      }
      return route.continue();
    });
    await use();
    expect(scriptErrors, 'Uncaught JavaScript errors').toEqual([]);
    expect(hydrationErrors, 'Hydration or CSP console errors').toEqual([]);
    expect(cspViolations, 'CSP violations from every document visited').toEqual([]);
  }, { auto: true }],
});

async function waitForPageReady(page: Page, file: string) {
  await expect(page.locator('#themeSelect')).toBeEnabled();
  const scripts = file === 'index.html' ? [] : readPage(file).scripts;
  if (scripts.length) {
    await page.waitForFunction((sources: string[]) => sources.every(source => {
      const scripts = (window as unknown as { __logicBrowserScripts?: Map<string, Promise<void>> }).__logicBrowserScripts;
      return scripts?.has(new URL(source, window.location.origin).href);
    }), scripts);
    await page.evaluate(async (sources: string[]) => {
      const scripts = (window as unknown as { __logicBrowserScripts: Map<string, Promise<void>> }).__logicBrowserScripts;
      await Promise.all(sources.map(source => scripts.get(new URL(source, window.location.origin).href)));
    }, scripts);
  }
  await expect(page.locator('.legacy-content-error')).toHaveCount(0);
}

async function openSettings(page: Page) {
  await expect(page.locator('#themeSelect')).toBeEnabled();
  await page.getByRole('button', { name: 'Apri impostazioni', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Impostazioni globali', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

for (const entry of PAGE_ROUTES) {
  test(`static page ${entry.route} loads without hydration or CSP errors`, async ({ page }) => {
    const response = await page.goto(entry.route);
    expect(response?.status()).toBe(200);
    const policy = response?.headers()['content-security-policy'];
    expect(policy).toBeTruthy();
    expect(policy).not.toContain("'unsafe-inline'");
    await waitForPageReady(page, entry.file);
    await expect(page).toHaveTitle(`${readPage(entry.file).title} — TestLogica`);
    await expect(page.locator('html')).toHaveAttribute('lang', 'it');
    await expect(page.locator('main')).toHaveCount(1);
    await expect(page.locator('main')).toBeVisible();
    await expect(page.locator('#main-content')).toHaveCount(1);
    await expect(page.locator('#settings-trigger')).toHaveCount(1);
    const dialog = await openSettings(page);
    await expect(dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true })).not.toBeChecked();
    await dialog.getByRole('button', { name: 'Chiudi', exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Apri impostazioni', exact: true })).toBeFocused();
  });
}

for (const file of ['index.html', 'lezioni/lezione-1.html', 'Errori_comuni/Implica.html']) {
  const entry = PAGE_ROUTES.find(page => page.file === file)!;
  test(`legacy URL ${file} preserves query and fragment`, async ({ page }) => {
    const suffix = '?browser_redirect=next%20js&attempt=1#retained-anchor';
    const response = await page.goto(`/${file}${suffix}`);
    expect(response?.status()).toBe(200);
    const previousRequest = response!.request().redirectedFrom();
    expect(previousRequest).not.toBeNull();
    expect((await previousRequest!.response())?.status()).toBe(308);
    const url = new URL(page.url());
    expect(url.pathname + url.search + url.hash).toBe(entry.route + suffix);
    await waitForPageReady(page, file);
  });
}

test('unknown page returns the exported 404 with working navigation and CSP', async ({ page }) => {
  const response = await page.goto('/browser-fixture-not-found/');
  expect(response?.status()).toBe(404);
  expect(response?.headers()['content-security-policy']).toBeTruthy();
  await expect(page.getByRole('heading', { name: 'Pagina non trovata', exact: true })).toBeVisible();
  await expect(page.locator('#themeSelect')).toBeEnabled();
  await page.getByRole('link', { name: 'Torna all’indice', exact: true }).click();
  await expect(page).toHaveURL('/');
  await waitForPageReady(page, 'index.html');
});

// Use base: one enforced CSP violation is the expected result in this case.
base('CSP blocks an injected inline script while authorized Next scripts run', async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort('blockedbyclient');
    if (url.pathname.startsWith('/api/')) return route.fulfill({ status: 503, json: {} });
    return route.continue();
  });
  await page.goto('/');
  await waitForPageReady(page, 'index.html');
  const outcome = await page.evaluate(() => new Promise<{
    directive: string;
    blockedURI: string;
    disposition: string;
    executed: boolean;
  }>((resolve, reject) => {
    const runtime = window as unknown as { __testlogicaCspNegative?: string };
    const script = document.createElement('script');
    const timeout = window.setTimeout(() => {
      document.removeEventListener('securitypolicyviolation', onViolation);
      script.remove();
      reject(new Error('No CSP violation was emitted for the injected script.'));
    }, 5_000);
    function onViolation(event: SecurityPolicyViolationEvent) {
      if (event.blockedURI !== 'inline' || event.effectiveDirective !== 'script-src-elem') return;
      window.clearTimeout(timeout);
      document.removeEventListener('securitypolicyviolation', onViolation);
      script.remove();
      resolve({
        directive: event.effectiveDirective,
        blockedURI: event.blockedURI,
        disposition: event.disposition,
        executed: runtime.__testlogicaCspNegative === 'executed',
      });
    }
    document.addEventListener('securitypolicyviolation', onViolation);
    script.textContent = "window.__testlogicaCspNegative = 'executed';";
    document.body.appendChild(script);
  }));
  expect(outcome).toEqual({ directive: 'script-src-elem', blockedURI: 'inline', disposition: 'enforce', executed: false });
});

test('settings persist appearance and consent across reload and revoke demographic consent', async ({ page }) => {
  await page.goto('/');
  let dialog = await openSettings(page);
  await expect(dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel('Consenti invio feedback senza nome o account', { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel('Includi dati demografici nel feedback', { exact: true })).toBeDisabled();
  await dialog.getByLabel('Tema:', { exact: true }).selectOption('day');
  await dialog.getByRole('textbox', { name: 'Dimensione font in pixel' }).fill('20');
  await dialog.getByRole('textbox', { name: 'Dimensione font in pixel' }).press('Enter');
  await dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true }).check();
  await dialog.getByLabel('Consenti invio feedback senza nome o account', { exact: true }).check();
  await dialog.getByLabel('Includi dati demografici nel feedback', { exact: true }).check();
  await expect(page.locator('html')).toHaveClass(/\bfont-size-20\b/);
  await expect(page.locator('body')).toHaveClass(/\bday-mode\b/);
  await dialog.getByRole('button', { name: 'Chiudi', exact: true }).click();

  await page.reload();
  dialog = await openSettings(page);
  await expect(dialog.getByLabel('Tema:', { exact: true })).toHaveValue('day');
  await expect(dialog.getByRole('textbox', { name: 'Dimensione font in pixel' })).toHaveValue('20');
  await expect(dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true })).toBeChecked();
  await expect(dialog.getByLabel('Consenti invio feedback senza nome o account', { exact: true })).toBeChecked();
  await expect(dialog.getByLabel('Includi dati demografici nel feedback', { exact: true })).toBeChecked();
  await expect(page.locator('html')).toHaveClass(/\bfont-size-20\b/);
  await expect(page.locator('body')).toHaveClass(/\bday-mode\b/);

  await dialog.getByLabel('Consenti invio feedback senza nome o account', { exact: true }).uncheck();
  await expect(dialog.getByLabel('Includi dati demografici nel feedback', { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel('Includi dati demografici nel feedback', { exact: true })).toBeDisabled();
  await page.reload();
  dialog = await openSettings(page);
  await expect(dialog.getByLabel('Consenti invio feedback senza nome o account', { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel('Includi dati demografici nel feedback', { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true })).toBeChecked();
});

test('lesson completion and bookmarks survive document navigation and local data can be erased', async ({ page }) => {
  await page.goto('/');
  let dialog = await openSettings(page);
  await dialog.getByLabel('Salva localmente sessioni e progressi', { exact: true }).check();
  await dialog.getByLabel('Tema:', { exact: true }).selectOption('day');
  await dialog.getByRole('button', { name: 'Chiudi', exact: true }).click();
  await page.evaluate(() => { (window as unknown as { __migrationDocument: string }).__migrationDocument = 'home'; });
  await page.getByRole('link', { name: 'Apri Lezioni', exact: true }).click();
  await page.waitForURL('**/lezioni/lezione-1/');
  await waitForPageReady(page, 'lezioni/lezione-1.html');
  expect(await page.evaluate(() => (window as unknown as { __migrationDocument?: string }).__migrationDocument)).toBeUndefined();
  await expect(page.locator('body')).toHaveAttribute('data-lesson-id', 'lesson-1');
  await expect(page.locator('body')).toHaveClass(/\bday-mode\b/);
  const bookmark = page.locator('.lesson-bookmark-button').first();
  await expect(bookmark).toHaveText('Salva segnalibro');
  await bookmark.click();
  await expect(bookmark).toHaveText('Rimuovi segnalibro');
  await page.getByRole('button', { name: 'Segna lezione come completata', exact: true }).click();
  await expect(page.locator('#lessonCompletionButton')).toHaveText('Lezione completata');
  await expect(page.locator('#lessonCompletionButton')).toBeDisabled();

  await page.reload();
  await waitForPageReady(page, 'lezioni/lezione-1.html');
  await expect(page.locator('.lesson-bookmark-button').first()).toHaveText('Rimuovi segnalibro');
  await expect(page.locator('#lessonCompletionButton')).toHaveText('Lezione completata');
  await expect(page.locator('.lesson-switcher-link[href="/lezioni/lezione-1/"]').first()).toContainText('✓');
  await page.goto('/');
  await waitForPageReady(page, 'index.html');
  await expect(page.locator('#indexLessonProgress')).toContainText('Lezioni completate: 1 su 6.');
  const resume = page.getByRole('link', { name: /Riprendi dall’ultimo segnalibro:/ });
  await expect(resume).toHaveAttribute('href', /^\/lezioni\/lezione-1\/#/);

  // Synthetic session and demographics make the full erase operation observable.
  const saved = await page.evaluate(async () => {
    localStorage.setItem('logDataAge', '99');
    const storage = (window as unknown as { LogicAppStorage: { instance: { put: (type: string, id: string, value: unknown) => Promise<boolean> } } }).LogicAppStorage.instance;
    return storage.put('sessions', 'browser-fixture', { expiresAt: Date.now() + 60_000, fixture: true });
  });
  expect(saved).toBe(true);
  dialog = await openSettings(page);
  await dialog.getByRole('button', { name: 'Elimina dati locali', exact: true }).click();
  await expect(dialog.locator('[aria-live="polite"]')).toHaveText('Sessioni, progressi e dati demografici locali eliminati.');
  await dialog.getByRole('button', { name: 'Chiudi', exact: true }).click();
  await expect(page.locator('#indexLessonProgress')).toContainText('Lezioni completate: 0 su 6.');
  await expect(resume).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('logDataAge'))).toBeNull();
  expect(await page.evaluate(async () => {
    const storage = (window as unknown as { LogicAppStorage: { instance: { exportAll: () => Promise<unknown[]> } } }).LogicAppStorage.instance;
    return storage.exportAll();
  })).toEqual([]);
  await page.reload();
  await waitForPageReady(page, 'index.html');
  await expect(page.locator('#indexLessonProgress')).toContainText('Lezioni completate: 0 su 6.');
  await expect(page.getByRole('link', { name: /Riprendi dall’ultimo segnalibro:/ })).toHaveCount(0);
});

for (const entry of PAGE_ROUTES.filter(page => ['index.html', 'lezioni/lezione-1.html'].includes(page.file))) {
  test(`mobile pages preserve content width and settings access: ${entry.route}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(entry.route);
    await waitForPageReady(page, entry.file);
    await expect(page.locator('#main-content')).toHaveCSS('padding-top', '52px');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const dialog = await openSettings(page);
    await dialog.getByLabel('Tema:', { exact: true }).selectOption('day');
    await expect(page.locator('body')).toHaveClass(/\bday-mode\b/);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: 'Apri impostazioni', exact: true })).toBeFocused();
    expect(await page.locator('#main-content').evaluate(element => element.inert)).toBe(false);
  });
}
