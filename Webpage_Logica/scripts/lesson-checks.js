/*
 * Validatori per quiz delle lezioni (vero/falso + risposte in sequenza token).
 */

/**
 * Valida la risposta selezionata in un quiz radio e blocca il form dopo la verifica.
 * @pre Il bottone di verifica e all'interno del blocco domanda con radio T/F.
 * @post Lo stato visivo viene aggiornato, il feedback testuale e mostrato e il form viene bloccato.
 */
function check(callerElement) {
    function lockCheckButton(button) {
        if (!button) return;
        button.disabled = true;
        button.setAttribute('aria-disabled', 'true');
    }

    function setStatus(targetButton, message, kind) {
        if (!targetButton) return;
        const box = targetButton.closest('.rounded-box') || targetButton.parentElement;
        if (!box) return;

        let status = box.querySelector('.quiz-status.lesson-quiz-status');
        if (!status) {
            status = document.createElement('p');
            status.className = 'quiz-status lesson-quiz-status';
            status.setAttribute('aria-live', 'polite');
            targetButton.insertAdjacentElement('afterend', status);
        }
        status.classList.remove('is-correct');
        status.classList.remove('is-wrong');
        if (kind === 'correct') status.classList.add('is-correct');
        if (kind === 'wrong') status.classList.add('is-wrong');
        status.textContent = message || '';
    }

    function clearVisualFeedback(scope) {
        const options = scope.querySelectorAll('.lesson-radio-option');
        options.forEach(function(option) {
            option.classList.remove('is-correct');
            option.classList.remove('is-correct-answer');
            option.classList.remove('is-wrong');
            option.classList.remove('is-final');
        });
    }

    function markRadioOption(input, className) {
        if (!input) return;
        const option = input.closest('.lesson-radio-option');
        if (!option) return;
        option.classList.add('is-final');
        option.classList.add(className);
    }

    function lockRadioScope(scope) {
        if (!scope) return;
        const radios = scope.querySelectorAll('input[type="radio"]');
        radios.forEach(function(radio) {
            radio.disabled = true;
        });

        if (scope.tagName === 'FORM') {
            scope.dataset.quizLocked = 'true';
            return;
        }

        const forms = scope.querySelectorAll('form');
        forms.forEach(function(form) {
            form.dataset.quizLocked = 'true';
        });
    }

    const caller = callerElement || document.activeElement;

    let scope = document;
    if (caller) {
        let prev = caller.previousElementSibling;
        while (prev && prev.tagName !== 'FORM') {
            prev = prev.previousElementSibling;
        }
        if (prev && prev.tagName === 'FORM') {
            scope = prev;
        } else {
            const container = caller.closest && (caller.closest('.rounded-box') || caller.closest('form') || caller.closest('label'));
            if (container) scope = container;
        }
    }

    const selected = scope.querySelector('input[type="radio"]:checked');
    if (!selected) {
        setStatus(caller, 'Seleziona una risposta.', '');
        return;
    }

    clearVisualFeedback(scope);

    const val = selected.value;
    if (val === 'T') {
        markRadioOption(selected, 'is-correct');
        lockRadioScope(scope);
        lockCheckButton(caller);
        if (window.LogicAppEvents) window.LogicAppEvents.emit('lesson:answered', {
            exerciseId: scope.id || caller?.dataset.checkIndex || caller?.dataset.checkAction || 'radio',
            correct: true
        });
        //setStatus(caller, '✓ Corretto.', 'correct');
        return;
    }
    if (val === 'F') {
        markRadioOption(selected, 'is-wrong');
        const correct = scope.querySelector('input[type="radio"][value="T"]');
        if (correct) {
            markRadioOption(correct, 'is-correct-answer');
        }
        lockRadioScope(scope);
        lockCheckButton(caller);
        if (window.LogicAppEvents) window.LogicAppEvents.emit('lesson:answered', {
            exerciseId: scope.id || caller?.dataset.checkIndex || caller?.dataset.checkAction || 'radio',
            correct: false
        });
        //setStatus(caller, '✕ Errato.', 'wrong');
        return;
    }

    setStatus(caller, 'Risposta non valida.', '');
}

/**
 * Confronta la risposta tokenizzata dell'esercizio n con i pattern ammessi.
 * @pre n identifica una domanda presente e relativo input .expressionInput.
 * @post Mostra alert di esito e restituisce true/false in base alla correttezza.
 */
