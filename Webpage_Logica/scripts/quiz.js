/*
 * Motore principale del quiz equivalente/verita/negazione quantificatori.
 * Gestisce caricamento esercizi da API, rendering opzioni, verifica risposte,
 * timer, recap finale e modalita di visualizzazione/accessibilita.
 */

/**
 * Inizializza il quiz nel contenitore indicato.
 * @pre rootId punta a un elemento DOM esistente con la struttura attesa del quiz.
 * @post Event listener e stato interno vengono inizializzati; il quiz entra in intro o in caricamento diretto.
 */
function initEquivalentQuiz(rootId) {
    const logger = window.LogicLogger;
        /**
         * Restituisce le opzioni attive (testi) mostrate all'utente per le domande.
         * @returns {string[]} Array dei testi delle opzioni attuali.
         */
        function getActiveOptions() { 
            const showFormulas = document.getElementById('quizShowFormulas')?.checked || false;
            const colorAtoms = document.getElementById('quizColorAtoms')?.checked || false;
            const spokenLanguage = document.getElementById('quizSpokenLanguage')?.checked || false;
            const showWrongActionImages = document.getElementById('quizShowWrongActionImages')?.checked || false;
            return {
                showFormulas,
                colorAtoms,
                spokenLanguage,
                showWrongActionImages
            };
        }
        const root = document.getElementById(rootId);
    if (!root) return;

    const EX_HIGHLIGHT_KEY = 'logic-exercises-highlight-atoms';
    const EX_PARENS_KEY = 'logic-exercises-differentiate-parens';
    const isExercisesPage = /\/esercizi\//.test(window.location.pathname);

    function readExerciseSetting(key) {
        return localStorage.getItem(key) === '1';
    }

    // Crea/recupera il display timer condiviso fissato a viewport.
    function ensureTimerDisplay() {
        let el = document.getElementById('quizTimerDisplay');
        if (el) return el;

        el = document.createElement('div');
        el.id = 'quizTimerDisplay';
        el.className = 'quiz-timer';
        el.setAttribute('role', 'timer');
        el.setAttribute('aria-label', 'Tempo rimanente');
        el.setAttribute('aria-live', 'off');
        el.hidden = true;
        el.textContent = '20:00';
        document.body.appendChild(el);
        return el;
    }

    const introEl = root.querySelector('#quizIntro');
    const startButton = root.querySelector('#quizStartButton');
    const questionCountInput = root.querySelector('#quizQuestionCount');
    const questionMaximumEl = root.querySelector('#quizQuestionMaximum');
    const timeMinutesInput = root.querySelector('#quizTimeMinutes');
    const showFormulasInput = root.querySelector('#quizShowFormulas');
    const colorAtomsInput = root.querySelector('#quizColorAtoms');
    const spokenLanguageInput = root.querySelector('#quizSpokenLanguage');
    const showWrongActionImagesInput = root.querySelector('#quizShowWrongActionImages');
    const presetSelect = root.querySelector('#quizPreset');
    const modeSelect = root.querySelector('#quizMode');
    const difficultySelect = root.querySelector('#quizDifficulty');
    const adaptiveInput = root.querySelector('#quizAdaptive');
    const showConstructionInput = root.querySelector('#quizShowConstruction');
    const adaptiveNoticeEl = root.querySelector('#quizAdaptiveNotice');
    const resumePanelEl = root.querySelector('#quizResumePanel');
    const resumeSummaryEl = root.querySelector('#quizResumeSummary');
    const resumeButton = root.querySelector('#quizResumeButton');
    const discardSessionButton = root.querySelector('#quizDiscardSessionButton');
    const logDataAgeInput = root.querySelector('#quizLogDataAge');
    const logDataInstitutionSelect = root.querySelector('#quizLogDataInstitution');
    const logDataStemRow = root.querySelector('#quizLogDataStemRow');
    const logDataStemSelect = root.querySelector('#quizLogDataStem');
    const logDataSection = root.querySelector('#quizLogDataSection');
    const testEl = root.querySelector('#quizTest');
    const splitLayoutEl = document.getElementById('quizTestLayout') || root.querySelector('#quizTestLayout');
    const formulasPaneEl = document.getElementById('quizFormulasPane') || root.querySelector('#quizFormulasPane');
    const reviewEl = root.querySelector('#quizReview');
    const reviewListEl = root.querySelector('#quizReviewList');
    const reviewTitleEl = document.getElementById('quizReviewTitle') || root.querySelector('#quizReviewTitle');
    const reviewNavEl = document.getElementById('quizReviewNav') || root.querySelector('#quizReviewNav');
    const reviewRestartButton = document.getElementById('quizReviewRestart') || root.querySelector('#quizReviewRestart');
    const introTitleEl = document.getElementById('quizIntroTitle') || root.querySelector('#quizIntroTitle');
    const indexNavEl = document.getElementById('quizIndexNav') || root.querySelector('#quizIndexNav');
    const testTitleEl = document.getElementById('quizTestTitle') || root.querySelector('#quizTestTitle');
    const timerDisplayEl = ensureTimerDisplay();
    const questionEl = root.querySelector('#quizQuestion');
    const infoEl = root.querySelector('#quizInfo');
    const optionsEl = root.querySelector('#quizOptions');
    const actionButton = root.querySelector('#quizActionButton');
    const statusEl = root.querySelector('#quizStatus');
    const formulaTransformationEl = root.querySelector('#quizFormulaTransformation');
    const wrongActionImagesEl = root.querySelector('#quizWrongActionImages');
    const exportJsonButton = document.getElementById('quizExportJson');
    const exportCsvButton = document.getElementById('quizExportCsv');
    const printResultsButton = document.getElementById('quizPrintResults');

    if (!questionEl || !infoEl || !optionsEl || !actionButton || !statusEl) return;

    const DEFAULT_EXERCISES = 10;
    const DEFAULT_TIME_MINUTES = 20;
    const MAX_QUIZ_QUESTIONS = window.LogicDataContracts.MAX_QUIZ_QUESTIONS;
    const DEFAULT_BATCH_SIZE = 50;
    const BATCH_REQUEST_TIMEOUT_MS = 120000;
    let currentExercise = 0;
    let totalExercises = DEFAULT_EXERCISES;
    let standardTimeMinutes = DEFAULT_TIME_MINUTES;
    const reviewResults = [];
    let currentQuestionInfo = [];
    let currentTruthAssignments = {};
    let atomSpokenMap = {};
    let currentSpokenNameColors = {};
    let currentQuestionText = '';
    let currentQuestionId = '';
    let currentImageFormulaSteps = { question: [], correct: [], wrongByFormula: {} };
    let quantifierNegationTarget = 0;
    let quantifierNegationUsed = 0;
    var quizStartTimestamp = Date.now();
    var questionViewTimestamps = [];
    // Batch loading state
    let batchQuestionsCache = [];
    let batchCacheIndex = 0;
    let batchInitialized = false;
    let batchOperationsPlan = [];
    const FEEDBACK_FIELDS = window.LogicQuizFeedback.FIELDS;
    let feedbackValues = createEmptyFeedbackValues();
    let currentQuizConfig = window.LogicDataContracts.normalizeQuizConfig({});
    let activeSession = null;
    let resumeSelectedIndex = null;
    const recordedAttempts = [];
    let adaptiveMessage = '';
    let quizMaximumQuestions = MAX_QUIZ_QUESTIONS;
    let quizBatchSize = DEFAULT_BATCH_SIZE;
    const sessionManager = window.LogicQuizSession.create({ storage: window.LogicAppStorage.instance });
    const errorNotebook = window.LogicErrorNotebook.create({ storage: window.LogicAppStorage.instance });
    const reviewSubmissionState = window.LogicQuizFeedback.createSubmission({
        postJson: window.LogicApi.postJson
    });

    /**
     * Legge i dati demografici direttamente dai controlli correnti del form.
     * @returns {Object} Oggetto con age, institution e stem, se consentiti.
     */
    function getLogDataSettings() {
        if (!window.LogicPrivacy.includeDemographics()) return {};
        return window.LogicQuizReport.readDemographics({
            age: logDataAgeInput,
            institution: logDataInstitutionSelect,
            stem: logDataStemRow && logDataStemRow.hidden ? null : logDataStemSelect
        });
    }

    function isLogDataStemRequired(institutionValue) {
        return window.LogicQuizReport.isStemRequired(institutionValue);
    }

    function syncLogDataStemVisibility() {
        if (!logDataInstitutionSelect || !logDataStemRow || !logDataStemSelect) return;
        const required = isLogDataStemRequired(logDataInstitutionSelect.value);
        logDataStemRow.hidden = !required;
        if (!required) {
            logDataStemSelect.value = '';
        }
    }

    function syncLogDataSettings() {
        if (logDataAgeInput) {
            const rawAge = String(logDataAgeInput.value || '').trim();
            if (rawAge !== '' && window.LogicQuizFeedback.isOptionalAgeValid(rawAge, logDataAgeInput.validity)) {
                logDataAgeInput.value = String(Number(rawAge));
            }
            if (rawAge === '' || window.LogicQuizFeedback.isOptionalAgeValid(rawAge, logDataAgeInput.validity)) {
                logDataAgeInput.removeAttribute('aria-invalid');
            }
        }

        if (logDataInstitutionSelect) {
            syncLogDataStemVisibility();
        }
    }

    function createEmptyFeedbackValues() {
        return window.LogicQuizReport.emptyFeedback();
    }

    function isFeedbackComplete() {
        return window.LogicQuizFeedback.isComplete(feedbackValues);
    }

    function buildReviewReport(feedbackMap) {
        return window.LogicQuizReport.buildReport({
            demographics: getLogDataSettings(),
            feedback: feedbackMap,
            feedbackFields: FEEDBACK_FIELDS,
            results: reviewResults,
            startedAt: quizStartTimestamp
        });
    }

    function submitReviewReport(report) {
        if (!window.LogicPrivacy.canSendFeedback()) return Promise.resolve(false);
        return reviewSubmissionState.submit(report);
    }

    function updateFeedbackFormState(statusNode, submitButton) {
        if (reviewSubmissionState.sent) return;
        const complete = isFeedbackComplete();
        submitButton.disabled = !complete || reviewSubmissionState.inFlight;
        if (!reviewSubmissionState.inFlight) {
            statusNode.textContent = complete
                ? 'La valutazione è pronta per essere inviata.'
                : 'Per inviare la valutazione, assegna un punteggio da 1 a 5 a tutte le affermazioni. Puoi anche saltarla.';
            statusNode.className = 'quiz-feedback-status';
        }
    }

    function validateOptionalDemographics(statusNode) {
        if (!window.LogicPrivacy.includeDemographics() || !logDataAgeInput) return true;
        const ageValue = String(logDataAgeInput.value || '').trim();
        if (window.LogicQuizFeedback.isOptionalAgeValid(ageValue, logDataAgeInput.validity)) {
            logDataAgeInput.removeAttribute('aria-invalid');
            return true;
        }

        logDataAgeInput.setAttribute('aria-invalid', 'true');
        statusNode.textContent = 'Inserisci un\'età intera da 1 a 199 oppure lascia vuoto il campo. Puoi comunque saltare la valutazione.';
        statusNode.className = 'quiz-feedback-status quiz-review-answer is-wrong';
        logDataAgeInput.focus();
        return false;
    }

    function submitFeedbackFromForm(statusNode, submitButton, skipButton, radioNodes) {
        if (reviewSubmissionState.sent || reviewSubmissionState.inFlight) return;
        if (!isFeedbackComplete()) {
            updateFeedbackFormState(statusNode, submitButton);
            return;
        }
        if (!validateOptionalDemographics(statusNode)) return;

        statusNode.textContent = 'Invio della valutazione in corso…';
        statusNode.className = 'quiz-feedback-status';
        submitButton.disabled = true;
        radioNodes.forEach(function(radio) {
            radio.disabled = true;
        });

        submitReviewReport(buildReviewReport(feedbackValues)).then(function(ok) {
            if (!ok) {
                statusNode.textContent = 'Invio non riuscito. Puoi riprovare oppure saltare la valutazione e vedere subito i risultati.';
                statusNode.className = 'quiz-feedback-status quiz-review-answer is-wrong';
                submitButton.textContent = 'Riprova l\'invio e mostra i risultati';
                submitButton.disabled = false;
                radioNodes.forEach(function(radio) {
                    radio.disabled = false;
                });
                submitButton.focus();
                return;
            }
            statusNode.textContent = 'Valutazione inviata correttamente. Apertura dei risultati…';
            statusNode.className = 'quiz-feedback-status quiz-review-answer is-correct';
            submitButton.textContent = 'Valutazione inviata';
            skipButton.disabled = true;
            setTimeout(function() {
                showReviewPage();
            }, 250);
        });
    }

    function parkLogDataSection() {
        if (logDataSection && reviewEl && logDataSection.parentNode === reviewListEl) {
            reviewEl.insertBefore(logDataSection, reviewListEl);
        }
    }

    function renderFeedbackPage() {
        if (!reviewListEl) return;
        parkLogDataSection();
        reviewListEl.innerHTML = '';
        reviewListEl.classList.add('quiz-feedback-panel');

        const transmissionSummary = document.createElement('p');
        transmissionSummary.className = 'quiz-feedback-intro';
        transmissionSummary.textContent = 'La valutazione è facoltativa. Se scegli di inviarla, saranno trasmessi i punteggi da 1 a 5 e i risultati del quiz. I dati demografici sono '
            + (window.LogicPrivacy.includeDemographics() ? 'inclusi, ma tutti i campi restano facoltativi' : 'esclusi') + '.';
        reviewListEl.appendChild(transmissionSummary);

        const applicabilityNote = document.createElement('p');
        applicabilityNote.className = 'quiz-feedback-note';
        applicabilityNote.textContent = 'Se non hai usato gli ausili o le lezioni, oppure non vuoi rispondere, puoi saltare l\'intera valutazione senza perdere i risultati.';
        reviewListEl.appendChild(applicabilityNote);

        const radioNodes = [];
        FEEDBACK_FIELDS.forEach(function(field) {
            const row = document.createElement('fieldset');
            row.className = 'quiz-feedback-row';

            const rowLabel = document.createElement('legend');
            rowLabel.className = 'quiz-feedback-question';
            rowLabel.textContent = field.label;
            row.appendChild(rowLabel);

            const descriptionId = 'feedback-scale-' + field.id;
            const describedBy = [descriptionId];
            if (field.hint) {
                const hint = document.createElement('p');
                hint.id = 'feedback-hint-' + field.id;
                hint.className = 'quiz-feedback-question-hint';
                hint.textContent = field.hint;
                row.appendChild(hint);
                describedBy.unshift(hint.id);
            }

            const radioGroup = document.createElement('div');
            radioGroup.className = 'quiz-feedback-radio-group';

            for (let value = 1; value <= 5; value += 1) {
                const choice = document.createElement('label');
                choice.className = 'quiz-feedback-radio-choice';

                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = 'feedback-' + field.id;
                radio.value = String(value);
                radio.setAttribute('aria-label', field.label + ' ' + String(value));
                radio.setAttribute('aria-describedby', describedBy.join(' '));
                if (String(feedbackValues[field.id] || '') === String(value)) {
                    radio.checked = true;
                }
                radio.addEventListener('change', function() {
                    if (!radio.checked) return;
                    reviewSubmissionState.invalidate();
                    feedbackValues[field.id] = String(radio.value || '');
                    submitButton.textContent = 'Invia la valutazione e mostra i risultati';
                    updateFeedbackFormState(statusLine, submitButton);
                });

                const valueText = document.createElement('span');
                valueText.textContent = String(value);

                choice.appendChild(radio);
                choice.appendChild(valueText);
                radioGroup.appendChild(choice);
                radioNodes.push(radio);
            }

            row.appendChild(radioGroup);

            const endpoints = document.createElement('div');
            endpoints.id = descriptionId;
            endpoints.className = 'quiz-feedback-endpoints';
            const left = document.createElement('span');
            left.textContent = '1 Per niente d\'accordo';
            const right = document.createElement('span');
            right.textContent = '5 Totalmente d\'accordo';
            endpoints.appendChild(left);
            endpoints.appendChild(right);
            row.appendChild(endpoints);

            reviewListEl.appendChild(row);
        });

        if (logDataSection) {
            logDataSection.hidden = !window.LogicPrivacy.includeDemographics();
            reviewListEl.appendChild(logDataSection);
        }

        const statusLine = document.createElement('p');
        statusLine.className = 'quiz-feedback-status';
        statusLine.setAttribute('role', 'status');
        statusLine.setAttribute('aria-live', 'polite');
        statusLine.setAttribute('aria-atomic', 'true');
        reviewListEl.appendChild(statusLine);

        const actions = document.createElement('div');
        actions.className = 'quiz-feedback-actions';

        const submitButton = document.createElement('button');
        submitButton.type = 'button';
        submitButton.className = 'btn-wide quiz-feedback-submit';
        submitButton.textContent = 'Invia la valutazione e mostra i risultati';
        submitButton.disabled = true;
        submitButton.addEventListener('click', function() {
            submitFeedbackFromForm(statusLine, submitButton, skipButton, radioNodes);
        });

        const skipButton = document.createElement('button');
        skipButton.type = 'button';
        skipButton.className = 'btn-wide quiz-feedback-skip';
        skipButton.textContent = 'Salta e mostra i risultati';
        skipButton.addEventListener('click', function() {
            showReviewPage();
        });

        actions.appendChild(submitButton);
        actions.appendChild(skipButton);
        reviewListEl.appendChild(actions);

        updateFeedbackFormState(statusLine, submitButton);
    }

    function appendReviewSummary() {
        const total = reviewResults.length;
        const correct = reviewResults.filter(function(entry) { return entry.isCorrect; }).length;
        const percentage = total > 0 ? Math.round((correct / total) * 100) : 0;
        const summary = document.createElement('section');
        summary.className = 'quiz-review-summary';
        summary.setAttribute('aria-label', 'Risultato complessivo');

        const score = document.createElement('div');
        score.className = 'quiz-review-score';
        score.textContent = String(percentage) + '%';
        score.setAttribute('aria-hidden', 'true');

        const copy = document.createElement('div');
        const title = document.createElement('h2');
        title.textContent = String(correct) + ' risposte corrette su ' + String(total);
        const note = document.createElement('p');
        note.textContent = correct === total && total > 0
            ? 'Ottimo lavoro: hai completato il quiz senza errori.'
            : 'Rivedi le risposte qui sotto e apri i passaggi per capire dove migliorare.';
        copy.appendChild(title);
        copy.appendChild(note);
        summary.appendChild(score);
        summary.appendChild(copy);
        reviewListEl.appendChild(summary);

        const sectionTitle = document.createElement('h2');
        sectionTitle.className = 'quiz-review-section-title';
        sectionTitle.textContent = 'Rivedi le risposte';
        reviewListEl.appendChild(sectionTitle);
    }

    function renderReviewList() {
        if (!reviewListEl) return;
        parkLogDataSection();
        reviewListEl.innerHTML = '';
        reviewListEl.classList.remove('quiz-feedback-panel');
        appendReviewSummary();

        reviewResults.forEach(function(entry) {
            const item = document.createElement('article');
            item.className = 'quiz-review-item ' + (entry.isCorrect ? 'is-correct' : 'is-wrong');

            const title = document.createElement('h3');
            title.className = 'quiz-review-title';
            const titleText = document.createElement('span');
            titleText.textContent = 'Domanda ' + String(entry.number);
            const resultBadge = document.createElement('span');
            resultBadge.className = 'quiz-review-badge';
            resultBadge.textContent = entry.isCorrect ? 'Corretta' : 'Da rivedere';
            title.appendChild(titleText);
            title.appendChild(resultBadge);

            const questionLine = document.createElement('p');
            questionLine.className = 'quiz-review-line quiz-review-question';
            questionLine.textContent = entry.question;

            let infoBlock = null;
            if (Array.isArray(entry.infoLines) && entry.infoLines.length > 0) {
                infoBlock = document.createElement('div');
                infoBlock.className = 'quiz-review-hypotheses';

                const infoTitle = document.createElement('p');
                infoTitle.className = 'quiz-review-line';
                infoTitle.textContent = 'Ipotesi:';

                const infoList = document.createElement('ul');
                entry.infoLines.forEach(function(line) {
                    const li = document.createElement('li');
                    li.textContent = line;
                    infoList.appendChild(li);
                });

                infoBlock.appendChild(infoTitle);
                infoBlock.appendChild(infoList);
            }

            const userLine = document.createElement('p');
            userLine.className = 'quiz-review-line quiz-review-answer-row';
            const userLabel = document.createElement('span');
            userLabel.className = 'quiz-review-answer-label';
            userLabel.textContent = 'La tua risposta';
            userLine.appendChild(userLabel);

            const userAnswer = document.createElement('span');
            userAnswer.className = 'quiz-review-answer ' + (entry.isCorrect ? 'is-correct' : 'is-wrong');
            userAnswer.textContent = entry.selectedAnswer;
            userLine.appendChild(userAnswer);

            const correctLine = document.createElement('p');
            correctLine.className = 'quiz-review-line quiz-review-answer-row';
            const correctLabel = document.createElement('span');
            correctLabel.className = 'quiz-review-answer-label';
            correctLabel.textContent = 'Risposta corretta';
            const correctAnswer = document.createElement('span');
            correctAnswer.textContent = entry.correctAnswer;
            correctLine.appendChild(correctLabel);
            correctLine.appendChild(correctAnswer);

            item.appendChild(title);
            item.appendChild(questionLine);
            if (infoBlock) item.appendChild(infoBlock);
            item.appendChild(userLine);
            item.appendChild(correctLine);
            if (entry.transformationCorrect || entry.transformationSelected) {
                const transformationBlock = document.createElement('div');
                transformationBlock.className = 'formula-transformation';
                item.appendChild(transformationBlock);
                window.LogicFormulaTransformationRenderer.create({
                    container: transformationBlock,
                    formatFormula: function(formula) {
                        return prologToLogical(String(formula || '')) || String(formula || '');
                    }
                }).show({
                    correct: entry.transformationCorrect,
                    selected: entry.transformationSelected,
                    selectedIsCorrect: entry.isCorrect
                });
            }
            if (entry.constructionCorrect) {
                const treeDetails = document.createElement('details');
                const treeSummary = document.createElement('summary');
                treeSummary.textContent = 'Mostra albero della formula';
                const treeContainer = document.createElement('div');
                treeContainer.className = 'sandbox-tree';
                const treeDetail = document.createElement('p');
                treeDetail.className = 'sandbox-tree-detail';
                treeDetail.setAttribute('aria-live', 'polite');
                treeDetails.appendChild(treeSummary);
                treeDetails.appendChild(treeContainer);
                treeDetails.appendChild(treeDetail);
                treeDetails.addEventListener('toggle', function() {
                    if (treeDetails.open && !treeContainer.firstChild) {
                        window.LogicFormulaTree.render(treeContainer, entry.constructionCorrect, {
                            detailElement: treeDetail,
                            formatFormula: displayFormulaText,
                            fullLabels: true
                        });
                        treeContainer.scrollLeft = Math.max(
                            0,
                            (treeContainer.scrollWidth - treeContainer.clientWidth) / 2
                        );
                        treeContainer.scrollTop = 0;
                    }
                });
                item.appendChild(treeDetails);
            }
            reviewListEl.appendChild(item);
        });
    }

    function showReviewPage() {
        if (logDataSection) logDataSection.hidden = true;
        if (reviewTitleEl) {
            reviewTitleEl.hidden = false;
            reviewTitleEl.textContent = 'Risultati del quiz';
        }
        renderReviewList();
        if (reviewNavEl) reviewNavEl.hidden = false;
        if (indexNavEl) indexNavEl.hidden = true;
        if (reviewTitleEl) {
            reviewTitleEl.setAttribute('tabindex', '-1');
            reviewTitleEl.focus();
        }
    }

    function normalizeApiBase(rawBase) {
        return window.LogicApi.normalizeBase(rawBase);
    }

    function syncPrivacyVisibility() {
        if (!logDataSection) return;
        reviewSubmissionState.invalidate();
        const includeDemographics = window.LogicPrivacy.includeDemographics();
        const onFeedbackPage = reviewListEl && reviewListEl.classList.contains('quiz-feedback-panel');
        if (!includeDemographics) {
            if (logDataAgeInput) {
                logDataAgeInput.value = '';
                logDataAgeInput.removeAttribute('aria-invalid');
            }
            if (logDataInstitutionSelect) logDataInstitutionSelect.value = '';
            if (logDataStemSelect) logDataStemSelect.value = '';
            if (logDataStemRow) logDataStemRow.hidden = true;
        }
        if (onFeedbackPage && !window.LogicPrivacy.canSendFeedback()) {
            showReviewPage();
            return;
        }
        logDataSection.hidden = !includeDemographics || !onFeedbackPage;
    }

    function buildApiUrl(path) {
        return window.LogicApi.buildUrl(path, normalizeApiBase(window.LOGIC_API_BASE_URL));
    }

    const equivalenceApiUrl = buildApiUrl('generator/build-exercise-from-depth');
    const truthApiUrl = buildApiUrl('generator/build-truth-value-options-question');
    const logicalConsequenceApiUrl = buildApiUrl('generator/build-logical-consequence-question');
    const translationApiUrl = buildApiUrl('generator/build-translation-question');
    const formulaByVariableCountApiUrl = buildApiUrl('generator/generate-formula-by-variable-count');

    const NOMI = ['Luca', 'Matteo', 'Alessandro', 'Marco', 'Davide', 'Giulia', 'Sofia', 'Martina', 'Chiara', 'Elisa'];
    const AZIONI = ['nuota', 'corre', 'salta', 'guarda', 'parla', 'apre la porta', 'chiude la porta', 'ascolta'];
    const ACTION_IMAGE_FILES = {
        nuota: { day: 'Nuotare_White.png', night: 'Nuotare_Black.png' },
        corre: { day: 'Correre_White.png', night: 'Correre_Black.png' },
        salta: { day: 'Saltare_White.png', night: 'Saltare_Black.png' },
        guarda: { day: 'Guardare_White.png', night: 'Guardare_Black.png' },
        parla: { day: 'Parlare_White.png', night: 'Parlare_Black.png' },
        apre: { day: 'Aprire_White.png', night: 'Aprire_Black.png' },
        'apre la porta': { day: 'Aprire_White.png', night: 'Aprire_Black.png' },
        chiude: { day: 'Chiudere_White.png', night: 'Chiudere_Black.png' },
        'chiude la porta': { day: 'Chiudere_White.png', night: 'Chiudere_Black.png' },
        ascolta: { day: 'Ascoltare_White.png', night: 'Ascoltare_Black.png' }
    };

    const state = window.LogicQuizState.create({
        isExercisesPage: isExercisesPage,
        highlightKey: EX_HIGHLIGHT_KEY,
        parensKey: EX_PARENS_KEY,
        readSetting: readExerciseSetting
    });

    const quizShared = window.quizShared;
    if (!quizShared) {
        throw new Error('Modulo quiz-shared.js non caricato');
    }
    const differentiateParentheses = quizShared.differentiateParentheses;
    const parsePositiveInt = quizShared.parsePositiveInt;
    const prologToLogical = quizShared.prologToLogical;
    const shuffle = quizShared.shuffle;
    const pickRandom = quizShared.pickRandom;
    const normalizeNameKey = quizShared.normalizeNameKey;
    const isGenericPersonLabel = quizShared.isGenericPersonLabel;
    const quizPayloads = window.LogicQuizPayloads;
    if (!quizPayloads) {
        throw new Error('Modulo quiz-payloads.js non caricato');
    }
    const quizNormalizers = window.LogicQuizNormalizers.create({
        shuffle: shuffle,
        prologToLogical: prologToLogical,
        normalizeGenerationSteps: normalizeGenerationSteps,
        extractWrongStepsMap: extractWrongStepsMap,
        normalizeConstruction: window.LogicFormulaConstruction.normalize,
        buildConstructionFromFormula: window.LogicFormulaConstruction.buildFromFormula,
        buildQuantifiedConstruction: window.LogicFormulaConstruction.buildQuantifiedTrace,
        removeFormulaNegations: quizShared.removeFormulaNegations,
        normalizeTransformation: window.LogicFormulaTransformation.normalize
    });
    const normalizeEquivalenceResult = quizNormalizers.normalizeEquivalenceResult;
    const normalizeTruthValueResult = quizNormalizers.normalizeTruthValueResult;
    const normalizeLogicalConsequenceResult = quizNormalizers.normalizeLogicalConsequenceResult;
    const normalizeTranslationResult = quizNormalizers.normalizeTranslationResult;
    const buildQuantifiedNegationOptions = quizNormalizers.buildQuantifiedNegationOptions;
    const formulaTransformationRenderer = window.LogicFormulaTransformationRenderer.create({
        container: formulaTransformationEl,
        formatFormula: function(formula) {
            return prologToLogical(String(formula || '')) || String(formula || '');
        }
    });
    const hideFormulaTransformation = formulaTransformationRenderer.hide;
    const showFormulaTransformation = formulaTransformationRenderer.show;
    const quizRenderer = window.LogicQuizRenderer.create({
        state: state,
        infoEl: infoEl,
        optionsEl: optionsEl,
        statusEl: statusEl,
        escapeHtml: escapeHtml,
        formatSpokenInfoLine: formatSpokenInfoLine,
        colorizeAtomsInText: colorizeAtomsInText,
        transformFormula: getCachedFormulaTransforms,
        getOptionFormula: getOptionDisplayFormula
    });
    const showInfo = quizRenderer.showInfo;
    const renderQuizOptions = quizRenderer.renderOptions;
    const updateSelectionVisual = quizRenderer.updateSelectionVisual;
    const setStatus = quizRenderer.setStatus;
    const resetVisualFeedback = quizRenderer.resetVisualFeedback;

    function setRenderedOptionsLocked(locked) {
        optionsEl.querySelectorAll('.quiz-option').forEach(function(option) {
            option.disabled = Boolean(locked);
            option.setAttribute('aria-disabled', locked ? 'true' : 'false');
            if (locked) option.tabIndex = -1;
        });
    }

    function renderOptions() {
        renderQuizOptions();
        setRenderedOptionsLocked(state.locked);
    }
    const quizTimer = window.LogicQuizTimer.create({
        display: timerDisplayEl,
        defaultMinutes: DEFAULT_TIME_MINUTES,
        parseMinutes: parsePositiveInt,
        onExpire: function() {
            if (state.mode === 'check' || state.mode === 'next') {
                setStatus('Tempo scaduto.');
                showCompletion();
            }
        }
    });

    function stableQuestionId(kind, question, answer) {
        const text = [kind || 'unknown', question || '', answer || ''].join('|');
        let hash = 2166136261;
        for (let index = 0; index < text.length; index += 1) {
            hash ^= text.charCodeAt(index);
            hash = Math.imul(hash, 16777619);
        }
        return 'question-' + (hash >>> 0).toString(16);
    }

    function persistSession(patch) {
        if (!activeSession) return Promise.resolve(null);
        return sessionManager.update({
            currentIndex: currentExercise,
            remainingSeconds: quizTimer.getRemainingSeconds(),
            operationPlan: batchOperationsPlan,
            questions: batchQuestionsCache,
            answers: reviewResults.slice(),
            ...(patch || {})
        }).then(function(session) {
            activeSession = session;
            window.LogicAppEvents.emit('session:saved', session);
            return session;
        }).catch(function(error) {
            logger.warn('Sessione non salvata:', error && error.message);
            return null;
        });
    }

    function recordLearningAttempt(details) {
        if (!details.scorable) return null;
        const attempt = window.LogicDataContracts.createAttempt({
            sessionId: activeSession ? activeSession.sessionId : '',
            questionId: currentQuestionId || stableQuestionId(state.exerciseKind, details.question, details.correctAnswer),
            type: state.exerciseKind,
            difficulty: currentQuizConfig.difficulty,
            elapsedMs: details.elapsedMs,
            correct: details.correct,
            question: details.question,
            selectedAnswer: details.selectedAnswer,
            correctAnswer: details.correctAnswer
        });
        recordedAttempts.push(attempt);
        window.LogicAppEvents.emit('quiz:answered', attempt);
        window.LogicAppStorage.instance.put('attempts', attempt.attemptId, attempt).catch(function() {});
        errorNotebook.record(attempt, {
            construction: details.construction,
            transformationCorrect: details.transformationCorrect,
            transformationSelected: details.transformationSelected
        }).catch(function() {});

        if (currentQuizConfig.adaptive) {
            const topicAttempts = recordedAttempts.filter(function(item) { return item.type === state.exerciseKind; });
            const recommendation = window.LogicAdaptiveEngine.recommend(topicAttempts, currentQuizConfig.difficulty);
            if (recommendation.changed) {
                currentQuizConfig = window.LogicDataContracts.normalizeQuizConfig({
                    ...currentQuizConfig,
                    difficulty: recommendation.difficulty
                });
                if (difficultySelect) difficultySelect.value = currentQuizConfig.difficulty;
                if (adaptiveNoticeEl) adaptiveNoticeEl.textContent = recommendation.reason + ' Nuovo livello: ' + recommendation.difficulty + '.';
                adaptiveMessage = recommendation.reason + ' La difficolta passa al livello ' + recommendation.difficulty + '.';
                for (let index = batchCacheIndex; index < batchQuestionsCache.length; index += 1) {
                    batchQuestionsCache[index] = null;
                }
                persistSession({ config: currentQuizConfig });
            }
        }
        return attempt;
    }
    const fetchBatchQuestions = function(operations) {
        return window.LogicQuizBatch.fetchQuestions(operations, {
            buildApiUrl: buildApiUrl,
            postJson: window.LogicApi.postJson,
            batchSize: quizBatchSize,
            timeoutMs: BATCH_REQUEST_TIMEOUT_MS
        });
    };

    const NAME_COLOR_CLASS_COUNT = 4;

    // === Caches for performance optimization (Phase 2-3) ===
    // Cache for buildImageSequenceFromFormula results: key is formula+mode, value is sequence array
    var formulaSequenceCache = {};
    
    // Cache for applyFormulaTransforms results: key is formula+flags, value is transformed formula
    var formulaTransformsCache = {};
    
    // Cache for colorizeAtomsInText results: key is formula+colorMap, value is HTML string
    var colorizeAttentionCache = {};
    let imagePanelSequence = 0;

    function getCachedFormulaSequence(formula, mode) {
        var cacheKey = formula + '|' + mode;
        if (formulaSequenceCache.hasOwnProperty(cacheKey)) {
            return formulaSequenceCache[cacheKey];
        }
        var sequence = buildImageSequenceFromFormula(formula, mode);
        formulaSequenceCache[cacheKey] = sequence;
        return sequence;
    }

    function getCachedFormulaTransforms(formula) {
        // Cache key includes formula and current state flags (since applyFormulaTransforms uses state)
        var flagKey = (state.differentiateParens ? '1' : '0') + (state.spokenlanguage ? '1' : '0');
        var cacheKey = formula + '|' + flagKey;
        if (formulaTransformsCache.hasOwnProperty(cacheKey)) {
            return formulaTransformsCache[cacheKey];
        }
        var transformed = applyFormulaTransforms(formula);
        formulaTransformsCache[cacheKey] = transformed;
        return transformed;
    }

    function clearFormulaSequenceCaches() {
        formulaSequenceCache = {};
        formulaTransformsCache = {};
        colorizeAttentionCache = {};
    }

    function isDayMode() {
        return document.documentElement.classList.contains('day-mode') || document.body.classList.contains('day-mode');
    }

    // Pulisce il pannello immagini legato alle risposte errate.
    function clearWrongActionImages() {
        if (!wrongActionImagesEl) return;
        wrongActionImagesEl.innerHTML = '';
        wrongActionImagesEl.hidden = true;
    }

    function resolveImageCandidates(action, mode) {
        const item = ACTION_IMAGE_FILES[action];
        if (!item) return [];
        const raw = item[mode];
        if (Array.isArray(raw)) return raw;
        if (typeof raw === 'string') return [raw];
        return [];
    }

    function resetSpokenNameColors() {
        currentSpokenNameColors = {};
    }

    function buildSpokenNameColorMap() {
        const assigned = {};

        Object.keys(atomSpokenMap || {}).forEach(function(atom) {
            const entry = atomSpokenMap[atom];
            if (!entry || !entry.nome) return;
            const nameKey = normalizeNameKey(entry.nome);
            if (!nameKey || Object.prototype.hasOwnProperty.call(assigned, nameKey)) return;

            const colorIndex = Object.keys(assigned).length % NAME_COLOR_CLASS_COUNT;
            assigned[nameKey] = 'quiz-name-color-' + colorIndex;
        });

        currentSpokenNameColors = assigned;
    }

    function resolveNameCaptionClass(name) {
        const nameKey = normalizeNameKey(name);
        if (!nameKey) return '';
        return currentSpokenNameColors[nameKey] || '';
    }

    function connectorText(symbol) {
        const map = {
            '∧': 'E',
            '∨': 'O',
            '→': 'IMPLICA',
            '↔': 'SE E SOLO SE'
        };
        return map[symbol] || symbol;
    }

    function extractFormulaFromQuestionText(text) {
        const question = String(text || '');
        const match = question.match(/"([^"]+)"/);
        if (!match) return '';
        return String(match[1] || '').trim();
    }

    function tokenizeFormulaForImages(formula) {
        let normalized = String(formula || '');
        if (state.differentiateParens) {
            normalized = differentiateParentheses(normalized);
        }
        return normalized.match(/\(|\)|\[|\]|\{|\}|¬|↔|→|∧|∨|∀\s*[A-Za-z][A-Za-z0-9_]*|∃\s*[A-Za-z][A-Za-z0-9_]*|[A-Za-z][A-Za-z0-9_]*/g) || [];
    }

    function isPredicateApplicationParenthesis(tokens, index) {
        if (!Array.isArray(tokens)) return false;
        const current = tokens[index];
        if (current !== '(' && current !== ')') return false;

        if (current === '(') {
            const left = tokens[index - 1] || '';
            const right = tokens[index + 1] || '';
            const rightAfter = tokens[index + 2] || '';
            return /^[A-Za-z][A-Za-z0-9_]*$/.test(left) && /^[A-Za-z][A-Za-z0-9_]*$/.test(right) && rightAfter === ')';
        }

        const left = tokens[index - 1] || '';
        const open = tokens[index - 2] || '';
        const predicate = tokens[index - 3] || '';
        return open === '(' && /^[A-Za-z][A-Za-z0-9_]*$/.test(left) && /^[A-Za-z][A-Za-z0-9_]*$/.test(predicate);
    }

    function removePredicateApplicationParentheses(text) {
        return String(text || '').replace(/\b([A-Za-z][A-Za-z0-9_]*)\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)/g, function(_, predicate, variable) {
            return predicate + ' ' + variable;
        });
    }

    // Trasforma una formula in sequenza di token renderizzabili come immagini/connettivi.
    function buildImageSequenceFromFormula(formula, mode) {
        const tokens = tokenizeFormulaForImages(formula);
        if (tokens.length === 0) return [];

        const sequence = [];

        tokens.forEach(function(token, index) {
            const t = String(token || '').trim();
            if (!t) return;

            if (t === '¬') {
                sequence.push({ type: 'connector', text: 'NON', logicKey: 'OP:NOT' });
                return;
            }

            if (t === '∧' || t === '∨' || t === '→' || t === '↔') {
                sequence.push({ type: 'connector', text: connectorText(t), logicKey: 'OP:' + t });
                return;
            }

            if (t === '(' || t === ')' || t === '[' || t === ']' || t === '{' || t === '}') {
                if (isPredicateApplicationParenthesis(tokens, index)) {
                    return;
                }
                sequence.push({ type: 'parenthesis', text: t, logicKey: 'PAREN:' + t });
                return;
            }

            const quantifierMatch = t.match(/^(∀|∃)\s*([A-Za-z][A-Za-z0-9_]*)$/);
            if (quantifierMatch) {
                const q = quantifierMatch[1];
                const qText = q === '∀' ? 'PER OGNI' : 'ESISTE';
                sequence.push({ type: 'connector', text: qText, logicKey: 'Q:' + q });
                return;
            }

            const entry = atomSpokenMap[t] || atomSpokenMap[t.toLowerCase()];
            if (!entry) return;

            const action = String(entry.azione || '').toLowerCase();
            const candidates = resolveImageCandidates(action, mode);
            if (candidates.length === 0) return;

            sequence.push({
                type: 'image',
                atom: t,
                candidates: candidates,
                nome: String(entry.nome || ''),
                azione: action,
                logicKey: 'ATOM:' + t.toLowerCase()
            });
        });

        return sequence;
    }

    function appendImageNode(container, item, extraClass) {
        const node = document.createElement('div');
        node.className = 'quiz-wrong-images-item' + (extraClass ? ' ' + extraClass : '');

        const img = document.createElement('img');
        img.className = 'quiz-wrong-images-img';
        img.alt = item.atom;
        img.loading = 'lazy';

        let candidateIndex = 0;
        function setCandidate(idx) {
            if (idx >= item.candidates.length) {
                node.remove();
                return;
            }
            img.src = '../Immagini/' + item.candidates[idx];
        }

        img.addEventListener('error', function() {
            candidateIndex += 1;
            setCandidate(candidateIndex);
        });

        const caption = document.createElement('span');
        caption.className = 'quiz-wrong-images-caption';
        const captionSubject = item.nome;
        const captionAction = state.spokenlanguage
            ? formatSpokenAction(item.azione, false)
            : item.azione;

        const subjectText = String(captionSubject || '').trim();
        const actionText = String(captionAction || '').trim();

        const subjectNode = document.createElement('span');
        subjectNode.className = 'quiz-wrong-images-caption-subject';
        subjectNode.textContent = subjectText;

        if (subjectText && !isGenericPersonLabel(subjectText)) {
            const subjectClass = resolveNameCaptionClass(subjectText);
            if (subjectClass) subjectNode.classList.add(subjectClass);
        }

        const actionNode = document.createElement('span');
        actionNode.className = 'quiz-wrong-images-caption-action';
        actionNode.textContent = actionText;

        if (subjectText) {
            caption.appendChild(subjectNode);
        }
        if (subjectText && actionText) {
            caption.appendChild(document.createTextNode(' '));
        }
        if (actionText) {
            caption.appendChild(actionNode);
        }

        node.appendChild(img);
        node.appendChild(caption);
        container.appendChild(node);
        setCandidate(candidateIndex);
    }

    /**
     * Aggiunge un connettivo testuale alla riga immagini.
     * @pre container e un nodo DOM valido.
     * @post Se text non e vuoto viene aggiunto uno span con classe connettore.
     */
    function appendConnectorNode(container, text, extraClass) {
        const connector = document.createElement('span');
        connector.className = 'quiz-wrong-images-connector' + (extraClass ? ' ' + extraClass : '');
        connector.textContent = String(text || '').trim();
        if (!connector.textContent) return;
        container.appendChild(connector);
    }

    /**
     * Aggiunge un simbolo di parentesi alla riga immagini.
     * @pre container e un nodo DOM valido.
     * @post Se text non e vuoto viene aggiunto uno span parentesi.
     */
    function appendParenthesisNode(container, text, extraClass) {
        const paren = document.createElement('span');
        paren.className = 'quiz-wrong-images-parenthesis' + (extraClass ? ' ' + extraClass : '');
        paren.textContent = String(text || '').trim();
        if (!paren.textContent) return;
        container.appendChild(paren);
    }

    /**
     * Determina la classe di evidenziazione confronto step per step.
     * @pre sequence e referenceSequence sono sequenze allineate per indice o vuote.
     * @post Restituisce una classe CSS coerente con highlightKind oppure stringa vuota.
     */
    function resolveStepHighlightClass(sequence, index, referenceSequence, highlightKind) {
        if (!referenceSequence || referenceSequence.length === 0 || !highlightKind) return '';
        const current = sequence[index];
        const reference = referenceSequence[index];
        const isSame = Boolean(reference && current && reference.logicKey === current.logicKey);
        if (isSame) return '';
        if (highlightKind === 'changed') return 'is-step-changed';
        if (highlightKind === 'error') return 'is-step-error';
        return '';
    }

    /**
     * Uniforma diverse forme di step-log in un array di stringhe formula.
     * @pre raw puo essere array eterogeneo (stringhe/oggetti) o altro valore.
     * @post Restituisce sempre un array filtrato di stringhe non vuote.
     */
    function normalizeGenerationSteps(raw) {
        if (!Array.isArray(raw)) return [];
        return raw.map(function(step) {
            if (typeof step === 'string') return step;
            if (!step || typeof step !== 'object') return '';
            return step.formula_prolog || step.formula || step.expr || step.step || '';
        }).filter(function(step) {
            return Boolean(step);
        });
    }

    /**
     * Estrae la formula sorgente di un'opzione privilegiando il primo step disponibile.
     * @pre option e un oggetto opzione o valore nullo.
     * @post Restituisce una stringa formula (o vuota in fallback).
     */
    function getOptionFormulaSource(option) {
        if (!option || typeof option !== 'object') return '';
        const steps = normalizeGenerationSteps(option.formulaSteps);
        if (steps.length > 0) return steps[0];
        return option.text || '';
    }

    function getQuantifiedTraceFormula(option) {
        if (!option || typeof option !== 'object') return null;
        const text = String(option.text || '').trim();
        const match = text.match(/^([∀∃])\s*([A-Za-z][A-Za-z0-9_]*)\s*(¬)?\s*\(([\s\S]*)\)$/);
        const construction = option.construction;
        const steps = construction && Array.isArray(construction.steps) ? construction.steps : [];
        if (!match || steps.length < 2 || construction.final_formula_prolog !== text) return null;

        const quantifier = match[1] === '∀' ? 'forall' : 'exists';
        const variable = match[2];
        const negated = Boolean(match[3]);
        const root = steps[steps.length - 1];
        const unary = negated ? steps[steps.length - 2] : null;
        const base = steps[steps.length - (negated ? 3 : 2)];
        if (!root || root.node_id !== 'root' || root.kind !== 'quantifier' ||
            root.operator !== quantifier || root.result_prolog !== text ||
            String(root.details && root.details.bound_variable || '').toLowerCase() !== variable.toLowerCase() ||
            (negated && (!unary || unary.node_id !== 'root.body' || unary.kind !== 'unary' || unary.operator !== 'not')) ||
            !base || base.node_id !== (negated ? 'root.body.operand' : 'root.body')) {
            return null;
        }

        const body = String(base.result_prolog || '').trim();
        const ast = /^[A-Za-z0-9_,()\s]+$/.test(body) ? quizShared.parsePrologFormula(body) : null;
        if (!ast || quizShared.serializePrologFormula(ast).toLowerCase() !== body.replace(/\s+/g, '').toLowerCase()) {
            return null;
        }
        // Il trace deve descrivere proprio il corpo dell'opzione visualizzata.
        const expectedBody = normalizeFormulaAtoms(match[4]).replace(/\s+/g, '');
        const traceBody = displayFormulaText(body).replace(/\s+/g, '');
        if (expectedBody !== traceBody) return null;

        return {
            quantifier: quantifier,
            variable: variable,
            body: body,
            prolog: quantifier + '(' + variable + ',' + (negated ? 'not(' + body + ')' : body) + ')'
        };
    }

    /**
     * Restituisce la formula da mostrare in UI per una singola opzione.
     * @pre option e un oggetto opzione compatibile.
     * @post Restituisce sempre una stringa renderizzabile in notazione utente.
     */
    function getOptionDisplayFormula(option) {
        const source = getOptionFormulaSource(option);
        // Anche una sessione parlata salvata prima del filtro del generatore
        // mantiene il significato delle risposte: si normalizza solo il display.
        if (!state.spokenlanguage) return displayFormulaText(source);
        const quantifiedTrace = getQuantifiedTraceFormula(option);
        const formulaSource = quantifiedTrace ? quantifiedTrace.prolog : source;
        const readable = quizShared.spokenFriendlyPrologFormula(formulaSource);
        return displayFormulaText(readable === formulaSource ? source : readable);
    }

    /**
     * Estrae e normalizza i passi di generazione delle risposte sbagliate.
     * @pre res e il payload backend (o sua porzione), wrongs e un array formule.
     * @post Restituisce una mappa formula -> array passi (anche vuoto se non presenti dati).
     */
    function extractWrongStepsMap(res, wrongs) {
        const map = {};
        if (!res || !Array.isArray(wrongs)) return map;

        if (Array.isArray(res.wrong_answers_generation_steps)) {
            res.wrong_answers_generation_steps.forEach(function(entry, index) {
                if (!entry) return;
                if (Array.isArray(entry)) {
                    const fallbackFormula = wrongs[index] || '';
                    if (fallbackFormula) map[fallbackFormula] = normalizeGenerationSteps(entry);
                    return;
                }
                if (typeof entry === 'string') {
                    const fallbackFormula = wrongs[index] || '';
                    if (fallbackFormula) map[fallbackFormula] = [entry];
                    return;
                }
                const formula = entry.formula_prolog || entry.formula || wrongs[index] || '';
                const steps = normalizeGenerationSteps(entry.generation_steps || entry.steps || entry.path);
                if (formula) map[formula] = steps;
            });
        }

        return map;
    }

    /**
     * Formatta un passo formula per visualizzazione fallback testuale.
     * @pre step e una stringa formula o valore convertibile.
     * @post Restituisce stringa simbolica e, se attivo, con parentesi differenziate.
     */
    function formatStepFormulaText(step) {
        const source = String(step || '').trim();
        if (!source) return '';

        // Step-log entries are usually Prolog formulas; force symbolic rendering here.
        let text = prologToLogical(source);
        if (!text) {
            text = displayFormulaText(source);
        }
        text = normalizeFormulaAtoms(text);
        if (state.differentiateParens) {
            text = differentiateParentheses(text);
        }
        return text;
    }

    /**
     * Renderizza una sezione immagini (domanda/corretta/sbagliata).
     * @pre parent e un nodo contenitore; descriptor contiene almeno title e formulaText.
     * @post Appende al parent una section completa con fallback testuale se necessario.
     */
    function renderImageFileSection(parent, descriptor, mode, options) {
        const section = document.createElement('section');
        section.className = 'quiz-wrong-images-file';

        const title = document.createElement('h4');
        title.className = 'quiz-wrong-images-file-title';
        title.textContent = descriptor.title;
        section.appendChild(title);

        if (options && options.badgeText) {
            const badge = document.createElement('p');
            badge.className = 'quiz-wrong-images-badge';
            badge.textContent = options.badgeText;
            section.appendChild(badge);
        }

        const row = document.createElement('div');
        row.className = 'quiz-wrong-images-row';
        const allowImages = Boolean(options && options.allowImages);
        // Use cached sequence to avoid repeated tokenization of the same formula
        const sequence = allowImages ? getCachedFormulaSequence(descriptor.formulaText, mode) : [];
        if (sequence.length === 0) {
            const empty = document.createElement('span');
            empty.className = 'quiz-wrong-images-empty';
            const fallbackFormula = formatStepFormulaText(descriptor.formulaText);
            empty.textContent = removePredicateApplicationParentheses(fallbackFormula) || 'Nessuna formula disponibile.';
            row.appendChild(empty);
        } else {
            sequence.forEach(function(item, index) {
                const extraClass = resolveStepHighlightClass(
                    sequence,
                    index,
                    options && options.referenceSequence,
                    options && options.highlightKind
                );
                if (item.type === 'connector') {
                    appendConnectorNode(row, item.text, extraClass);
                    return;
                }
                if (item.type === 'parenthesis') {
                    appendParenthesisNode(row, item.text, extraClass);
                    return;
                }
                appendImageNode(row, item, extraClass);
            });
        }

        section.appendChild(row);
        if (options && options.legendText) {
            const legend = document.createElement('p');
            legend.className = 'quiz-wrong-images-legend';
            legend.textContent = options.legendText;
            section.appendChild(legend);
        }
        parent.appendChild(section);
    }

    /**
     * Compone l'elenco descriptor immagini usando i builder registrati su window.
     * @pre context contiene i dati formula correnti della domanda.
     * @post Restituisce un array di descriptor validi con almeno un titolo.
     */
    function buildImageFileDescriptors(context) {
        const descriptors = [];
        if (typeof window.quizQuestionImageFileBuilder === 'function') {
            descriptors.push(window.quizQuestionImageFileBuilder(context));
        }
        if (typeof window.quizCorrectImageFileBuilder === 'function') {
            descriptors.push(window.quizCorrectImageFileBuilder(context));
        }
        if (typeof window.quizWrongImageFileBuilder === 'function') {
            descriptors.push(window.quizWrongImageFileBuilder(context));
        }
        return descriptors.filter(function(item) {
            return item && typeof item.title === 'string';
        });
    }

    /**
     * Renderizza i blocchi immagini contestuali alla risposta corrente.
     * @pre Lo stato quiz corrente e coerente (selectedIndex/correctIndex validi quando disponibili).
     * @post Il pannello immagini e aggiornato oppure nascosto se non applicabile.
     */
    function renderWrongActionImages() {
        if (!wrongActionImagesEl) return;
        clearWrongActionImages();

        const shouldRenderImages = Boolean(state.showWrongActionImages && state.spokenlanguage);
        if (!shouldRenderImages) return;

        const mode = isDayMode() ? 'day' : 'night';
        const selectedOption = state.options[state.selectedIndex] || null;
        const correctOption = state.options[state.correctIndex] || null;
        const wrongOption = selectedOption;
        const context = {
            questionText: currentQuestionText,
            questionFormulaText: extractFormulaFromQuestionText(currentQuestionText),
            correctFormulaText: correctOption ? getOptionDisplayFormula(correctOption) : '',
            wrongFormulaText: wrongOption ? getOptionDisplayFormula(wrongOption) : '',
            questionFormulaSteps: currentImageFormulaSteps.question || [],
            correctFormulaSteps: currentImageFormulaSteps.correct || [],
            wrongFormulaSteps: wrongOption && currentImageFormulaSteps.wrongByFormula
                ? (currentImageFormulaSteps.wrongByFormula[wrongOption.text] || [])
                : []
        };

        const descriptors = buildImageFileDescriptors(context);
        if (descriptors.length === 0) return;

        const descriptorMap = {};
        descriptors.forEach(function(descriptor) {
            descriptorMap[descriptor.key] = descriptor;
        });

        const questionDescriptor = descriptorMap.question || null;
        const correctDescriptor = descriptorMap.correct || null;
        const wrongDescriptor = descriptorMap.wrong || null;

        const questionSequence = questionDescriptor
            ? getCachedFormulaSequence(questionDescriptor.formulaText, mode)
            : [];
        const correctSequence = correctDescriptor
            ? getCachedFormulaSequence(correctDescriptor.formulaText, mode)
            : [];

        const frag = document.createDocumentFragment();
        if (questionDescriptor && shouldRenderImages) {
            renderImageFileSection(frag, questionDescriptor, mode, {
                allowImages: shouldRenderImages,
                referenceSequence: null,
                highlightKind: '',
                badgeText: '',
                legendText: ''
            });
        }
        if (correctDescriptor) {
            renderImageFileSection(frag, correctDescriptor, mode, {
                allowImages: shouldRenderImages,
                referenceSequence: questionSequence,
                highlightKind: '',
                badgeText: '',
                legendText: ''
            });
        }
        if (wrongDescriptor) {
            renderImageFileSection(frag, wrongDescriptor, mode, {
                allowImages: shouldRenderImages,
                referenceSequence: correctSequence,
                highlightKind: '',
                badgeText: '',
                legendText: ''
            });
        }

        const panel = document.createElement('div');
        panel.className = 'quiz-wrong-images-panel';
        panel.appendChild(frag);
        if (panel.childElementCount === 0) return;

        imagePanelSequence += 1;
        const panelId = 'quizWrongActionImagesPanel-' + String(imagePanelSequence);
        panel.id = panelId;
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', 'Immagini della soluzione');

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'quiz-wrong-images-toggle';
        toggle.textContent = 'Nascondi le immagini';
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-controls', panelId);
        toggle.addEventListener('click', function() {
            const willOpen = panel.hidden;
            panel.hidden = !willOpen;
            toggle.textContent = willOpen ? 'Nascondi le immagini' : 'Mostra le immagini';
            toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        });

        wrongActionImagesEl.appendChild(toggle);
        wrongActionImagesEl.appendChild(panel);
        wrongActionImagesEl.hidden = false;
    }

    /**
     * Sincronizza disponibilita toggle immagini con la modalita linguaggio parlato.
     * @pre showWrongActionImagesInput puo essere nullo nelle pagine senza controllo.
     * @post Il controllo e abilitato/disabilitato e lo stato interno resta coerente.
     */
    function syncWrongImagesAvailability() {
        if (!showWrongActionImagesInput) return;
        const enabled = Boolean(state.spokenlanguage);
        showWrongActionImagesInput.disabled = !enabled;
        if (!enabled) {
            showWrongActionImagesInput.checked = false;
            state.showWrongActionImages = false;
            clearWrongActionImages();
            return;
        }
        state.showWrongActionImages = Boolean(showWrongActionImagesInput.checked);
    }

    function syncSpokenLanguageAvailability() {
        if (!spokenLanguageInput) return;
        spokenLanguageInput.disabled = Boolean(state.spokenlanguageLocked);
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Estrae una mappa atomo->boolean dalle righe informative della domanda.
     * @pre infoLines e array di stringhe o valore non-array.
     * @post Restituisce una mappa con chiavi originali e lowercase quando trovate.
     */
    function extractTruthAssignments(infoLines) {
        const out = {};
        if (!Array.isArray(infoLines)) return out;
        infoLines.forEach(function(line) {
            const match = String(line).match(/^\s*([A-Za-z][A-Za-z0-9_]*)\s+(?:e|è|=|:)\s*(vero|falso)\s*$/i);
            if (!match) return;
            const atom = match[1];
            const isTrue = match[2].toLowerCase() === 'vero';
            out[atom] = isTrue;
            out[atom.toLowerCase()] = isTrue;
        });
        return out;
    }

    /**
     * Associa gli atomi alla legenda API, con fallback deterministico se assente.
     * @pre parsed e una domanda normalizzata con info e opzioni.
     * @post Restituisce una mappa atomo -> {nome, azione} semanticamente coerente.
     */
    function buildAtomSpokenMap(parsed) {
        return quizShared.resolveSpokenMap(
            parsed && parsed.info,
            collectAtomsFromExercise(parsed || {}),
            NOMI,
            AZIONI
        );
    }

    /**
     * Colleziona l'insieme atomi usati in info/opzioni per la modalita parlata.
     * @pre parsed contiene opzionalmente info e options.
     * @post Restituisce un array ordinato di atomi unici in lowercase.
     */
    function collectAtomsFromExercise(parsed) {
        const atomSet = new Set();
        if (Array.isArray(parsed.info)) {
            parsed.info.forEach(function(line) {
                const match = String(line).match(/^\s*([A-Za-z][A-Za-z0-9_]*)\s+(?:e|è|=|:)\s*(vero|falso)\s*$/i);
                if (match) atomSet.add(match[1].toLowerCase());
            });
        }
        if (Array.isArray(parsed.options)) {
            parsed.options.forEach(function(opt) {
                const formula = getOptionDisplayFormula(opt);
                const quantifiedVars = new Set();
                String(formula).replace(/[∀∃]\s*([A-Za-z][A-Za-z0-9_]*)/g, function(_, variable) {
                    quantifiedVars.add(String(variable).toLowerCase());
                    return _;
                });

                const predicateMatches = String(formula).match(/\b([A-Za-z][A-Za-z0-9_]*)\s*\(\s*[A-Za-z][A-Za-z0-9_]*\s*\)/g);
                if (predicateMatches) {
                    predicateMatches.forEach(function(predicate) {
                        const baseMatch = predicate.match(/^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(/);
                        if (baseMatch) atomSet.add(baseMatch[1].toLowerCase());
                    });
                }

                const letters = String(formula).match(/\b[A-Za-z]\b(?!\s*\()/g);
                if (letters) {
                    letters.forEach(function(letter) {
                        const lower = String(letter).toLowerCase();
                        if (!quantifiedVars.has(lower)) {
                            atomSet.add(lower);
                        }
                    });
                }
            });
        }
        return Array.from(atomSet).sort();
    }

    function extractQuantifiedVariables(text) {
        const variables = [];
        const seen = new Set();
        String(text || '').replace(/[∀∃]\s*([A-Za-z][A-Za-z0-9_]*)/g, function(_, variable) {
            const normalized = String(variable || '').toLowerCase();
            if (!seen.has(normalized)) {
                seen.add(normalized);
                variables.push(String(variable || ''));
            }
            return _;
        });
        return variables;
    }

    function normalizeFormulaAtoms(text) {
        let out = String(text || '');
        if (out.indexOf('"') !== -1) {
            return out.replace(/"([^"]*)"/g, function(_, inner) {
                return '"' + normalizeFormulaAtoms(inner) + '"';
            });
        }
        out = out.replace(/^\s*([a-z])\s+((?:e|è|=|:)\s*(?:vero|falso)\s*)$/i, function(_, atom, rest) {
            return atom.toUpperCase() + ' ' + rest;
        });
        out = out.replace(/\b([a-z])(?=\s*\()/g, function(_, atom) {
            return atom.toUpperCase();
        });

        function previousNonSpaceChar(source, index) {
            for (let i = index - 1; i >= 0; i -= 1) {
                const ch = source[i];
                if (!/\s/.test(ch)) return ch;
            }
            return '';
        }

        function nextNonSpaceChar(source, index) {
            for (let i = index; i < source.length; i += 1) {
                const ch = source[i];
                if (!/\s/.test(ch)) return ch;
            }
            return '';
        }

        function isFormulaBoundaryChar(ch) {
            return !ch || /[\(\)\[\]\{\}¬∧∨→↔,:;]/.test(ch);
        }

        const quantifiedVariables = extractQuantifiedVariables(out);
        const quantifiedSet = new Set(quantifiedVariables.map(function(v) {
            return String(v).toLowerCase();
        }));
        const quantifiedVariable = quantifiedVariables.length > 0
            ? String(quantifiedVariables[0] || '').toLowerCase()
            : null;

        if (quantifiedVariables.length > 0) {
            out = out.replace(/([∀∃]\s*)([A-Za-z][A-Za-z0-9_]*)/g, function(_, prefix, variable) {
                return prefix + String(variable || '').toLowerCase();
            });
        }

        if (quantifiedVariable) {
            out = out.replace(/\b([A-Za-z])\b(?!\s*\()/g, function(_, atom, offset, source) {
                const lower = String(atom).toLowerCase();
                if (quantifiedSet.has(lower)) {
                    return lower;
                }
                const prev = previousNonSpaceChar(source, offset);
                const next = nextNonSpaceChar(source, offset + String(atom).length);
                if (!isFormulaBoundaryChar(prev) || !isFormulaBoundaryChar(next)) {
                    return atom;
                }
                return String(atom).toUpperCase() + '(' + quantifiedVariable + ')';
            });
            return out;
        }

        return out.replace(/\b([a-z])\b(?!\s*\()/g, function(_, atom, offset, source) {
            const prev = previousNonSpaceChar(source, offset);
            const next = nextNonSpaceChar(source, offset + String(atom).length);
            if (!isFormulaBoundaryChar(prev) || !isFormulaBoundaryChar(next)) {
                return atom;
            }
            return atom.toUpperCase();
        });
    }

    function normalizeAtomLookupKey(token) {
        const source = String(token || '').trim();
        const predicateMatch = source.match(/^([A-Za-z][A-Za-z0-9_]*)\s*\(\s*[A-Za-z][A-Za-z0-9_]*\s*\)$/);
        if (predicateMatch) {
            return predicateMatch[1].toLowerCase();
        }
        return source.toLowerCase();
    }

    function formatSpokenAction(action, negated) {
        const normalizedAction = String(action || '').trim();
        let actionText = normalizedAction;
        if (normalizedAction === 'apre' || normalizedAction === 'apre la porta' || normalizedAction === 'chiude') {
            actionText = normalizedAction + ' la porta';
            if (normalizedAction === 'apre la porta') {
                actionText = normalizedAction;
            }
        }
        if (negated) {
            return 'non ' + actionText;
        }
        return actionText;
    }

    function pluralizeAction(actionText) {
        const a = String(actionText || '').trim();
        if (!a) return a;
        const parts = a.split(/\s+/);
        const first = parts[0];
        const map = {
            nuota: 'nuotano',
            corre: 'corrono',
            salta: 'saltano',
            guarda: 'guardano',
            parla: 'parlano',
            apre: 'aprono',
            chiude: 'chiudono',
            ascolta: 'ascoltano'
        };
        let pluralFirst = map[first];
        if (!pluralFirst) {
            if (first.endsWith('a')) pluralFirst = first.slice(0, -1) + 'ano';
            else if (first.endsWith('e')) pluralFirst = first.slice(0, -1) + 'ono';
            else pluralFirst = first + 'ano';
        }
        parts[0] = pluralFirst;
        return parts.join(' ');
    }

    /**
     * Converte una formula simbolica in testo piu naturale in base alla mappa parlata.
     * @pre text e una stringa formula o testo; atomSpokenMap puo essere vuota.
     * @post Restituisce una stringa leggibile con sostituzioni lessicali e connettivi testuali.
     */
    function applySpokenTransform(text) {
        if (!state.spokenlanguage || Object.keys(atomSpokenMap).length === 0) return String(text || '');
        let out = normalizeFormulaAtoms(text);
        const quantifiedSet = new Set(extractQuantifiedVariables(out).map(function(v) {
            return String(v).toLowerCase();
        }));
        const universalSet = new Set();
        String(out).replace(/∀\s*([A-Za-z][A-Za-z0-9_]*)/g, function(_, v) { universalSet.add(String(v || '').toLowerCase()); return _; });
        const existentialSet = new Set();
        String(out).replace(/∃\s*([A-Za-z][A-Za-z0-9_]*)/g, function(_, v) { existentialSet.add(String(v || '').toLowerCase()); return _; });
        const spokenTokens = [];
        function stashSpoken(textChunk) {
            spokenTokens.push(textChunk);
            return '%%' + String(spokenTokens.length - 1) + '%%';
        }

        out = out.replace(/¬\s*([A-Za-z][A-Za-z0-9_]*(?:\s*\(\s*[A-Za-z][A-Za-z0-9_]*\s*\))?)/g, function(_, atom) {
            const key = normalizeAtomLookupKey(atom);
            const entry = atomSpokenMap[key] || atomSpokenMap[String(key).toLowerCase()];
            if (entry) {
                // detect if atom has a quantified variable like P(x)
                const m = String(atom).match(/^([A-Za-z][A-Za-z0-9_]*)\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)$/);
                if (m) {
                    const variable = String(m[2] || '').toLowerCase();
                    if (universalSet.has(variable)) {
                        return stashSpoken('non è vero che ' + pluralizeAction(formatSpokenAction(entry.azione, false)));
                    }
                    if (existentialSet.has(variable)) {
                        return stashSpoken('non è vero che ' + formatSpokenAction(entry.azione, false));
                    }
                }
                return stashSpoken('non è vero che ' + entry.nome + ' ' + formatSpokenAction(entry.azione, false));
            }
            return 'non è vero che ' + atom;
        });

        out = out.replace(/\b([A-Za-z][A-Za-z0-9_]*)(?:\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\))?/g, function(match, atom, variable) {
            if (!variable && quantifiedSet.has(String(atom).toLowerCase())) {
                return match;
            }
            const key = normalizeAtomLookupKey(variable ? atom + '(' + variable + ')' : atom);
            const entry = atomSpokenMap[key] || atomSpokenMap[String(key).toLowerCase()];
            if (entry) {
                if (variable) {
                    const varLower = String(variable || '').toLowerCase();
                    if (universalSet.has(varLower)) {
                        return stashSpoken(pluralizeAction(formatSpokenAction(entry.azione, false)));
                    }
                    if (existentialSet.has(varLower)) {
                        return stashSpoken(formatSpokenAction(entry.azione, false));
                    }
                }
                return stashSpoken(entry.nome + ' ' + formatSpokenAction(entry.azione, false));
            }
            return match;
        });

        // handle implication between stashed spoken tokens as "Se P allora Q"
        out = out.replace(/(%%\d+%%)\s*→\s*(%%\d+%%)/g, function(_, a, b) {
            return 'se ' + a + ' allora ' + b;
        });

        out = out
            .replace(/∀\s*([A-Za-z][A-Za-z0-9_]*)/g, function() { return 'Per ogni persona, '; })
            .replace(/∃\s*([A-Za-z][A-Za-z0-9_]*)/g, function() { return 'Esiste una persona, '; })
            .replace(/↔/g, ' se e solo se ')
            .replace(/→/g, ' allora ')
            .replace(/∧/g, ' e ')
            .replace(/∨/g, ' oppure ')
            .replace(/¬\s*/g, 'non è vero che ');

        out = out.replace(/%%(\d+)%%/g, function(_, idx) {
            const numericIndex = Number(idx);
            return spokenTokens[numericIndex] || '';
        });

        // Remove outer parentheses immediately following quantifiers (do not change inner capitalization here)
        out = out.replace(/(Per ogni persona, |Esiste una persona, )\(\s*([^)]*?)\s*\)/g, function(_, prefix, inner) {
            inner = String(inner || '').trim();
            return prefix + inner;
        });

        // Remove any remaining parentheses in the spoken form
        out = out.replace(/[()]/g, '');

        out = out.replace(/\s{2,}/g, ' ').trim();
        if (out.length > 0) {
            const firstLetterIndex = out.search(/[A-Za-zÀ-ÖØ-öø-ÿ]/);
            if (firstLetterIndex >= 0) {
                out = out.slice(0, firstLetterIndex) + out.charAt(firstLetterIndex).toUpperCase() + out.slice(firstLetterIndex + 1);
            }
        }
        return out;
    }

    /**
     * Traduce una singola riga info in linguaggio parlato preservando verita/falsita.
     * @pre line e stringa con possibile pattern "atomo e vero/falso".
     * @post Restituisce una frase naturale basata su atomSpokenMap se disponibile.
     */
    function formatSpokenInfoLine(line) {
        // Accept multiple separators and both Italian/English boolean literals
        const match = String(line).match(/^\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:-|:|\s+|(?:e|è|=))\s*(vero|falso|true|false|1|0)\s*$/i);
        if (!match) return applySpokenTransform(String(line));
        const atom = match[1];
        const rawVal = String(match[2] || '').toLowerCase();
        const isTrue = rawVal === 'vero' || rawVal === 'true' || rawVal === '1';
        const key = normalizeAtomLookupKey(atom);
        const entry = atomSpokenMap[key] || atomSpokenMap[String(key).toLowerCase()];
        if (!entry) return line;
        return entry.nome + ' ' + formatSpokenAction(entry.azione, !isTrue);
    }

    /**
     * Colora ed evidenzia token atomici in base alle assegnazioni di verita correnti.
     * @pre text e stringa; currentTruthAssignments contiene eventuali valori noti.
     * @post Restituisce HTML sanitizzato con span semantici quando applicabili.
     */
    function colorizeAtomsInText(text) {
        const source = String(text || '');
        const keys = Object.keys(currentTruthAssignments || {});
        const shouldColor = Boolean(state.colorAtoms && keys.length > 0);
        const shouldHighlight = Boolean(state.highlightAtoms);
        if (!shouldColor && !shouldHighlight) return escapeHtml(source);

        const atomRegex = /\b[A-Za-z][A-Za-z0-9_]*\b/g;
        let out = '';
        let last = 0;
        let match;
        while ((match = atomRegex.exec(source)) !== null) {
            const start = match.index;
            const end = atomRegex.lastIndex;
            const token = match[0];
            out += escapeHtml(source.slice(last, start));

            let hasValue = false;
            let value = false;
            let isAtom = false;
            if (Object.prototype.hasOwnProperty.call(currentTruthAssignments, token)) {
                hasValue = true;
                value = Boolean(currentTruthAssignments[token]);
                isAtom = true;
            } else if (Object.prototype.hasOwnProperty.call(currentTruthAssignments, token.toLowerCase())) {
                hasValue = true;
                value = Boolean(currentTruthAssignments[token.toLowerCase()]);
                isAtom = true;
            } else if (token.toLowerCase() === 'vero') {
                hasValue = true;
                value = true;
            } else if (token.toLowerCase() === 'falso') {
                hasValue = true;
                value = false;
            } else if (/^[A-Za-z]$/.test(token)) {
                isAtom = true;
            }

            const classes = [];
            if (shouldColor && hasValue) {
                classes.push(value ? 'quiz-atom-true' : 'quiz-atom-false');
            }
            if (shouldHighlight && isAtom) {
                classes.push('quiz-atom-emphasis');
            }

            if (classes.length > 0) {
                out += '<span class="' + classes.join(' ') + '">' + escapeHtml(token) + '</span>';
            } else {
                out += escapeHtml(token);
            }
            last = end;
        }
        out += escapeHtml(source.slice(last));
        return out;
    }

    /**
     * Applica trasformazioni di presentazione formula in base alle opzioni attive.
     * @pre text e stringa formula o testo.
     * @post Restituisce testo trasformato (parentesi differenziate e/o parlato).
     */
    function applyFormulaTransforms(text) {
        let out = normalizeFormulaAtoms(text);
        if (state.differentiateParens) {
            out = differentiateParentheses(out);
        }
        if (state.spokenlanguage) {
            out = applySpokenTransform(out);
        }
        return out;
    }

    /**
     * Rirenderizza domanda/info/opzioni dopo variazione impostazioni visuali.
     * @pre Lo stato domanda corrente e inizializzato.
     * @post UI allineata a state (colori atomi, parlato, parentesi).
     */
    function refreshCurrentExerciseRendering() {
        if (questionEl && currentQuestionText) {
            questionEl.textContent = state.exerciseKind === 'translation'
                ? currentQuestionText
                : getCachedFormulaTransforms(currentQuestionText);
            // Only sync width when rendering after question load (called in loadExercise),
            // not on every setting change to reduce DOM reflows
        }
        showInfo(currentQuestionInfo);
        renderOptions();
    }

    /**
     * Attiva/disattiva il layout split con pannello formule laterale.
     * @pre Gli elementi layout opzionali possono essere assenti; la funzione deve restare safe.
     * @post Le classi/visibilita layout risultano allineate allo stato corrente.
     */
    function applyFormulasLayout() {
        const enabled = Boolean(state.showFormulas && splitLayoutEl && formulasPaneEl && testEl && !testEl.hidden);
        if (splitLayoutEl) {
            splitLayoutEl.classList.toggle('with-formulas', enabled);
        }
        if (formulasPaneEl) {
            formulasPaneEl.hidden = !enabled;
        }
        document.body.classList.toggle('quiz-formulas-mode', enabled);
    }

    function updateTestTitle() {
        if (!testTitleEl) return;
        testTitleEl.textContent = 'Domanda ' + String(currentExercise) + ' di ' + String(totalExercises);
    }

    /**
     * Calcola quante domande di negazione quantificatori inserire nel test.
     * @pre totalQuestions e numero totale domande del test.
     * @post Restituisce un intero >= 0 conforme alla strategia di distribuzione.
     */
    function pickQuantifierNegationTarget(totalQuestions) {
        if (!Number.isFinite(totalQuestions) || totalQuestions < 1) return 0;
        if (totalQuestions < 5) {
            return Math.random() < 0.5 ? 1 : 0;
        }
        if (totalQuestions < 10) {
            return 1;
        }
        return Math.max(1, Math.round(totalQuestions * 0.1));
    }

    /**
     * Costruisce una lista ordinata di operazioni garantendo almeno 1 di ogni tipo domanda.
     * @pre totalCount e numero positivo, spokenlanguageMode e boolean.
     * @post Restituisce array di {operation: string, payload: object} con distribuzione ordinata.
     */
    function buildOrderedQuestionsList(totalCount, spokenlanguageMode) {
        const config = window.LogicDataContracts.normalizeQuizConfig({
            ...currentQuizConfig,
            questionCount: totalCount,
            spokenLanguage: spokenlanguageMode,
            questionTypes: currentQuizConfig.questionTypes
        });
        const atomCount = window.LogicQuizConfig.atomCountForDifficulty(config.difficulty);
        const quantifierRatio = config.difficulty === 'hard' ? 0.75 : config.difficulty === 'easy' ? 0.25 : 0.5;
        const payloadOptions = { wrongAnswersCount: 3, quantifierRatio: quantifierRatio };
        return window.LogicQuizConfig.buildOperationPlan(config, {
            equivalence: function() { return quizPayloads.buildEquivalencePayload(config.spokenLanguage, payloadOptions); },
            'truth-value': function() { return quizPayloads.buildTruthValuePayload(config.spokenLanguage, atomCount, payloadOptions); },
            'logical-consequence': function() { return quizPayloads.buildLogicalConsequencePayload(config.spokenLanguage, atomCount, payloadOptions); },
            translation: function() { return quizPayloads.buildTranslationPayload(config.spokenLanguage, NOMI, AZIONI, shuffle, payloadOptions); }
        });
    }

    function buildEquivalencePayload(spokenlanguageMode) {
        return quizPayloads.buildEquivalencePayload(spokenlanguageMode);
    }

    function buildTruthValuePayload(spokenlanguageMode) {
        return quizPayloads.buildTruthValuePayload(
            spokenlanguageMode,
            window.LogicQuizConfig.atomCountForDifficulty(currentQuizConfig.difficulty)
        );
    }

    function buildLogicalConsequencePayload(spokenlanguageMode) {
        return quizPayloads.buildLogicalConsequencePayload(
            spokenlanguageMode,
            window.LogicQuizConfig.atomCountForDifficulty(currentQuizConfig.difficulty)
        );
    }

    function buildTranslationPayload(spokenlanguageMode) {
        const ratio = currentQuizConfig.difficulty === 'hard' ? 0.75 : currentQuizConfig.difficulty === 'easy' ? 0.25 : 0.5;
        return quizPayloads.buildTranslationPayload(spokenlanguageMode, NOMI, AZIONI, shuffle, { quantifierRatio: ratio });
    }


    /**
     * Ritorna la prossima domanda dalla cache batch.
     * @pre batchQuestionsCache e inizializzata.
     * @post Incrementa l'indice e ritorna la risposta (potenzialmente null).
     */
    function getNextCachedQuestion() {
        if (batchCacheIndex >= batchQuestionsCache.length) {
            return null;
        }
        const result = batchQuestionsCache[batchCacheIndex];
        batchCacheIndex += 1;
        return result;
    }


    function shouldKeepRawFormula(formula) {
        const text = String(formula || '');
        return /[∀∃]/.test(text);
    }

    /**
     * Sceglie come visualizzare una formula (raw o convertita da Prolog).
     * @pre formula e stringa formula o valore convertibile.
     * @post Restituisce una stringa pronta per l'interfaccia utente.
     */
    function displayFormulaText(formula) {
        if (shouldKeepRawFormula(formula)) {
            return normalizeFormulaAtoms(String(formula || ''));
        }
        return normalizeFormulaAtoms(prologToLogical(formula));
    }

    function getSpokenQuestionText(parsed) {
        const question = String(parsed && parsed.question || '');
        if (!state.spokenlanguage || !parsed) {
            return question;
        }
        if (parsed.kind === 'quantifier-negation') {
            const quote = question.match(/"([∀∃])\s*([A-Za-z][A-Za-z0-9_]*)\s*\(([\s\S]*?)\)"/);
            const trace = Array.isArray(parsed.options)
                ? parsed.options.map(getQuantifiedTraceFormula).find(Boolean)
                : null;
            if (!quote || !trace || quote[2].toLowerCase() !== trace.variable.toLowerCase() ||
                normalizeFormulaAtoms(quote[3]).replace(/\s+/g, '') !==
                    displayFormulaText(trace.body).replace(/\s+/g, '')) {
                return question;
            }
            const quantifier = quote[1] === '∀' ? 'forall' : 'exists';
            const source = quantifier + '(' + quote[2] + ',' + trace.body + ')';
            const readable = quizShared.spokenFriendlyPrologFormula(source);
            return readable === source
                ? question
                : question.replace(quote[0], '"' + displayFormulaText(readable) + '"');
        }
        if (!/^(equivalence|logical-consequence)$/.test(parsed.kind)) return question;
        const questionSteps = parsed.kind === 'equivalence' && parsed.imageFormulaSteps &&
            Array.isArray(parsed.imageFormulaSteps.question)
            ? parsed.imageFormulaSteps.question
            : [];
        const source = String(
            (parsed.questionConstruction && parsed.questionConstruction.final_formula_prolog) ||
            (questionSteps.length > 0 ? questionSteps[questionSteps.length - 1] : '')
        ).trim();
        if (!source || !question.includes('"')) return question;
        const readable = quizShared.spokenFriendlyPrologFormula(source);
        if (readable === source) return question;
        return question.replace(/"[^"]*"/, '"' + displayFormulaText(readable) + '"');
    }


    /**
     * Recupera un esercizio di equivalenza dal backend.
     * @pre equivalenceApiUrl raggiungibile e backend conforme al contratto atteso.
     * @post Restituisce un oggetto normalizzato pronto per il rendering o solleva errore.
     */
    async function fetchEquivalenceExercise() {
        const payload = await window.LogicApi.postJson(
            equivalenceApiUrl,
            buildEquivalencePayload(state.spokenlanguage)
        );

        const parsed = normalizeEquivalenceResult(payload);
        if (parsed) {
            return parsed;
        }
        throw new Error('Formato risposta equivalenza non valido');
    }

    /**
     * Recupera un esercizio sul valore di verita.
     * @pre truthApiUrl raggiungibile e backend conforme al contratto atteso.
     * @post Restituisce un oggetto normalizzato con domanda, info e 4 opzioni.
     */
    async function fetchTruthValueExercise() {
        const payload = await window.LogicApi.postJson(
            truthApiUrl,
            buildTruthValuePayload(state.spokenlanguage)
        );

        const parsed = normalizeTruthValueResult(payload);
        if (parsed) {
            return parsed;
        }
        throw new Error('Formato risposta valore di verita non valido');
    }

    /**
     * Recupera un esercizio di conseguenza logica dal backend.
     * @pre logicalConsequenceApiUrl raggiungibile e backend conforme al contratto atteso.
     * @post Restituisce un oggetto normalizzato con domanda e opzioni.
     */
    async function fetchLogicalConsequenceExercise() {
        let lastStatus = 0;
        let lastDetail = '';

        for (let attempt = 0; attempt < 4; attempt += 1) {
            let payload = null;
            try {
                payload = await window.LogicApi.postJson(
                    logicalConsequenceApiUrl,
                    buildLogicalConsequencePayload(state.spokenlanguage)
                );
                lastStatus = 200;
            } catch (error) {
                lastStatus = Number(error && error.status) || 0;
                payload = error && error.payload ? error.payload : null;
            }

            const parsed = normalizeLogicalConsequenceResult(payload);
            if (parsed) {
                return parsed;
            }

            const detailText = payload && typeof payload === 'object'
                ? String(payload.message || payload.detail || '')
                : '';
            if (detailText) {
                lastDetail = detailText;
            }
        }

        if (lastDetail) {
            throw new Error('HTTP ' + lastStatus + ' - ' + lastDetail);
        }
        throw new Error('HTTP ' + lastStatus);
    }

    async function fetchQuantifierNegationExercise() {
        const payload = await window.LogicApi.postJson(formulaByVariableCountApiUrl, {
            variable_count: window.LogicQuizConfig.atomCountForDifficulty(currentQuizConfig.difficulty),
            use_all: false,
            allow_spoken_mode: Boolean(state.spokenlanguage),
            timeout: 10
        });

        try {
            const baseFormula = String((payload && payload.result) || '').trim();
            if (baseFormula) {
                const logicalBaseFormula = prologToLogical(baseFormula);
                const quantifier = Math.random() < 0.5 ? '∀' : '∃';
                const quantified = buildQuantifiedNegationOptions(
                    quantifier,
                    logicalBaseFormula,
                    baseFormula,
                    state.spokenlanguage
                );
                return {
                    kind: 'quantifier-negation',
                    question: quantified.question,
                    info: [],
                    options: quantified.options
                };
            }
        } catch (_) {
            // The backend returned non-JSON or an unexpected payload.
        }
        throw new Error('Formato risposta formula non valido');
    }

    async function fetchTranslationExercise() {
        function hasRepeatedPersonAction(questionText) {
            const text = String(questionText || '').toLowerCase();
            if (!text) return false;

            function escapeRegex(value) {
                return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            }

            for (let nameIndex = 0; nameIndex < NOMI.length; nameIndex += 1) {
                const name = String(NOMI[nameIndex] || '').trim().toLowerCase();
                if (!name) continue;

                for (let actionIndex = 0; actionIndex < AZIONI.length; actionIndex += 1) {
                    const action = String(AZIONI[actionIndex] || '').trim().toLowerCase();
                    if (!action) continue;

                    const actionPattern = escapeRegex(action).replace(/\s+/g, '\\s+');
                    const pattern = new RegExp('\\b' + escapeRegex(name) + '\\b(?:\\s|,|;|:)+(' + actionPattern + ')\\b', 'gi');
                    const matches = text.match(pattern);
                    if (matches && matches.length > 1) {
                        return true;
                    }
                }
            }

            return false;
        }

        function countDistinctActionsInQuestion(questionText) {
            const text = String(questionText || '').toLowerCase();
            if (!text) return 0;

            const found = new Set();
            AZIONI.forEach(function(action) {
                const normalized = String(action || '').trim().toLowerCase();
                if (!normalized) return;
                const escaped = normalized.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const pattern = new RegExp('\\b' + escaped + '\\b', 'i');
                if (pattern.test(text)) {
                    found.add(normalized);
                }
            });

            return found.size;
        }

        let fallbackParsed = null;
        let lastStatus = 0;

        for (let attempt = 0; attempt < 4; attempt += 1) {
            let payload = null;
            try {
                payload = await window.LogicApi.postJson(
                    translationApiUrl,
                    buildTranslationPayload(state.spokenlanguage)
                );
                lastStatus = 200;
            } catch (error) {
                lastStatus = Number(error && error.status) || 0;
                continue;
            }

            try {
                const parsed = normalizeTranslationResult(payload);
                if (!parsed) {
                    continue;
                }

                if (hasRepeatedPersonAction(parsed.question)) {
                    continue;
                }

                const distinctActions = countDistinctActionsInQuestion(parsed.question);
                if (distinctActions >= 2) {
                    return parsed;
                }

                if (!fallbackParsed) {
                    fallbackParsed = parsed;
                }
            } catch (_) {
                // The backend returned non-JSON or an unexpected payload.
            }
        }

        if (fallbackParsed) {
            return fallbackParsed;
        }
        throw new Error('HTTP ' + lastStatus);
    }

    /**
     * Carica la prossima domanda dal batch o fallback singolo se necessario.
     * @pre Il quiz e in stato attivo (test avviato) e i nodi UI essenziali sono disponibili.
     * @post Aggiorna domanda/opzioni/stato; in caso errore mostra fallback utente senza interrompere l'app.
     */
    async function loadExercise() {
        state.locked = false;
        state.mode = 'check';
        state.selectedIndex = null;
        actionButton.textContent = 'Controlla la risposta';
        actionButton.disabled = true;
        setStatus('Caricamento della domanda…');
        questionEl.textContent = 'Caricamento della domanda…';
        currentQuestionText = '';
        optionsEl.innerHTML = '';
        showInfo([]);
        hideFormulaTransformation();
        clearWrongActionImages();

        try {
            let parsed = null;

            // Primo caricamento: fetch batch
            if (!batchInitialized) {
                try {
                    logger.info('Inizializzazione batch per ' + totalExercises + ' domande...');
                    const operationsList = buildOrderedQuestionsList(totalExercises, state.spokenlanguage);
                    batchOperationsPlan = operationsList.slice();
                    logger.debug('Operazioni batch costruite:', operationsList.length);
                    const batchResults = await fetchBatchQuestions(operationsList);
                    logger.debug('Batch ricevuto:', batchResults.length, 'risposte');
                    
                    // Normalizza tutte le risposte del batch
                    batchQuestionsCache = batchResults.map(function(result, index) {
                        if (!result) {
                            logger.warn('Soft-fail: operazione ' + index + ' ritornata null');
                            return null;
                        }
                        try {
                            const operation = batchOperationsPlan[index];
                            return normalizeQuestionResult(result, operation.operation);
                        } catch (e) {
                            logger.warn('Errore normalizzazione operazione ' + index + ':', e.message);
                            return null;
                        }
                    });
                    
                    batchInitialized = true;
                    logger.info('Batch inizializzato con', batchQuestionsCache.filter(Boolean).length, 'domande valide su', batchQuestionsCache.length);
                    persistSession({
                        phase: 'check',
                        operationPlan: batchOperationsPlan,
                        questions: batchQuestionsCache
                    });
                } catch (batchErr) {
                    logger.error('Errore batch fetch, fallback a singoli:', batchErr.message);
                    batchInitialized = true; // Evita retry infiniti
                    batchQuestionsCache = [];
                    parsed = await loadFallbackExercise(batchCacheIndex);
                }
            }

            // Se batch non ha fornito risposta valida, prova cache o fallback singolo
            if (!parsed) {
                const currentPlanIndex = batchCacheIndex;
                parsed = getNextCachedQuestion();
                if (!parsed) {
                    // Cache esaurita o nulla: fallback singolo
                    logger.debug('Cache esaurita, fallback singolo per domanda', currentExercise);
                    parsed = await loadFallbackExercise(currentPlanIndex);
                }
            }

            if (!parsed) {
                throw new Error('Formato risposta non valido');
            }

            // Resto della logica di rendering (identico a prima)
            state.exerciseKind = parsed.kind;
            state.options = parsed.options;
            state.correctIndex = parsed.options.findIndex(function(option) {
                return option.correct;
            });
            state.selectedIndex = null;

            if (parsed.kind === 'quantifier-negation') {
                quantifierNegationUsed += 1;
            }

            currentQuestionText = parsed.question;
            currentQuestionId = String(parsed.questionId || '');
            currentImageFormulaSteps = parsed.imageFormulaSteps || { question: [], correct: [], wrongByFormula: {} };
            // Clear formula sequence cache when loading new question to avoid stale data
            clearFormulaSequenceCaches();
            // If backend indicated spoken_mode, enable spoken language mode automatically
            if (parsed && parsed.spoken_mode) {
                state.spokenlanguage = true;
                state.spokenlanguageLocked = false;
                try { syncSpokenLanguageAvailability(); } catch (_) {}
            }

            currentQuestionText = getSpokenQuestionText(parsed);

            if (state.spokenlanguage) {
                atomSpokenMap = buildAtomSpokenMap(parsed);
                buildSpokenNameColorMap();
            } else {
                atomSpokenMap = {};
                resetSpokenNameColors();
            }
            questionEl.textContent = parsed.kind === 'translation'
                ? currentQuestionText
                : applyFormulaTransforms(currentQuestionText);
            currentQuestionInfo = Array.isArray(parsed.info) ? parsed.info.slice() : [];
            currentTruthAssignments = extractTruthAssignments(currentQuestionInfo);
            showInfo(parsed.info);
            renderOptions();
            if (resumeSelectedIndex != null && resumeSelectedIndex < state.options.length) {
                selectIndex(resumeSelectedIndex);
                resumeSelectedIndex = null;
            }
            clearWrongActionImages();
            if (!Array.isArray(state.options) || state.options.length === 0) {
                state.locked = true;
                state.mode = 'next';
                actionButton.textContent = currentExercise >= totalExercises ? 'Vedi i risultati' : 'Prossima domanda';
                actionButton.disabled = false;
                setStatus('L\'API non ha fornito opzioni selezionabili. Usa il pulsante per continuare.');
            } else if (state.correctIndex < 0) {
                setStatus('Seleziona una risposta. La correzione sarà registrata dal backend.');
            } else {
                setStatus('Seleziona una risposta. Puoi usare anche i tasti freccia.');
            }
            if (state.selectedIndex == null) {
                const firstOption = optionsEl.querySelector('.quiz-option');
                if (firstOption) firstOption.focus();
            }
            
            // Registra il timestamp di quando l'utente vede la domanda
            if (currentExercise > 0 && currentExercise <= totalExercises) {
                questionViewTimestamps[currentExercise] = Date.now();
            }
            persistSession({ phase: 'check' });
        } catch (err) {
            setStatus('Errore nel caricamento esercizio: ' + err.message);
            questionEl.textContent = 'Impossibile caricare l\'esercizio.';
            state.locked = true;
            state.mode = 'error';
            actionButton.disabled = true;
            quizTimer.stop();
            quizTimer.hide();
            currentQuestionText = '';
            currentQuestionId = '';
            atomSpokenMap = {};
            resetSpokenNameColors();
            currentQuestionInfo = [];
            currentTruthAssignments = {};
            currentImageFormulaSteps = { question: [], correct: [], wrongByFormula: {} };
            showInfo([]);
            hideFormulaTransformation();
            clearWrongActionImages();
            if (indexNavEl) {
                indexNavEl.hidden = false;
                const mainMenuLink = indexNavEl.querySelector('a[href="/"], a[href="../index.html"]');
                if (mainMenuLink) {
                    mainMenuLink.textContent = 'Torna al menu principale';
                    mainMenuLink.focus();
                }
            }
        }
    }

    /**
     * Normalizza una risposta del batch in base al tipo operazione.
     * @pre result e una risposta backend, operationType e il tipo operazione richiesto.
     * @post Restituisce oggetto quiz normalizzato o solleva errore.
     */
    function normalizeQuestionResult(result, operationType) {
        if (operationType === 'build_ex_depth') {
            return normalizeEquivalenceResult(result);
        } else if (operationType === 'build_tvq') {
            return normalizeTruthValueResult(result);
        } else if (operationType === 'build_logical_consequence_question') {
            return normalizeLogicalConsequenceResult(result);
        } else if (operationType === 'build_translation_question') {
            return normalizeTranslationResult(result);
        } else if (operationType === 'build_quantifier_negation') {
            // Per quantifier negation, la risposta del batch è direttamente una formula
            try {
                const baseFormula = String(result.result || result || '').trim();
                if (!baseFormula) throw new Error('Empty formula');
                const logicalBaseFormula = prologToLogical(baseFormula);
                const quantifier = Math.random() < 0.5 ? '∀' : '∃';
                const quantified = buildQuantifiedNegationOptions(
                    quantifier,
                    logicalBaseFormula,
                    baseFormula,
                    state.spokenlanguage
                );
                return {
                    kind: 'quantifier-negation',
                    question: quantified.question,
                    info: [],
                    options: quantified.options
                };
            } catch (e) {
                throw new Error('Invalid quantifier negation result: ' + e.message);
            }
        }
        throw new Error('Unknown operation type: ' + operationType);
    }

    /**
     * Carica una singola domanda usando il vecchio meccanismo (fallback soft-fail).
     * @pre Lo stato quiz e configurato.
     * @post Restituisce una domanda normalizzata o solleva errore.
     */
    async function loadSingleExercise() {
        const allowedOperations = window.LogicQuizConfig.allowedOperations(currentQuizConfig);
        const operation = pickRandom(allowedOperations);
        if (!operation) throw new Error('Nessuna tipologia configurata per il fallback');
        return await loadSingleExerciseByOperation(operation);
    }

    async function loadFallbackExercise(planIndex) {
        const normalizedIndex = Math.max(0, Number(planIndex) || 0);
        const planned = batchOperationsPlan[normalizedIndex];
        const operation = window.LogicQuizConfig.resolveFallbackOperation(
            currentQuizConfig,
            planned && planned.operation
        );
        if (!operation) throw new Error('Nessuna operazione valida per il fallback');
        const parsed = await loadSingleExerciseByOperation(operation);
        batchCacheIndex = Math.max(batchCacheIndex, normalizedIndex + 1);
        return parsed;
    }

    async function loadSingleExerciseByOperation(operationType) {
        if (operationType === 'build_ex_depth') {
            return await fetchEquivalenceExercise();
        }
        if (operationType === 'build_tvq') {
            return await fetchTruthValueExercise();
        }
        if (operationType === 'build_logical_consequence_question') {
            return await fetchLogicalConsequenceExercise();
        }
        if (operationType === 'build_translation_question') {
            return await fetchTranslationExercise();
        }
        if (operationType === 'build_quantifier_negation') {
            return await fetchQuantifierNegationExercise();
        }
        return await loadSingleExercise();
    }

    /**
     * Sposta la selezione corrente nelle opzioni con comportamento circolare.
     * @pre delta e intero (tipicamente +/-1).
     * @post state.selectedIndex cambia se il quiz non e bloccato.
     */
    function moveSelection(delta, originIndex) {
        if (state.locked || state.options.length === 0) return;

        const len = state.options.length;
        const currentIndex = Number.isInteger(state.selectedIndex)
            ? state.selectedIndex
            : (Number.isInteger(originIndex) ? originIndex : (delta > 0 ? -1 : 0));
        const nextIndex = (currentIndex + delta + len) % len;
        selectIndex(nextIndex, true);
    }

    /**
     * Seleziona direttamente un indice opzione.
     * @pre idx e compreso tra 0 e state.options.length-1.
     * @post La selezione visiva viene aggiornata se il quiz non e bloccato.
     */
    function selectIndex(idx, shouldFocus) {
        if (state.locked || idx < 0 || idx >= state.options.length) return;

        state.selectedIndex = idx;
        updateSelectionVisual({ focusIndex: idx, focus: shouldFocus === true });
        actionButton.disabled = false;
        persistSession({ selectedIndex: idx });
    }

    /**
     * Valuta la risposta selezionata e prepara il passaggio alla domanda successiva.
        * @pre state.options contiene almeno 2 opzioni e state.correctIndex e valido.
     * @post Blocca la domanda corrente, aggiorna feedback visuale/testuale e registra il risultato nel recap.
     */
    // Format elapsed time in seconds with two decimals and 's' suffix, or '' if invalid
    function formatElapsedTime(ms) {
        if (typeof ms !== 'number' || isNaN(ms) || ms < 0) return '';
        return (ms / 1000).toFixed(2) + 's';
    }

    function checkAnswer() {
        if (!Array.isArray(state.options) || state.options.length === 0) {
            hideFormulaTransformation();
            state.locked = true;
            state.mode = 'next';
            actionButton.textContent = currentExercise >= totalExercises ? 'Vedi i risultati' : 'Prossima domanda';
            actionButton.disabled = false;
            setStatus('Nessuna opzione disponibile. Usa il pulsante per continuare.');
            return;
        }

        if (state.locked) return;

        const selected = optionsEl.querySelector('.quiz-option.is-selected');
        if (!selected || state.selectedIndex == null) {
            logger.warn("Nessuna selezione valida");
            setStatus('Seleziona una risposta prima di continuare.');
            actionButton.disabled = true;
            const firstOption = optionsEl.querySelector('.quiz-option');
            if (firstOption) firstOption.focus();
            return;
        }

        const optionHadKeyboardFocus = optionsEl.contains(document.activeElement);
        state.locked = true;

        try {
            resetVisualFeedback();

            const canScore = state.correctIndex >= 0;
            const isCorrect = canScore && state.selectedIndex === state.correctIndex;
            const shouldRenderWrongActionImages = canScore && !isCorrect;
            clearWrongActionImages();

            selected.classList.add('is-final');
            if (canScore) {
                selected.classList.add(isCorrect ? 'is-correct' : 'is-wrong');
            }

            if (canScore && !isCorrect) {
                const options = optionsEl.querySelectorAll('.quiz-option');
                const correctOption = options[state.correctIndex];
                if (correctOption) {
                    correctOption.classList.add('is-final');
                    correctOption.classList.add('is-correct-answer');
                }
            }

            // Accesso sicuro alle opzioni
            const selectedRaw = state.options[state.selectedIndex] ?? '';
            const correctRaw = canScore ? (state.options[state.correctIndex] ?? '') : '';

            const selectedFormula = getOptionDisplayFormula(selectedRaw);
            const correctFormula = getOptionDisplayFormula(correctRaw);

            // CALCOLA IL TEMPO DI RISPOSTA UNA VOLTA SOLA
            let tempoRisposta = '';
            let elapsedMs = 0;
            if (questionViewTimestamps[currentExercise] != null) {
                const elapsed = Date.now() - questionViewTimestamps[currentExercise];
                elapsedMs = elapsed;
                tempoRisposta = formatElapsedTime(elapsed);
            }

            // Tipo domanda calcolato dal kind interno per evitare ambiguita nel testo domanda.
            let tipoDomanda = '';
            switch (state.exerciseKind) {
                case 'truth-value':
                    tipoDomanda = 'Ipotesi';
                    break;
                case 'equivalence':
                    tipoDomanda = 'Equivalenza';
                    break;
                case 'logical-consequence':
                    tipoDomanda = 'Conseguenza logica';
                    break;
                case 'translation':
                    tipoDomanda = 'Traduzione';
                    break;
                default:
                    tipoDomanda = 'Negazione';
                    break;
            }
            const qText = questionEl.textContent || '';

            // Opzioni attive (usa funzione sicura)
            const opzioniAttive = getActiveOptions();

            // Risposte mostrate (versione robusta)
            let risposteMostrate = '';
            if (Array.isArray(state.options)) {
                risposteMostrate = state.options.map(opt => {
                    try {
                        if (!opt) return '';
                        if (typeof opt === 'object' && opt !== null && 'text' in opt) {
                            return String(opt.text ?? '');
                        }
                        return String(opt);
                    } catch {
                        return '';
                    }
                }).join(' | ');
            }

            // Domanda completa
            let domandaCompleta = qText;
            if (tipoDomanda === 'Ipotesi' && currentQuestionInfo && currentQuestionInfo.length > 0) {
                domandaCompleta = qText.replace(/\?$/, '') + ' (' + currentQuestionInfo.join(', ') + ')';
            }

            const reviewEntry = {
                number: currentExercise,
                question: domandaCompleta,
                infoLines: state.spokenlanguage
                    ? currentQuestionInfo.map(formatSpokenInfoLine)
                    : currentQuestionInfo.slice(),
                selectedAnswer: state.spokenlanguage ? applySpokenTransform(selectedFormula) : applyFormulaTransforms(selectedFormula),
                correctAnswer: canScore
                    ? (state.spokenlanguage ? applySpokenTransform(correctFormula) : applyFormulaTransforms(correctFormula))
                    : 'Non disponibile (fornita dal backend)',
                isCorrect: isCorrect,
                tipoDomanda: tipoDomanda,
                tempoRisposta: tempoRisposta,
                opzioniAttive: opzioniAttive,
                risposteMostrate: risposteMostrate,
                constructionCorrect: canScore && correctRaw && typeof correctRaw === 'object'
                    ? correctRaw.construction
                    : null,
                transformationCorrect: canScore && correctRaw && typeof correctRaw === 'object'
                    ? correctRaw.transformation
                    : null,
                transformationSelected: selectedRaw && typeof selectedRaw === 'object'
                    ? selectedRaw.transformation
                    : null
            };
            reviewResults.push(reviewEntry);

            recordLearningAttempt({
                question: domandaCompleta,
                selectedAnswer: reviewEntry.selectedAnswer,
                correctAnswer: reviewEntry.correctAnswer,
                correct: isCorrect,
                scorable: canScore,
                elapsedMs: elapsedMs,
                construction: reviewEntry.constructionCorrect,
                transformationCorrect: reviewEntry.transformationCorrect,
                transformationSelected: reviewEntry.transformationSelected
            });

            if (currentQuizConfig.showConstruction) {
                showFormulaTransformation({
                    correct: canScore && correctRaw && typeof correctRaw === 'object'
                        ? correctRaw.transformation
                        : null,
                    selected: selectedRaw && typeof selectedRaw === 'object'
                        ? selectedRaw.transformation
                        : null,
                    selectedIsCorrect: isCorrect
                });
            } else {
                hideFormulaTransformation();
            }

            // La spiegazione della trasformazione precede sempre le immagini.
            // Un errore nel rendering opzionale delle immagini non deve nasconderla
            // né interrompere la registrazione della risposta.
            if (shouldRenderWrongActionImages) {
                try {
                    renderWrongActionImages();
                } catch (imageError) {
                    logger.error('Errore nel rendering delle immagini della risposta:', imageError);
                    clearWrongActionImages();
                }
            }

            const continuationStatus = canScore
                ? 'Risposta registrata. Continua quando sei pronto.'
                : 'Risposta registrata senza correzione locale. Continua quando sei pronto';
            setStatus(continuationStatus + (adaptiveMessage ? ' ' + adaptiveMessage : ''));
            adaptiveMessage = '';
            actionButton.textContent = currentExercise >= totalExercises ? 'Vedi i risultati' : 'Prossima domanda';
            actionButton.disabled = false;
            setRenderedOptionsLocked(true);
            persistSession({ phase: 'next' });

        } catch (err) {
            logger.error("Errore in checkAnswer:", err);
        }

        // SEMPRE eseguito → evita blocchi
        state.mode = 'next';
        // Il pulsante-opzione viene disabilitato dopo la verifica: sposta il
        // focus sull'azione successiva, così un altro Invio avanza davvero.
        if (optionHadKeyboardFocus && !actionButton.disabled) {
            actionButton.focus();
        }
    }

    function renderReview() {
        if (!window.LogicPrivacy.canSendFeedback()) {
            showReviewPage();
            return;
        }

        if (reviewTitleEl) {
            reviewTitleEl.hidden = false;
            reviewTitleEl.textContent = 'Valuta l\'esercitazione (facoltativo)';
        }
        if (reviewNavEl) reviewNavEl.hidden = true;
        if (indexNavEl) indexNavEl.hidden = true;
        renderFeedbackPage();
    }

    // Passa alla schermata finale e interrompe il timer.
    function showCompletion() {
        state.locked = true;
        quizTimer.stop();
        quizTimer.hide();
        if (introTitleEl) introTitleEl.hidden = true;
        state.options = [];
        optionsEl.innerHTML = '';
        showInfo([]);
        hideFormulaTransformation();
        if (testTitleEl) testTitleEl.hidden = true;
        if (reviewTitleEl) reviewTitleEl.hidden = false;
        if (testEl) testEl.hidden = true;
        applyFormulasLayout();
        renderReview();
        if (reviewEl) reviewEl.hidden = false;
        if (indexNavEl) indexNavEl.hidden = true;
        if (reviewTitleEl) {
            reviewTitleEl.setAttribute('tabindex', '-1');
            reviewTitleEl.focus();
        }
        state.mode = 'completed';
        sessionManager.complete(reviewResults.slice()).then(function() {
            activeSession = null;
        }).catch(function() {});
    }

    // Ripristina stato iniziale del quiz e mostra la schermata intro.
    function showIntro() {
        currentExercise = 0;
        reviewResults.length = 0;
        recordedAttempts.length = 0;
        currentQuestionInfo = [];
        currentTruthAssignments = {};
        atomSpokenMap = {};
        resetSpokenNameColors();
        currentQuestionText = '';
        currentQuestionId = '';
        currentImageFormulaSteps = { question: [], correct: [], wrongByFormula: {} };
        quantifierNegationTarget = 0;
        quantifierNegationUsed = 0;
        feedbackValues = createEmptyFeedbackValues();
        reviewSubmissionState.reset();
        // Resetta batch state
        batchQuestionsCache = [];
        batchCacheIndex = 0;
        batchInitialized = false;
        batchOperationsPlan = [];
        hideFormulaTransformation();
        clearWrongActionImages();
        quizTimer.reset(standardTimeMinutes);
        quizTimer.hide();
        if (questionCountInput && !questionCountInput.value) questionCountInput.value = String(DEFAULT_EXERCISES);
        if (timeMinutesInput && !timeMinutesInput.value) timeMinutesInput.value = String(DEFAULT_TIME_MINUTES);
        state.showFormulas = Boolean(showFormulasInput && showFormulasInput.checked);
        state.colorAtoms = Boolean(colorAtomsInput && colorAtomsInput.checked);
        state.spokenlanguage = Boolean(spokenLanguageInput && spokenLanguageInput.checked);
        state.showWrongActionImages = Boolean(showWrongActionImagesInput && showWrongActionImagesInput.checked);
        state.spokenlanguageLocked = false;
        syncSpokenLanguageAvailability();
        syncWrongImagesAvailability();
        if (presetSelect) window.LogicQuizConfig.syncPresetLocks(root, presetSelect.value);
        applyFormulasLayout();
        if (testTitleEl) testTitleEl.hidden = true;
        if (introTitleEl) introTitleEl.hidden = false;
        if (reviewTitleEl) reviewTitleEl.hidden = true;
        if (reviewTitleEl) reviewTitleEl.textContent = 'Risultati del quiz';
        if (reviewEl) reviewEl.hidden = true;
        if (reviewNavEl) reviewNavEl.hidden = true;
        if (testEl) testEl.hidden = true;
        if (introEl) introEl.hidden = false;
        if (indexNavEl) indexNavEl.hidden = false;
    }

    /**
     * Avvia un nuovo test con i parametri impostati dall'utente.
     * @pre Gli input intro (numero domande e minuti) sono presenti o fallback gestibili.
     * @post Timer avviato, stato azzerato e prima domanda in caricamento.
     */
    async function startTest() {
        syncLogDataSettings();
        if (!root.querySelector('[data-quiz-question-type]:checked')) {
            alert('Seleziona almeno una tipologia di domanda.');
            return;
        }
        const requestedQuestionCount = Array.from(root.querySelectorAll('[data-quiz-type-count]')).reduce(function(total, input) {
            const toggle = root.querySelector('[data-quiz-question-type][value="' + input.dataset.quizTypeCount + '"]');
            return total + (toggle && toggle.checked ? Math.max(0, Number(input.value) || 0) : 0);
        }, 0);
        if (requestedQuestionCount < 1) {
            alert('Imposta almeno una domanda nelle tipologie selezionate.');
            return;
        }
        if (requestedQuestionCount > quizMaximumQuestions) {
            alert('Il quiz supporta al massimo ' + String(quizMaximumQuestions) + ' domande per sessione. Riduci le quantita per tipologia.');
            return;
        }
        currentQuizConfig = window.LogicQuizConfig.readForm(root);
        currentExercise = 1;
        reviewResults.length = 0;
        recordedAttempts.length = 0;
        totalExercises = currentQuizConfig.questionCount;
        standardTimeMinutes = currentQuizConfig.timeMinutes;
        quantifierNegationTarget = pickQuantifierNegationTarget(totalExercises);
        quantifierNegationUsed = 0;
        feedbackValues = createEmptyFeedbackValues();
        reviewSubmissionState.reset();
        // Inizializza l'array dei timestamp con la lunghezza corretta (indici da 1 a totalExercises)
        questionViewTimestamps = new Array(totalExercises + 1);
        // Aggiorna il timestamp di inizio esercitazione
        quizStartTimestamp = Date.now();
        // Inizializza batch state
        batchQuestionsCache = [];
        batchCacheIndex = 0;
        batchInitialized = false;
        batchOperationsPlan = [];
        activeSession = await sessionManager.start(currentQuizConfig);
        if (questionCountInput) questionCountInput.value = String(totalExercises);
        if (timeMinutesInput) timeMinutesInput.value = String(standardTimeMinutes);
        state.showFormulas = Boolean(showFormulasInput && showFormulasInput.checked);
        state.colorAtoms = Boolean(colorAtomsInput && colorAtomsInput.checked);
        state.spokenlanguage = currentQuizConfig.spokenLanguage;
        state.showWrongActionImages = currentQuizConfig.showImages;
        state.spokenlanguageLocked = true;
        syncSpokenLanguageAvailability();
        syncWrongImagesAvailability();
        applyFormulasLayout();
        updateTestTitle();
        if (testTitleEl) testTitleEl.hidden = false;
        if (introTitleEl) introTitleEl.hidden = true;
        if (reviewTitleEl) reviewTitleEl.hidden = true;
        if (introEl) introEl.hidden = true;
        if (reviewEl) reviewEl.hidden = true;
        if (reviewNavEl) reviewNavEl.hidden = true;
        if (indexNavEl) indexNavEl.hidden = true;
        if (testEl) testEl.hidden = false;
        applyFormulasLayout();
        quizTimer.start(standardTimeMinutes);
        loadExercise();
    }

    function applyConfigToForm(config) {
        const normalized = window.LogicDataContracts.normalizeQuizConfig(config);
        if (presetSelect) presetSelect.value = normalized.preset;
        if (modeSelect) modeSelect.value = normalized.mode;
        if (difficultySelect) difficultySelect.value = normalized.difficulty;
        if (questionCountInput) questionCountInput.value = String(normalized.questionCount);
        if (timeMinutesInput) timeMinutesInput.value = String(normalized.timeMinutes);
        if (adaptiveInput) adaptiveInput.checked = normalized.adaptive;
        if (showConstructionInput) showConstructionInput.checked = normalized.showConstruction;
        if (spokenLanguageInput) spokenLanguageInput.checked = normalized.spokenLanguage;
        if (showWrongActionImagesInput) showWrongActionImagesInput.checked = normalized.showImages;
        root.querySelectorAll('[data-quiz-question-type]').forEach(function(input) {
            input.checked = normalized.questionTypes.includes(input.value);
        });
        root.querySelectorAll('[data-quiz-type-count]').forEach(function(input) {
            if (Object.prototype.hasOwnProperty.call(normalized.typeCounts, input.dataset.quizTypeCount)) {
                input.value = String(normalized.typeCounts[input.dataset.quizTypeCount]);
            }
        });
        window.LogicQuizConfig.syncPresetLocks(root, normalized.preset);
    }

    async function resumeSavedSession() {
        const session = await sessionManager.loadActive();
        if (!session) return;
        feedbackValues = createEmptyFeedbackValues();
        reviewSubmissionState.reset();
        activeSession = session;
        quizStartTimestamp = Number(session.createdAt) || Date.now();
        currentQuizConfig = session.config;
        applyConfigToForm(currentQuizConfig);
        totalExercises = currentQuizConfig.questionCount;
        standardTimeMinutes = currentQuizConfig.timeMinutes;
        currentExercise = Math.max(1, session.currentIndex || 1);
        reviewResults.length = 0;
        Array.prototype.push.apply(reviewResults, session.answers || []);
        batchOperationsPlan = Array.isArray(session.operationPlan) ? session.operationPlan.slice() : [];
        batchQuestionsCache = Array.isArray(session.questions) ? session.questions.slice() : [];
        batchInitialized = batchQuestionsCache.length > 0;
        if (session.phase === 'next' && currentExercise < totalExercises) currentExercise += 1;
        batchCacheIndex = Math.max(0, currentExercise - 1);
        questionViewTimestamps = new Array(totalExercises + 1);
        state.showFormulas = Boolean(showFormulasInput && showFormulasInput.checked);
        state.colorAtoms = Boolean(colorAtomsInput && colorAtomsInput.checked);
        state.spokenlanguage = currentQuizConfig.spokenLanguage;
        state.showWrongActionImages = currentQuizConfig.showImages;
        resumeSelectedIndex = session.phase === 'check' ? session.selectedIndex : null;
        state.spokenlanguageLocked = true;
        if (resumePanelEl) resumePanelEl.hidden = true;
        if (introEl) introEl.hidden = true;
        if (introTitleEl) introTitleEl.hidden = true;
        if (testTitleEl) testTitleEl.hidden = false;
        if (testEl) testEl.hidden = false;
        if (indexNavEl) indexNavEl.hidden = true;
        syncSpokenLanguageAvailability();
        syncWrongImagesAvailability();
        applyFormulasLayout();
        updateTestTitle();
        if (session.phase === 'next' && session.currentIndex >= totalExercises) {
            showCompletion();
            return;
        }
        quizTimer.startSeconds(session.remainingSeconds || (standardTimeMinutes * 60));
        loadExercise();
    }

    function offerSavedSession() {
        sessionManager.loadActive().then(function(session) {
            if (!session || !resumePanelEl) return;
            resumePanelEl.hidden = false;
            if (resumeSummaryEl) {
                resumeSummaryEl.textContent = 'Domanda ' + String(session.currentIndex) + ' di ' + String(session.config.questionCount)
                    + ', tempo residuo ' + window.LogicQuizTimer.format(session.remainingSeconds) + '.';
            }
        }).catch(function() {});
    }

    function clearActiveSessionState() {
        activeSession = null;
        resumeSelectedIndex = null;
        if (resumePanelEl) resumePanelEl.hidden = true;
        if (resumeSummaryEl) resumeSummaryEl.textContent = '';
        sessionManager.discard().catch(function() {});
    }

    function applyUrlConfiguration() {
        const params = new URLSearchParams(window.location.search);
        const requestedType = params.get('type');
        const requestedDifficulty = params.get('difficulty');
        if (window.LogicDataContracts.QUESTION_TYPES.includes(requestedType)) {
            root.querySelectorAll('[data-quiz-question-type]').forEach(function(input) {
                input.checked = input.value === requestedType;
            });
            if (presetSelect) presetSelect.value = 'custom';
        }
        if (window.LogicDataContracts.DIFFICULTIES.includes(requestedDifficulty) && difficultySelect) {
            difficultySelect.value = requestedDifficulty;
            if (presetSelect) presetSelect.value = 'custom';
        }
    }

    function attemptsForExport(storedAttempts) {
        const byId = new Map();
        (storedAttempts || []).concat(recordedAttempts).forEach(function(attempt) {
            byId.set(attempt.attemptId || stableQuestionId(attempt.type, attempt.question, attempt.answeredAt), attempt);
        });
        return Array.from(byId.values()).sort(function(left, right) { return Number(left.answeredAt) - Number(right.answeredAt); });
    }

    function loadQuizCapabilities() {
        return window.LogicApi.requestJson(buildApiUrl('capabilities'), { timeoutMs: 5000 }).then(function(capabilities) {
            const advertisedMaximum = Math.floor(Number(capabilities?.limits?.question_count?.maximum));
            const advertisedBatchSize = Math.floor(Number(capabilities?.limits?.batch_size));
            if (Number.isFinite(advertisedMaximum) && advertisedMaximum > 0) {
                quizMaximumQuestions = Math.min(MAX_QUIZ_QUESTIONS, advertisedMaximum);
                if (questionCountInput) questionCountInput.max = String(quizMaximumQuestions);
                if (questionMaximumEl) questionMaximumEl.textContent = String(quizMaximumQuestions);
                root.querySelectorAll('[data-quiz-type-count]').forEach(function(input) {
                    input.max = String(quizMaximumQuestions);
                });
            }
            if (Number.isFinite(advertisedBatchSize) && advertisedBatchSize > 0) {
                quizBatchSize = Math.min(quizMaximumQuestions, advertisedBatchSize);
            }
            const supported = Array.isArray(capabilities.question_types) ? capabilities.question_types : [];
            root.querySelectorAll('[data-quiz-question-type]').forEach(function(input) {
                input.disabled = supported.length > 0 && !supported.includes(input.value);
            });
        }).catch(function() {
            if (adaptiveNoticeEl) adaptiveNoticeEl.textContent = 'Limiti del backend non disponibili: verranno usati i valori standard.';
        });
    }

    optionsEl.addEventListener('click', function(evt) {
        const item = evt.target.closest('.quiz-option');
        if (!item) return;
        selectIndex(Number(item.dataset.index));
    });

    optionsEl.addEventListener('keydown', function(evt) {
        const option = evt.target.closest('.quiz-option');
        if (!option) return;
        const optionIndex = Number(option.dataset.index);

        if (evt.key === 'Enter') {
            evt.preventDefault();
            evt.stopPropagation();
            if (evt.repeat) return;

            if (state.mode === 'next') {
                activateQuizPrimaryAction();
                return;
            }

            if (state.locked) return;
            if (state.mode === 'check' && state.selectedIndex === optionIndex && !actionButton.disabled) {
                activateQuizPrimaryAction();
                return;
            }
            selectIndex(optionIndex, true);
            return;
        }

        if (state.locked) return;

        if (evt.key === 'ArrowDown' || evt.key === 'ArrowRight') {
            evt.preventDefault();
            moveSelection(1, optionIndex);
            return;
        }

        if (evt.key === 'ArrowUp' || evt.key === 'ArrowLeft') {
            evt.preventDefault();
            moveSelection(-1, optionIndex);
            return;
        }

        if (evt.key === 'Home') {
            evt.preventDefault();
            selectIndex(0, true);
            return;
        }

        if (evt.key === 'End') {
            evt.preventDefault();
            selectIndex(state.options.length - 1, true);
            return;
        }

        if (evt.key === ' ') {
            evt.preventDefault();
            selectIndex(optionIndex, true);
        }
    });

    function activateQuizPrimaryAction() {
        if (actionButton.disabled) return;

        if (state.mode === 'check') {
            checkAnswer();
            return;
        }

        if (state.mode === 'next') {
            if (currentExercise >= totalExercises) {
                showCompletion();
                return;
            }
            currentExercise += 1;
            state.selectedIndex = null;
            updateTestTitle();
            persistSession({ currentIndex: currentExercise, phase: 'check', selectedIndex: null });
            loadExercise();
        }
    }

    actionButton.addEventListener('click', activateQuizPrimaryAction);

    document.addEventListener('keydown', function(evt) {
        if (evt.key !== 'Enter' || evt.defaultPrevented || evt.repeat) return;
        if (!testEl || testEl.hidden || (state.mode !== 'check' && state.mode !== 'next')) return;

        const target = evt.target;
        const unrelatedControl = target && typeof target.closest === 'function'
            ? target.closest(
                'input, textarea, select, a[href], summary, button:not(.quiz-option), '
                + '[role="button"]:not(.quiz-option), [contenteditable="true"]'
            )
            : null;
        if (unrelatedControl || actionButton.disabled) return;

        evt.preventDefault();
        activateQuizPrimaryAction();
    });

    if (reviewRestartButton) {
        reviewRestartButton.addEventListener('click', function() {
            showIntro();
        });
    }

    if (startButton && introEl && testEl) {
        startButton.addEventListener('click', startTest);
        if (presetSelect) {
            presetSelect.addEventListener('change', function() {
                window.LogicQuizConfig.applyPreset(root, presetSelect.value);
                syncTypeCountTotal();
            });
        }
        if (modeSelect) {
            modeSelect.addEventListener('change', function() {
                if (modeSelect.value === 'exam') {
                    if (adaptiveInput) adaptiveInput.checked = false;
                    if (showConstructionInput) showConstructionInput.checked = false;
                }
            });
        }
        function syncTypeCountTotal() {
            let total = 0;
            root.querySelectorAll('[data-quiz-question-type]').forEach(function(toggle) {
                const count = root.querySelector('[data-quiz-type-count="' + toggle.value + '"]');
                if (count) count.disabled = !toggle.checked;
                if (toggle.checked && count) total += Math.max(0, Number(count.value) || 0);
            });
            if (questionCountInput) questionCountInput.value = String(total);
        }
        root.querySelectorAll('[data-quiz-question-type], [data-quiz-type-count]').forEach(function(input) {
            input.addEventListener('change', syncTypeCountTotal);
            if (input.matches('[data-quiz-type-count]')) input.addEventListener('input', syncTypeCountTotal);
        });
        if (resumeButton) resumeButton.addEventListener('click', resumeSavedSession);
        if (discardSessionButton) {
            discardSessionButton.addEventListener('click', function() {
                sessionManager.discard().then(function() {
                    activeSession = null;
                    if (resumePanelEl) resumePanelEl.hidden = true;
                });
            });
        }
        if (exportJsonButton) {
            exportJsonButton.addEventListener('click', function() {
                window.LogicAppStorage.instance.list('attempts').then(function(attempts) {
                    window.LogicResultsExport.downloadJson({
                        configuration: currentQuizConfig,
                        attempts: attemptsForExport(attempts)
                    });
                });
            });
        }
        if (exportCsvButton) {
            exportCsvButton.addEventListener('click', function() {
                window.LogicAppStorage.instance.list('attempts').then(function(attempts) {
                    window.LogicResultsExport.downloadCsv(attemptsForExport(attempts));
                });
            });
        }
        if (printResultsButton) printResultsButton.addEventListener('click', function() { window.print(); });
        if (showFormulasInput) {
            showFormulasInput.addEventListener('change', function() {
                state.showFormulas = Boolean(showFormulasInput.checked);
                applyFormulasLayout();
            });
        }
        if (colorAtomsInput) {
            colorAtomsInput.addEventListener('change', function() {
                state.colorAtoms = Boolean(colorAtomsInput.checked);
                refreshCurrentExerciseRendering();
            });
        }
        if (spokenLanguageInput) {
            spokenLanguageInput.addEventListener('change', function() {
                if (state.spokenlanguageLocked) {
                    spokenLanguageInput.checked = state.spokenlanguage;
                    return;
                }
                state.spokenlanguage = Boolean(spokenLanguageInput.checked);
                syncWrongImagesAvailability();
                if (state.spokenlanguage && state.options && state.options.length > 0) {
                    atomSpokenMap = buildAtomSpokenMap({
                        kind: state.exerciseKind,
                        info: currentQuestionInfo,
                        options: state.options
                    });
                    buildSpokenNameColorMap();
                } else {
                    atomSpokenMap = {};
                    resetSpokenNameColors();
                }
                refreshCurrentExerciseRendering();
            });
        }
        if (showWrongActionImagesInput) {
            showWrongActionImagesInput.addEventListener('change', function() {
                state.showWrongActionImages = Boolean(showWrongActionImagesInput.checked);
                if (!state.showWrongActionImages) {
                    clearWrongActionImages();
                }
            });
        }
        function handleLogDataChange() {
            reviewSubmissionState.invalidate();
            syncLogDataSettings();
        }
        if (logDataAgeInput) logDataAgeInput.addEventListener('change', handleLogDataChange);
        if (logDataInstitutionSelect) logDataInstitutionSelect.addEventListener('change', handleLogDataChange);
        if (logDataStemSelect) logDataStemSelect.addEventListener('change', handleLogDataChange);
        syncLogDataStemVisibility();
        syncPrivacyVisibility();
        window.LogicAppEvents.on('privacy:changed', syncPrivacyVisibility);
        window.LogicAppEvents.on('privacy:sessions-clearing', clearActiveSessionState);
        window.LogicAppEvents.on('privacy:sessions-cleared', clearActiveSessionState);
        window.LogicAppEvents.on('privacy:data-clearing', clearActiveSessionState);
        window.LogicAppEvents.on('privacy:data-cleared', clearActiveSessionState);
        document.addEventListener('visibilitychange', function() {
            if (document.visibilityState === 'hidden' && state.mode !== 'completed') persistSession();
        });
        window.addEventListener('beforeunload', function() {
            if (activeSession) persistSession();
        });
        window.addEventListener('logicExerciseSettingsChanged', function(evt) {
            if (!isExercisesPage) return;
            const detail = evt && evt.detail ? evt.detail : {};
            state.highlightAtoms = Boolean(detail.highlightAtoms);
            state.differentiateParens = Boolean(detail.differentiateParens);
            refreshCurrentExerciseRendering();
        });

        if (isExercisesPage) {
            state.highlightAtoms = readExerciseSetting(EX_HIGHLIGHT_KEY);
            state.differentiateParens = readExerciseSetting(EX_PARENS_KEY);
        }
        syncWrongImagesAvailability();
        showIntro();
        applyUrlConfiguration();
        syncTypeCountTotal();
        loadQuizCapabilities();
        offerSavedSession();
        return;
    }

    currentExercise = 1;
    updateTestTitle();
    if (introTitleEl) introTitleEl.hidden = true;
    if (reviewTitleEl) reviewTitleEl.hidden = true;
    if (reviewNavEl) reviewNavEl.hidden = true;
    loadExercise();
}
