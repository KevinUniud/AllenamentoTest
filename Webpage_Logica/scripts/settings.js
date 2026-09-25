/*
 * Modulo impostazioni globali.
 * Si occupa di: tema, dimensione font, modalita daltonismo e preferenze esercizi.
 */

/**
 * Inizializza l'interfaccia impostazioni e applica i valori persistiti.
 * @pre document.body e localStorage sono disponibili nel browser.
 * @post Esistono bottone/overlay impostazioni e le preferenze correnti sono applicate al DOM.
 */
function initGlobalSettings() {
    const preferences = window.LogicPreferences;
    if (!preferences) throw new Error('Modulo settings-preferences.js non caricato');
    const privacy = window.LogicPrivacy || null;
    const appStorage = window.LogicAppStorage && window.LogicAppStorage.instance;
    const FONT_KEY = preferences.KEYS.font;
    const EX_HIGHLIGHT_KEY = preferences.KEYS.highlightAtoms;
    const EX_PARENS_KEY = preferences.KEYS.differentiateParens;
    const THEME_KEY = preferences.KEYS.theme;
    const DALTONISM_KEY = preferences.KEYS.daltonism;
    const MIN_FONT_PX = 12;
    const MAX_FONT_PX = 28;
    const DEFAULT_FONT_PX = 16;

    function clearLegacyDemographics() {
        ['logDataAge', 'logDataInstitution', 'logDataStem'].forEach(function(key) {
            localStorage.removeItem(key);
        });
    }

    /**
     * Limita la dimensione font al range configurato.
     * @pre value e convertibile a numero o valore arbitrario.
     * @post Restituisce sempre un intero compreso tra MIN_FONT_PX e MAX_FONT_PX.
     */
    function clampFontPx(value) {
        return preferences.clampFontPx(value, MIN_FONT_PX, MAX_FONT_PX, DEFAULT_FONT_PX);
    }

    /**
     * Applica la dimensione font base tramite una classe CSS predefinita.
     * @pre sizePx e un valore numerico o convertibile.
     * @post documentElement espone una sola classe font-size-* e il valore clamped viene restituito.
     */
    function applyFontPx(sizePx) {
        const safe = clampFontPx(sizePx);
        for (let value = MIN_FONT_PX; value <= MAX_FONT_PX; value += 1) {
            document.documentElement.classList.remove('font-size-' + value);
        }
        document.documentElement.classList.add('font-size-' + safe);
        return safe;
    }

    /**
     * Parsing di un input utente in pixel (es. "16" o "16px").
     * @pre text e una stringa o valore convertibile a stringa.
     * @post Restituisce un numero clamped oppure null se non valido.
     */
    function parsePxValue(text) {
        return preferences.parsePxValue(text, MIN_FONT_PX, MAX_FONT_PX, DEFAULT_FONT_PX);
    }

    const savedPx = localStorage.getItem(FONT_KEY);

    const initialFontPx = applyFontPx(savedPx || DEFAULT_FONT_PX);
    let currentFontPx = initialFontPx;

    // Applica il tema giorno/notte tramite classi sul documento.
    function applyTheme(mode) {
        return preferences.applyTheme(document, mode);
    }

    // Applica una palette semantica alternativa per accessibilita visiva.
    function applyDaltonism(mode) {
        return preferences.applyDaltonism(document, mode);
    }

    const savedTheme = localStorage.getItem(THEME_KEY) || 'night';
    applyTheme(savedTheme);
    const savedDaltonism = applyDaltonism(localStorage.getItem(DALTONISM_KEY) || 'none');

    /**
     * Legge un flag booleano persistito su localStorage con convenzione 1/0.
     * @pre key e una chiave localStorage valida.
     * @post Restituisce true solo se il valore salvato e "1".
     */
    function readBool(key) {
        return preferences.readBool(localStorage, key);
    }

    /**
     * Persiste un flag booleano in localStorage con convenzione 1/0.
     * @pre key e una chiave localStorage valida.
     * @post localStorage[key] viene aggiornato con "1" o "0".
     */
    function writeBool(key, value) {
        preferences.writeBool(localStorage, key, value);
    }

    // Notifica gli script degli esercizi quando cambiano le opzioni locali.
    function publishExerciseSettings() {
        const detail = {
            highlightAtoms: readBool(EX_HIGHLIGHT_KEY),
            differentiateParens: readBool(EX_PARENS_KEY)
        };
        window.dispatchEvent(new CustomEvent('logicExerciseSettingsChanged', { detail: detail }));
    }

    if (document.querySelector('.settings-trigger')) return;

    // Costruzione del modal impostazioni.
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = 'settings-trigger';
    trigger.className = 'btn-wide settings-trigger';
    trigger.setAttribute('aria-label', 'Apri impostazioni');
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', 'settings-overlay');
    trigger.textContent = '⚙';

    const overlay = document.createElement('div');
    overlay.id = 'settings-overlay';
    overlay.className = 'settings-overlay';
    overlay.hidden = true;

    const modal = document.createElement('div');
    modal.id = 'settings-modal';
    modal.className = 'settings-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'settings-title');
    modal.setAttribute('aria-describedby', 'settings-description');

    const title = document.createElement('h2');
    title.id = 'settings-title';
    title.textContent = 'Impostazioni globali';

    const description = document.createElement('p');
    description.id = 'settings-description';
    description.className = 'sr-only';
    description.textContent = 'Pannello impostazioni globali del sito e opzioni di accessibilita.';

    const globalTitle = document.createElement('h3');
    globalTitle.textContent = 'Opzioni globali:';

    const exercisesTitle = document.createElement('h3');
    exercisesTitle.textContent = 'Opzioni esercitazione:';

    const privacyTitle = document.createElement('h3');
    privacyTitle.textContent = 'Dati e privacy:';

    const fontRow = document.createElement('div');
    fontRow.className = 'settings-row';

    const fontLabel = document.createElement('label');
    fontLabel.textContent = 'Dimensione font:';
    fontLabel.setAttribute('for', 'fontScaleInput');

    const input = document.createElement('input');
    input.id = 'fontScaleInput';
    input.type = 'text';
    input.className = 'settings-input';
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('aria-label', 'Dimensione font in pixel');
    input.value = String(initialFontPx);

    const valueLabel = document.createElement('span');
    valueLabel.textContent = 'px';

    fontRow.appendChild(fontLabel);
    fontRow.appendChild(input);
    fontRow.appendChild(valueLabel);

    const themeRow = document.createElement('div');
    themeRow.className = 'settings-row';

    const themeLabel = document.createElement('label');
    themeLabel.textContent = 'Tema:';
    themeLabel.setAttribute('for', 'themeSelect');

    const themeSelect = document.createElement('select');
    themeSelect.id = 'themeSelect';
    themeSelect.className = 'settings-input';

    const optNight = document.createElement('option');
    optNight.value = 'night';
    optNight.textContent = 'Night';

    const optDay = document.createElement('option');
    optDay.value = 'day';
    optDay.textContent = 'Day';

    themeSelect.appendChild(optNight);
    themeSelect.appendChild(optDay);
    themeSelect.value = savedTheme;

    themeRow.appendChild(themeLabel);
    themeRow.appendChild(themeSelect);

    const daltonismRow = document.createElement('div');
    daltonismRow.className = 'settings-row';

    const daltonismLabel = document.createElement('label');
    daltonismLabel.textContent = 'Daltonismo:';
    daltonismLabel.setAttribute('for', 'daltonismSelect');

    const daltonismSelect = document.createElement('select');
    daltonismSelect.id = 'daltonismSelect';
    daltonismSelect.className = 'settings-input settings-input-wide';
    daltonismSelect.setAttribute('aria-describedby', 'daltonism-help');

    const daltonismHelp = document.createElement('p');
    daltonismHelp.id = 'daltonism-help';
    daltonismHelp.className = 'sr-only';
    daltonismHelp.textContent = 'Seleziona una palette alternativa per migliorare la leggibilita dei colori semantici.';

    const optDaltonismNone = document.createElement('option');
    optDaltonismNone.value = 'none';
    optDaltonismNone.textContent = 'Nessuno';

    const optDaltonismProtanopia = document.createElement('option');
    optDaltonismProtanopia.value = 'protanopia';
    optDaltonismProtanopia.textContent = 'Protanopia';

    const optDaltonismDeuteranopia = document.createElement('option');
    optDaltonismDeuteranopia.value = 'deuteranopia';
    optDaltonismDeuteranopia.textContent = 'Deuteranopia';

    const optDaltonismTritanopia = document.createElement('option');
    optDaltonismTritanopia.value = 'tritanopia';
    optDaltonismTritanopia.textContent = 'Tritanopia';

    const optDaltonismAchromatopsia = document.createElement('option');
    optDaltonismAchromatopsia.value = 'achromatopsia';
    optDaltonismAchromatopsia.textContent = 'Acromatopsia';

    daltonismSelect.appendChild(optDaltonismNone);
    daltonismSelect.appendChild(optDaltonismProtanopia);
    daltonismSelect.appendChild(optDaltonismDeuteranopia);
    daltonismSelect.appendChild(optDaltonismTritanopia);
    daltonismSelect.appendChild(optDaltonismAchromatopsia);
    daltonismSelect.value = savedDaltonism;

    daltonismRow.appendChild(daltonismLabel);
    daltonismRow.appendChild(daltonismSelect);

    const exercisesRow1 = document.createElement('div');
    exercisesRow1.className = 'settings-row';

    const highlightLabel = document.createElement('label');
    highlightLabel.textContent = 'Evidenzia atomi';
    highlightLabel.setAttribute('for', 'settingsHighlightAtoms');

    const highlightInput = document.createElement('input');
    highlightInput.id = 'settingsHighlightAtoms';
    highlightInput.type = 'checkbox';
    highlightInput.checked = readBool(EX_HIGHLIGHT_KEY);

    exercisesRow1.appendChild(highlightInput);
    exercisesRow1.appendChild(highlightLabel);

    const exercisesRow2 = document.createElement('div');
    exercisesRow2.className = 'settings-row';

    const parensLabel = document.createElement('label');
    parensLabel.textContent = 'Differenzia parentesi';
    parensLabel.setAttribute('for', 'settingsDifferentiateParens');

    const parensInput = document.createElement('input');
    parensInput.id = 'settingsDifferentiateParens';
    parensInput.type = 'checkbox';
    parensInput.checked = readBool(EX_PARENS_KEY);

    exercisesRow2.appendChild(parensInput);
    exercisesRow2.appendChild(parensLabel);

    const privacyValues = privacy ? privacy.read() : { localData: false, anonymousFeedback: false, includeDemographics: false };
    const localDataRow = document.createElement('div');
    localDataRow.className = 'settings-row';
    const localDataInput = document.createElement('input');
    localDataInput.id = 'settingsLocalData';
    localDataInput.type = 'checkbox';
    localDataInput.checked = privacyValues.localData;
    const localDataLabel = document.createElement('label');
    localDataLabel.setAttribute('for', localDataInput.id);
    localDataLabel.textContent = 'Salva localmente sessioni e progressi';
    localDataRow.appendChild(localDataInput);
    localDataRow.appendChild(localDataLabel);

    const feedbackDataRow = document.createElement('div');
    feedbackDataRow.className = 'settings-row';
    const feedbackDataInput = document.createElement('input');
    feedbackDataInput.id = 'settingsAnonymousFeedback';
    feedbackDataInput.type = 'checkbox';
    feedbackDataInput.checked = privacyValues.anonymousFeedback;
    const feedbackDataLabel = document.createElement('label');
    feedbackDataLabel.setAttribute('for', feedbackDataInput.id);
    feedbackDataLabel.textContent = 'Consenti invio feedback senza nome o account';
    feedbackDataRow.appendChild(feedbackDataInput);
    feedbackDataRow.appendChild(feedbackDataLabel);

    const demographicsRow = document.createElement('div');
    demographicsRow.className = 'settings-row';
    const demographicsInput = document.createElement('input');
    demographicsInput.id = 'settingsIncludeDemographics';
    demographicsInput.type = 'checkbox';
    demographicsInput.checked = privacyValues.includeDemographics;
    demographicsInput.disabled = !privacyValues.anonymousFeedback;
    const demographicsLabel = document.createElement('label');
    demographicsLabel.setAttribute('for', demographicsInput.id);
    demographicsLabel.textContent = 'Includi dati demografici nel feedback';
    demographicsRow.appendChild(demographicsInput);
    demographicsRow.appendChild(demographicsLabel);

    const privacyHelp = document.createElement('p');
    privacyHelp.className = 'settings-help';
    privacyHelp.textContent = 'I dati locali restano in questo browser. Nessun feedback viene inviato senza consenso.';
    const privacyInfoLink = document.createElement('a');
    const settingsScript = document.querySelector('script[src*="settings.js"]');
    privacyInfoLink.href = settingsScript ? new URL('../privacy.html', settingsScript.src).href : 'privacy.html';
    privacyInfoLink.textContent = ' Leggi l’informativa completa.';
    privacyHelp.appendChild(privacyInfoLink);

    const privacyActions = document.createElement('div');
    privacyActions.className = 'settings-actions settings-privacy-actions';
    const exportDataButton = document.createElement('button');
    exportDataButton.type = 'button';
    exportDataButton.className = 'btn-wide';
    exportDataButton.textContent = 'Esporta dati';
    const deleteSessionsButton = document.createElement('button');
    deleteSessionsButton.type = 'button';
    deleteSessionsButton.className = 'btn-wide';
    deleteSessionsButton.textContent = 'Elimina sessioni';
    const deleteProgressButton = document.createElement('button');
    deleteProgressButton.type = 'button';
    deleteProgressButton.className = 'btn-wide';
    deleteProgressButton.textContent = 'Elimina progressi';
    const deleteDataButton = document.createElement('button');
    deleteDataButton.type = 'button';
    deleteDataButton.className = 'btn-wide';
    deleteDataButton.textContent = 'Elimina dati locali';
    const privacyStatus = document.createElement('p');
    privacyStatus.className = 'settings-help';
    privacyStatus.setAttribute('aria-live', 'polite');
    privacyActions.appendChild(exportDataButton);
    privacyActions.appendChild(deleteSessionsButton);
    privacyActions.appendChild(deleteProgressButton);
    privacyActions.appendChild(deleteDataButton);

    const actions = document.createElement('div');
    actions.className = 'settings-actions';

    const resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'btn-wide';
    resetButton.textContent = 'Reset';

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-wide';
    closeButton.textContent = 'Chiudi';

    actions.appendChild(resetButton);
    actions.appendChild(closeButton);

    modal.appendChild(title);
    modal.appendChild(description);
    modal.appendChild(globalTitle);
    modal.appendChild(fontRow);
    modal.appendChild(themeRow);
    modal.appendChild(daltonismRow);
    modal.appendChild(daltonismHelp);
    modal.appendChild(exercisesTitle);
    modal.appendChild(exercisesRow1);
    modal.appendChild(exercisesRow2);
    modal.appendChild(privacyTitle);
    modal.appendChild(localDataRow);
    modal.appendChild(feedbackDataRow);
    modal.appendChild(demographicsRow);
    modal.appendChild(privacyHelp);
    modal.appendChild(privacyActions);
    modal.appendChild(privacyStatus);
    modal.appendChild(actions);
    overlay.appendChild(modal);

    document.body.appendChild(trigger);
    document.body.appendChild(overlay);

    let lastFocusedElement = null;

    /**
     * Elenca gli elementi focusabili del modal attualmente visibili.
     * @pre modal e un elemento dialog valido nel DOM.
     * @post Restituisce un array ordinato di nodi focusabili non nascosti.
     */
    function getFocusableElements() {
        return Array.from(modal.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(function(el) {
            return !el.hasAttribute('hidden') && el.offsetParent !== null;
        });
    }

    // Apertura/chiusura dialog con gestione focus.
    /**
     * Apre il modal impostazioni e sposta il focus all'interno.
     * @pre overlay/modal sono gia montati nel DOM.
     * @post overlay.hidden = false e aria-expanded del trigger e impostato a true.
     */
    function openSettings() {
        lastFocusedElement = document.activeElement;
        overlay.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        const focusables = getFocusableElements();
        if (focusables.length > 0) {
            focusables[0].focus();
        } else {
            modal.focus();
        }
    }

    /**
     * Chiude il modal impostazioni e ripristina il focus precedente.
     * @pre overlay e trigger esistono nel DOM.
     * @post overlay.hidden = true e il focus torna all'elemento precedente o al trigger.
     */
    function closeSettings() {
        overlay.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
            lastFocusedElement.focus();
        } else {
            trigger.focus();
        }
    }

    trigger.addEventListener('click', openSettings);
    closeButton.addEventListener('click', closeSettings);

    overlay.addEventListener('click', function(evt) {
        if (evt.target === overlay) {
            closeSettings();
        }
    });

    document.addEventListener('keydown', function(evt) {
        if (overlay.hidden) return;
        if (evt.key === 'Escape' && !overlay.hidden) {
            closeSettings();
            return;
        }
        if (evt.key === 'Tab') {
            const focusables = getFocusableElements();
            if (focusables.length === 0) {
                evt.preventDefault();
                return;
            }

            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            const active = document.activeElement;

            if (evt.shiftKey && active === first) {
                evt.preventDefault();
                last.focus();
                return;
            }
            if (!evt.shiftKey && active === last) {
                evt.preventDefault();
                first.focus();
            }
        }
    });

    // Valida e persiste il valore di dimensione font.
    /**
     * Valida l'input font, applica il valore e lo persiste.
     * @pre input contiene il testo inserito dall'utente.
     * @post Il font globale e aggiornato oppure l'input viene riportato al valore corrente valido.
     */
    function commitFontValue() {
        const parsedPx = parsePxValue(input.value);
        if (parsedPx === null) {
            input.value = String(currentFontPx);
            return;
        }

        const next = applyFontPx(parsedPx);
        currentFontPx = next;
        input.value = String(next);
        localStorage.setItem(FONT_KEY, String(next));
    }

    input.addEventListener('change', commitFontValue);
    input.addEventListener('keydown', function(evt) {
        if (evt.key === 'Enter') {
            evt.preventDefault();
            commitFontValue();
        }
    });

    resetButton.addEventListener('click', function() {
        const next = applyFontPx(DEFAULT_FONT_PX);
        currentFontPx = next;
        input.value = String(next);
        localStorage.setItem(FONT_KEY, String(next));
        applyTheme('night');
        themeSelect.value = 'night';
        localStorage.setItem(THEME_KEY, 'night');
        applyDaltonism('none');
        daltonismSelect.value = 'none';
        localStorage.setItem(DALTONISM_KEY, 'none');
    });

    highlightInput.addEventListener('change', function() {
        writeBool(EX_HIGHLIGHT_KEY, Boolean(highlightInput.checked));
        publishExerciseSettings();
    });

    parensInput.addEventListener('change', function() {
        writeBool(EX_PARENS_KEY, Boolean(parensInput.checked));
        publishExerciseSettings();
    });

    localDataInput.addEventListener('change', function() {
        if (privacy) privacy.update({ localData: localDataInput.checked });
        privacyStatus.textContent = localDataInput.checked
            ? 'Salvataggio locale attivato.'
            : 'Salvataggio locale disattivato. I dati esistenti non sono stati eliminati.';
    });

    feedbackDataInput.addEventListener('change', function() {
        demographicsInput.disabled = !feedbackDataInput.checked;
        if (!feedbackDataInput.checked) {
            demographicsInput.checked = false;
            clearLegacyDemographics();
        }
        if (privacy) {
            privacy.update({
                anonymousFeedback: feedbackDataInput.checked,
                includeDemographics: demographicsInput.checked
            });
        }
        privacyStatus.textContent = feedbackDataInput.checked
            ? 'Invio feedback senza nome o account consentito.'
            : 'Invio feedback disattivato.';
    });

    demographicsInput.addEventListener('change', function() {
        if (!demographicsInput.checked) clearLegacyDemographics();
        if (privacy) privacy.update({ includeDemographics: demographicsInput.checked });
        privacyStatus.textContent = demographicsInput.checked
            ? 'I dati demografici saranno inclusi nel feedback.'
            : 'I dati demografici saranno esclusi dal feedback.';
    });

    exportDataButton.addEventListener('click', async function() {
        if (!appStorage) {
            privacyStatus.textContent = 'Archivio locale non disponibile.';
            return;
        }
        const records = await appStorage.exportAll();
        const blob = new Blob([JSON.stringify({ version: 1, exportedAt: Date.now(), records: records }, null, 2)], {
            type: 'application/json'
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'testlogica-dati.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        privacyStatus.textContent = 'Dati esportati.';
    });

    deleteDataButton.addEventListener('click', async function() {
        if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:data-clearing');
        try {
            clearLegacyDemographics();
            if (appStorage) await appStorage.clearAll();
            privacyStatus.textContent = 'Sessioni, progressi e dati demografici locali eliminati.';
        } catch (error) {
            privacyStatus.textContent = 'Non è stato possibile eliminare tutti i dati locali. Riprova.';
            if (window.LogicLogger) window.LogicLogger.error('Cancellazione dati locali fallita:', error);
        } finally {
            if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:data-cleared');
        }
    });

    deleteSessionsButton.addEventListener('click', async function() {
        if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:sessions-clearing');
        try {
            if (appStorage) {
                await appStorage.clearType('sessions');
                await appStorage.clearType('sessionHistory');
            }
            privacyStatus.textContent = 'Sessioni attive e concluse eliminate.';
        } catch (error) {
            privacyStatus.textContent = 'Non è stato possibile eliminare tutte le sessioni locali. Riprova.';
            if (window.LogicLogger) window.LogicLogger.error('Cancellazione sessioni locali fallita:', error);
        } finally {
            if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:sessions-cleared');
        }
    });

    deleteProgressButton.addEventListener('click', async function() {
        if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:progress-clearing');
        try {
            if (appStorage) {
                await appStorage.clearType('attempts');
                await appStorage.clearType('errors');
                await appStorage.clearType('lessonProgress');
            }
            privacyStatus.textContent = 'Tentativi, errori e progresso delle lezioni eliminati.';
        } catch (error) {
            privacyStatus.textContent = 'Non è stato possibile eliminare tutti i progressi locali. Riprova.';
            if (window.LogicLogger) window.LogicLogger.error('Cancellazione progressi locali fallita:', error);
        } finally {
            if (window.LogicAppEvents) window.LogicAppEvents.emit('privacy:progress-cleared');
        }
    });

    themeSelect.addEventListener('change', function() {
        const mode = themeSelect.value;
        applyTheme(mode);
        localStorage.setItem(THEME_KEY, mode);
    });

    daltonismSelect.addEventListener('change', function() {
        const mode = applyDaltonism(daltonismSelect.value);
        localStorage.setItem(DALTONISM_KEY, mode);
    });

    publishExerciseSettings();
}
