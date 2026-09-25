import { expect, test, type Page, type Route } from '@playwright/test';

const pageErrors = new WeakMap<Page, string[]>();
const unavailable = {
  code: 'SERVICE_UNAVAILABLE',
  message: 'Servizio non disponibile: fixture offline.',
};

async function offlineApi(route: Route) {
  await route.fulfill({ status: 503, json: unavailable });
}

test.beforeEach(async ({ page, baseURL }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && /hydrat|Content Security Policy/i.test(message.text())) {
      errors.push(message.text());
    }
  });
  await page.exposeFunction('__recordInteractiveCsp', (detail: string) => errors.push(detail));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', event => {
      const report = (window as unknown as { __recordInteractiveCsp: (detail: string) => Promise<void> }).__recordInteractiveCsp;
      void report(`CSP ${event.effectiveDirective}: ${event.blockedURI}`);
    });
  });

  // Only the local page and its static resources reach the server. Every API
  // request is fulfilled below, and external origins are blocked entirely.
  const origin = new URL(baseURL ?? 'http://127.0.0.1:18080').origin;
  await page.route('**/*', async route => {
    if (new URL(route.request().url()).origin === origin) {
      await route.continue();
    } else {
      await route.abort('blockedbyclient');
    }
  });
  await page.route('**/api/**', offlineApi);
});

test.afterEach(async ({ page }) => {
  expect(pageErrors.get(page), 'No uncaught browser errors').toEqual([]);
});

test('laboratorio: valida la formula ed esegue analisi e confronto con API simulate', async ({ page }) => {
  const requests: Array<{ path: string; payload: unknown }> = [];
  const truthTable = {
    vars: ['p', 'q'],
    rows: [
      { valuation: ['p-false', 'q-false'], result: false },
      { valuation: ['p-false', 'q-true'], result: false },
      { valuation: ['p-true', 'q-false'], result: false },
      { valuation: ['p-true', 'q-true'], result: true },
    ],
  };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    requests.push({ path, payload: route.request().postDataJSON() });
    if (path === '/api/prolog-bridge/logic/vars-in-formula') {
      await route.fulfill({ json: { result: ['p', 'q'] } });
    } else if (path === '/api/prolog-bridge/logic/truth-table-auto') {
      await route.fulfill({ json: { result: truthTable } });
    } else if (path === '/api/prolog-bridge/equivalence/equiv') {
      await route.fulfill({ json: { result: true } });
    } else {
      await offlineApi(route);
    }
  });

  await page.goto('/strumenti/sandbox/');
  const status = page.locator('#sandboxStatus');
  await expect(status).toHaveText("Inserisci una formula oppure costruiscila dall'albero.");
  await expect(status).toHaveAttribute('aria-live', 'polite');
  const formula = page.getByLabel('Formula principale', { exact: true });
  await formula.fill('p ∧ q');
  await expect(status).toContainText('Sintassi riconosciuta');
  await expect(page.locator('#sandboxTree').getByRole('group')).toBeVisible();

  await page.getByRole('button', { name: 'Trova variabili', exact: true }).click();
  await expect(status).toHaveText('Analisi completata.');
  await expect(page.locator('#sandboxResult pre')).toHaveText('[ "p", "q" ]');

  await page.getByRole('button', { name: 'Tabella di verità', exact: true }).click();
  const table = page.getByRole('table', { name: 'Tabella di verità della formula' });
  await expect(table).toBeVisible();
  await expect(table.locator('tbody tr')).toHaveCount(4);
  await expect(table.locator('tbody tr').last().getByRole('cell')).toHaveText(['true', 'true', 'true']);

  await page.getByLabel('Seconda formula, per il confronto', { exact: true }).fill('q ∧ p');
  await page.getByRole('button', { name: 'Confronta formule', exact: true }).click();
  await expect(page.locator('#sandboxResult pre')).toHaveText('true');
  expect(requests).toEqual([
    { path: '/api/prolog-bridge/logic/vars-in-formula', payload: { expr: 'and(p,q)', timeout: 10 } },
    { path: '/api/prolog-bridge/logic/truth-table-auto', payload: { expr: 'and(p,q)', timeout: 10 } },
    { path: '/api/prolog-bridge/equivalence/equiv', payload: { left: 'and(p,q)', right: 'and(q,p)', timeout: 10 } },
  ]);

  await page.getByRole('button', { name: 'Cancella', exact: true }).click();
  await expect(formula).toBeEmpty();
  await expect(page.locator('#sandboxResult')).toBeEmpty();
  await page.getByRole('button', { name: 'Trova variabili', exact: true }).click();
  await expect(status).toHaveText('Inserisci una formula.');
  expect(requests).toHaveLength(3);
});