function checkArray(n, callerElement) {
    function lockCheckButton(button) {
        if (!button) return;
        button.disabled = true;
        button.setAttribute('aria-disabled', 'true');
    }

    function getExpressionScope(input) {
        if (!input) return null;
        const label = input.closest('label');
        if (label) return label;
        return input.parentElement;
    }

    function getInputWrap(input) {
        if (!input) return null;
        let wrap = input.closest('.lesson-expression-input-wrap');
        if (wrap) return wrap;

        wrap = document.createElement('div');
        wrap.className = 'lesson-expression-input-wrap';
        input.insertAdjacentElement('beforebegin', wrap);
        wrap.appendChild(input);
        return wrap;
    }

    function lockExpressionBuilder(input) {
        const scope = getExpressionScope(input);
        if (!scope) return;
        scope.dataset.expressionLocked = 'true';

        const buttons = scope.querySelectorAll('.btn-wide');
        buttons.forEach(function(button) {
            button.disabled = true;
            button.setAttribute('aria-disabled', 'true');
        });
    }

    function unlockExpressionBuilder(input) {
        const scope = getExpressionScope(input);
        if (!scope) return;
        delete scope.dataset.expressionLocked;

        const buttons = scope.querySelectorAll('.btn-wide');
        buttons.forEach(function(button) {
            button.disabled = false;
            button.removeAttribute('aria-disabled');
        });
    }

    function clearExpressionFeedback(input) {
        if (!input) return;
        const inputWrap = getInputWrap(input);
        input.classList.remove('is-correct');
        input.classList.remove('is-wrong');

        if (inputWrap) {
            inputWrap.classList.remove('has-feedback');
        }

        const status = inputWrap && inputWrap.querySelector('.quiz-status.lesson-expression-status');
        if (status) {
            status.classList.remove('is-correct');
            status.classList.remove('is-wrong');
            status.textContent = '';
        }
    }

    function setExpressionFeedback(input, message, kind) {
        if (!input) return;
        clearExpressionFeedback(input);

        const inputWrap = getInputWrap(input);
        if (!inputWrap) return;

        if (kind === 'correct') {
            input.classList.add('is-correct');
        }
        if (kind === 'wrong') {
            input.classList.add('is-wrong');
        }
        inputWrap.classList.add('has-feedback');

        let status = inputWrap.querySelector('.quiz-status.lesson-expression-status');
        if (!status) {
            status = document.createElement('p');
            status.className = 'quiz-status lesson-expression-status';
            status.setAttribute('aria-live', 'polite');
            inputWrap.insertAdjacentElement('beforeend', status);
        }

        status.classList.remove('is-correct');
        status.classList.remove('is-wrong');
        if (kind === 'correct') status.classList.add('is-correct');
        if (kind === 'wrong') status.classList.add('is-wrong');
        status.textContent = message || '';
    }

    // Espone il reset globale per pulire lo stato mentre si compone la formula.
    window.clearExpressionFeedback = clearExpressionFeedback;
    window.unlockExpressionBuilder = unlockExpressionBuilder;

    const caller = callerElement || document.activeElement;

    const answers = {
        1: [['P', 'allora', 'non', 'Q']],
        2: [['non', 'N', 'allora', 'P']],
        3: [['M', '∧', '¬', 'B', '∧', 'S', '∧', 'R']],
        4: [['D', '∨', 'S', '∧', 'C', '→', 'R']],
        5: [['D', '→', '¬', 'B', '∨', '¬', 'C', '∧', 'R', '∧', 'S']],
        6: [
            ['∃x', '¬', '(', 'f(x)', '→', 'r(x)', ')'],
            ['∃x', '(', 'f(x)', '∧', '¬', 'r(x)', ')']
        ]
    };

    const possibles = answers[n];
    if (!possibles) {
        console.warn('Numero domanda non valido:', n);
        return false;
    }

    const inputs = document.querySelectorAll('.expressionInput');
    const input = inputs[n - 1];
    if (!input) {
        console.warn('Input esercizio non trovato per indice:', n);
        return false;
    }

    const normalize = function(s) {
        return (s || '').replace(/\s+/g, ' ').trim();
    };
    const user = normalize(input.value);
    const userTokens = user === '' ? [] : user.split(' ').filter(Boolean);

    for (const ans of possibles) {
        const ansTokens = ans.map(function(token) {
            return token.toString();
        });
        if (userTokens.length !== ansTokens.length) continue;
        let ok = true;
        for (let i = 0; i < ansTokens.length; i += 1) {
            if (userTokens[i] !== ansTokens[i]) {
                ok = false;
                break;
            }
        }
        if (ok) {
            setExpressionFeedback(input, '✓ Corretto', 'correct');
            lockExpressionBuilder(input);
            lockCheckButton(caller);
            if (window.LogicAppEvents) window.LogicAppEvents.emit('lesson:answered', {
                exerciseId: 'expression-' + String(n),
                correct: true
            });
            return true;
        }
    }

    setExpressionFeedback(input, '✕ Errato', 'wrong');
    lockExpressionBuilder(input);
    lockCheckButton(caller);
    if (window.LogicAppEvents) window.LogicAppEvents.emit('lesson:answered', {
        exerciseId: 'expression-' + String(n),
        correct: false
    });
    return false;
}

document.addEventListener('click', function handleLessonCheck(event) {
    const button = event.target.closest('[data-check-action], [data-check-index]');
    if (!button) return;
    if (button.dataset.checkIndex) {
        checkArray(Number(button.dataset.checkIndex), button);
        return;
    }
    check(button);
});
