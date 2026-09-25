/*
 * Navigazione e resa grafica delle risposte radio nelle lezioni.
 */

/**
 * Trasforma i radio button in opzioni stilizzate e abilita navigazione da tastiera.
 * @pre Le sezioni lezione-3..lezione-6 esistono nel DOM con form radio compatibili.
 * @post Ogni form idoneo ha opzioni custom, stato selezione sincronizzato e scorciatoie tastiera attive.
 */
function initLessonRadioNavigation() {
    const lessonIds = ['lezione-3', 'lezione-4', 'lezione-5', 'lezione-6'];

    function isFormLocked(form) {
        return Boolean(form && form.dataset && form.dataset.quizLocked === 'true');
    }

    function getRadiosInForm(form) {
        const radios = Array.from(form.querySelectorAll('input[type="radio"]'));
        if (radios.length < 2) return [];

        const name = radios[0].name;
        if (!name) return radios;
        return radios.filter(function(radio) {
            return radio.name === name;
        });
    }

    function moveSelection(radios, delta) {
        if (!Array.isArray(radios) || radios.length === 0) return;

        const availableRadios = radios.filter(function(radio) {
            return !radio.disabled;
        });
        if (availableRadios.length === 0) return;

        let current = availableRadios.findIndex(function(radio) {
            return radio.checked;
        });
        if (current < 0) current = 0;
        const next = (current + delta + availableRadios.length) % availableRadios.length;
        availableRadios[next].checked = true;
        availableRadios[next].focus();
    }

    function selectAbsolute(radios, idx) {
        if (!Array.isArray(radios) || radios.length === 0) return;
        const availableRadios = radios.filter(function(radio) {
            return !radio.disabled;
        });
        if (availableRadios.length === 0) return;
        if (idx < 0 || idx >= availableRadios.length) return;
        availableRadios[idx].checked = true;
        availableRadios[idx].focus();
    }

    function updateVisualSelection(form) {
        const options = form.querySelectorAll('.lesson-radio-option');
        options.forEach(function(option) {
            const radio = option.querySelector('input[type="radio"]');
            option.classList.toggle('is-selected', Boolean(radio && radio.checked));
        });
    }

    function buildStyledOptions(form) {
        const label = form.querySelector('label');
        if (!label) return;
        if (label.dataset.radioStyled === 'true') return;

        const radios = getRadiosInForm(form);
        if (radios.length < 2) return;

        const built = [];
        radios.forEach(function(radio) {
            const option = document.createElement('div');
            option.className = 'quiz-option lesson-radio-option';

            const textParts = [];
            let cursor = radio.nextSibling;
            while (cursor && !(cursor.nodeType === 1 && cursor.tagName === 'BR') && !(cursor.nodeType === 1 && cursor.tagName === 'INPUT')) {
                textParts.push(cursor.textContent || '');
                const next = cursor.nextSibling;
                cursor.remove();
                cursor = next;
            }

            if (cursor && cursor.nodeType === 1 && cursor.tagName === 'BR') {
                const next = cursor.nextSibling;
                cursor.remove();
                cursor = next;
            }

            const textSpan = document.createElement('span');
            textSpan.className = 'lesson-radio-text';
            textSpan.textContent = textParts.join('').replace(/\s+/g, ' ').trim();

            radio.classList.add('lesson-radio-input');
            option.appendChild(radio);
            option.appendChild(textSpan);
            built.push(option);
        });

        label.innerHTML = '';
        built.forEach(function(node) {
            label.appendChild(node);
        });
        label.dataset.radioStyled = 'true';

        built.forEach(function(option) {
            option.addEventListener('click', function(evt) {
                // Prevent the parent <label> default behavior from re-selecting the first radio.
                evt.preventDefault();
                if (isFormLocked(form)) return;
                const radio = option.querySelector('input[type="radio"]');
                if (!radio) return;
                if (radio.disabled) return;
                radio.checked = true;
                radio.focus();
                updateVisualSelection(form);
            });
        });

        form.addEventListener('change', function(evt) {
            const target = evt.target;
            if (!(target instanceof HTMLInputElement)) return;
            if (target.type !== 'radio') return;
            updateVisualSelection(form);
        });

        updateVisualSelection(form);
    }

    lessonIds.forEach(function(lessonId) {
        const root = document.getElementById(lessonId);
        if (!root) return;

        const forms = root.querySelectorAll('form');
        forms.forEach(function(form) {
            buildStyledOptions(form);

            if (form.dataset.radioNavReady === 'true') return;

            const radios = getRadiosInForm(form);
            if (radios.length < 2) return;

            form.dataset.radioNavReady = 'true';

            form.addEventListener('keydown', function(evt) {
                if (isFormLocked(form)) return;

                if (evt.key === 'ArrowDown' || evt.key === 'ArrowRight') {
                    evt.preventDefault();
                    moveSelection(radios, 1);
                    updateVisualSelection(form);
                    return;
                }

                if (evt.key === 'ArrowUp' || evt.key === 'ArrowLeft') {
                    evt.preventDefault();
                    moveSelection(radios, -1);
                    updateVisualSelection(form);
                    return;
                }

                if (evt.key === 'Home') {
                    evt.preventDefault();
                    selectAbsolute(radios, 0);
                    updateVisualSelection(form);
                    return;
                }

                if (evt.key === 'End') {
                    evt.preventDefault();
                    selectAbsolute(radios, radios.length - 1);
                    updateVisualSelection(form);
                }
            });

            updateVisualSelection(form);
        });
    });
}