test('quiz: segnala il backend offline e lascia disponibile il ritorno al menu', async ({ page }) => {
  const apiPaths: string[] = [];
  await page.route('**/api/**', async route => {
    apiPaths.push(new URL(route.request().url()).pathname);
    await offlineApi(route);
  });

  await page.goto('/esercizi/esercitazione/');
  // This warning is emitted only after the page controllers have initialized.
  await expect(page.locator('#quizAdaptiveNotice')).toContainText('Limiti del backend non disponibili');
  await page.locator('#quizPreset').selectOption('custom');
  for (const type of ['truth-value', 'logical-consequence', 'translation', 'quantifier-negation']) {
    await page.locator(`[data-quiz-question-type][value="${type}"]`).uncheck();
  }
  await page.getByRole('spinbutton', { name: 'Numero domande di equivalenza', exact: true }).fill('1');
  await expect(page.locator('#quizQuestionCount')).toHaveText('1');
  await page.getByRole('button', { name: 'Inizia il quiz', exact: true }).click();

  const status = page.locator('#quizStatus');
  await expect(status).toBeVisible();
  await expect(status).toHaveAttribute('aria-live', 'polite');
  await expect(status).toContainText('Errore nel caricamento esercizio: Servizio non disponibile');
  await expect(page.locator('#quizQuestion')).toHaveText("Impossibile caricare l'esercizio.");
  await expect(page.getByRole('button', { name: 'Controlla la risposta', exact: true })).toBeDisabled();
  await expect(page.locator('#quizOptions').getByRole('radio')).toHaveCount(0);
  await expect(page.locator('#quizTimerDisplay')).toBeHidden();
  const menu = page.locator('#quizIndexNav').getByRole('link');
  await expect(menu).toBeVisible();
  await expect(menu).toHaveAttribute('href', '/');
  expect(apiPaths).toContain('/api/capabilities');
  expect(apiPaths).toContain('/api/generator/multiple-questions');
  expect(apiPaths).toContain('/api/generator/build-exercise-from-depth');
  await menu.click();
  await expect(page).toHaveURL('/');
});

test('quiz: completa una domanda simulata da tastiera e mostra il risultato senza inviare feedback', async ({ page }) => {
  const requests: Array<{ path: string; payload: unknown }> = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    requests.push({ path, payload: route.request().postDataJSON() });
    if (path === '/api/capabilities') {
      await route.fulfill({ json: {
        limits: { question_count: { maximum: 20 }, batch_size: 20 },
        question_types: ['equivalence', 'truth-value', 'logical-consequence', 'translation', 'quantifier-negation'],
      } });
    } else if (path === '/api/generator/multiple-questions') {
      await route.fulfill({ json: { questions: [{ index: 0, status: 'ok', result: {
        question_id: 'browser-equivalence-fixture',
        question_prolog: 'p',
        options: [
          { formula_prolog: 'p', is_correct: true },
          { formula_prolog: 'q', is_correct: false },
          { formula_prolog: 'not(p)', is_correct: false },
          { formula_prolog: 'and(p,q)', is_correct: false },
        ],
      } }] } });
    } else {
      await offlineApi(route);
    }
  });

  await page.goto('/esercizi/esercitazione/');
  // This value changes only once the controller has applied our capabilities.
  await expect(page.getByRole('spinbutton', { name: 'Numero domande di equivalenza', exact: true })).toHaveAttribute('max', '20');
  await page.locator('#quizPreset').selectOption('custom');
  for (const type of ['truth-value', 'logical-consequence', 'translation', 'quantifier-negation']) {
    await page.locator(`[data-quiz-question-type][value="${type}"]`).uncheck();
  }
  await page.getByRole('spinbutton', { name: 'Numero domande di equivalenza', exact: true }).fill('1');
  await expect(page.locator('#quizQuestionCount')).toHaveText('1');
  await page.getByRole('button', { name: 'Inizia il quiz', exact: true }).click();
  await expect(page.locator('#quizQuestion')).toHaveText('Quale formula è equivalente a "P":');
  await expect(page.locator('#quizOptions').getByRole('radio')).toHaveCount(4);

  const correctOption = page.getByRole('radio', { name: 'P', exact: true });
  const correctIndex = await correctOption.getAttribute('data-index');
  await correctOption.focus();
  await correctOption.press('Enter');
  await expect(correctOption).toHaveAttribute('aria-checked', 'true');
  await correctOption.press('Enter');
  // Feedback adds text to the accessible name; keep identifying the selected option.
  await expect(page.locator(`#quizOptions [data-index="${correctIndex}"]`)).toHaveClass(/\bis-correct\b/);
  await expect(page.locator('#quizStatus')).toContainText('Risposta registrata.');
  const results = page.getByRole('button', { name: 'Vedi i risultati', exact: true });
  await expect(results).toBeFocused();
  await results.press('Enter');

  await expect(page.locator('#quizReviewTitle')).toHaveText('Risultati del quiz');
  await expect(page.locator('#quizReviewList')).toContainText('1 risposte corrette su 1');
  await expect(page.locator('#quizReviewList .quiz-review-item')).toHaveCount(1);
  await expect(page.locator('#quizTimerDisplay')).toBeHidden();
  expect(requests.map(request => request.path)).toEqual([
    '/api/capabilities', '/api/generator/multiple-questions',
  ]);
  expect(requests[1].payload).toMatchObject({ questions: [{ operation: 'build_ex_depth' }] });
});

test('grafici: apre il lightbox da tastiera, isola lo sfondo e ripristina il focus', async ({ page }) => {
  const generation = 'synthetic-browser-fixture';
  const imagePath = `/api/feedback/charts/${generation}/general/performance_summary.png`;
  // A one-pixel PNG; no production chart, feedback data or remote image is used.
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
    'base64',
  );
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/feedback/charts/manifest') {
      await route.fulfill({
        json: {
          schema_version: 1,
          generation_id: generation,
          generated_at: '2026-09-23T10:00:00Z',
          session_count: 3,
          charts: [{
            id: 'general.performance_summary',
            category: 'general',
            filename: 'performance_summary.png',
          }],
        },
      });
    } else if (path === imagePath) {
      await route.fulfill({ contentType: 'image/png', body: png });
    } else {
      await offlineApi(route);
    }
  });

  await page.goto('/grafici/grafici/');
  await expect(page.locator('#feedbackChartsStatus')).toContainText('Disponibili 1 grafici aggiornati');
  await expect(page.locator('#feedbackChartsLastPublished')).toContainText('3 sessioni aggregate');
  const title = 'Riepilogo prestazioni generali del test';
  const card = page.getByRole('button', { name: `Ingrandisci grafico: ${title}`, exact: true });
  const chart = card.getByRole('img', { name: title, exact: true });
  await card.scrollIntoViewIfNeeded();
  await expect(chart).toHaveAttribute('src', imagePath);
  await expect.poll(() => chart.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1);
  await card.focus();
  await card.press('Enter');

  const dialog = page.getByRole('dialog', { name: title, exact: true });
  const close = dialog.getByRole('button', { name: 'Chiudi grafico ingrandito', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('aria-modal', 'true');
  await expect(dialog.getByRole('img', { name: title, exact: true })).toHaveAttribute('src', new RegExp(`${imagePath}$`));
  await expect(close).toBeFocused();
  expect(await dialog.evaluate(element => element.closest('[inert], [aria-hidden="true"]'))).toBeNull();
  // The card is intentionally absent from accessible role locators while inert.
  const backgroundCard = page.locator('.graph-card').filter({ has: page.locator('[data-chart-id="general.performance_summary"]') });
  expect(await backgroundCard.evaluate(element => Boolean(element.closest('[inert]')))).toBe(true);
  await page.keyboard.press('Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(card).toBeFocused();
  expect(await card.evaluate(element => Boolean(element.closest('[inert], [aria-hidden="true"]')))).toBe(false);
});
