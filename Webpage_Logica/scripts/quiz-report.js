(function exposeQuizReport(global) {
    'use strict';

    const INSTITUTIONS = Object.freeze({
        triennale: 'Corso di laurea Triennale',
        magistrale: 'Corso di laurea Magistrale',
        'ciclo-unico': 'Ciclo unico',
        'liceo-scientifico': 'Liceo scientifico',
        'altro-liceo': 'Altro liceo',
        iti: 'Istituto tecnico industriale',
        'altri-tecnici': 'Altri istituti tecnici',
        professionale: 'Istituto professionale',
        altro: 'Altro'
    });

    function formatDateTime(timestamp) {
        if (!timestamp || typeof timestamp !== 'number') return '';
        const date = new Date(timestamp);
        const values = [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, '0'),
            String(date.getDate()).padStart(2, '0'),
            String(date.getHours()).padStart(2, '0'),
            String(date.getMinutes()).padStart(2, '0'),
            String(date.getSeconds()).padStart(2, '0')
        ];
        return values[0] + '/' + values[1] + '/' + values[2] + ' ' + values[3] + ':' + values[4] + ':' + values[5];
    }

    function readDemographics(fields) {
        const source = fields || {};
        function controlValue(control) {
            if (!control || typeof control !== 'object') return '';
            return String(control.value || '').trim();
        }
        return {
            age: controlValue(source.age),
            institution: controlValue(source.institution),
            stem: controlValue(source.stem)
        };
    }

    function institutionLabel(value) {
        return INSTITUTIONS[String(value || '')] || '';
    }

    function isStemRequired(value) {
        return ['triennale', 'magistrale', 'ciclo-unico'].includes(String(value || ''));
    }

    function emptyFeedback() {
        return { expectation: '', aidsUtility: '', lessonsUtility: '', testDifficulty: '', control: '' };
    }

    function buildReport(input) {
        const results = Array.isArray(input.results) ? input.results : [];
        const now = Number(input.now) || Date.now();
        const startedAt = Number(input.startedAt) || 0;
        const demographics = input.demographics || {};
        const feedback = input.feedback || {};
        const fields = Array.isArray(input.feedbackFields) ? input.feedbackFields : [];
        const feedbackPayload = {};
        fields.forEach(function(field) {
            feedbackPayload[field.payloadKey] = String(feedback[field.id] || '');
        });

        const initialData = {
            'Tempo inizio esercitazione': formatDateTime(startedAt),
            'Tempo totale': startedAt ? ((now - startedAt) / 1000).toFixed(2) + 's' : '',
            'Totale domande': results.length,
            'Totale domande corrette': results.filter(function(entry) { return entry.isCorrect; }).length,
            'Totale domande errate': results.filter(function(entry) { return !entry.isCorrect; }).length,
            'Opzioni attive': results.length ? results[0].opzioniAttive : {}
        };

        if (demographics.age) initialData.Età = demographics.age;
        if (demographics.institution) initialData['Istituto di appartenenza'] = institutionLabel(demographics.institution);
        if (demographics.stem) initialData.Indirizzo = demographics.stem;

        return {
            'Initial Data': initialData,
            Domande: results.map(function(entry, index) {
                const answer = {
                    Tipologia: entry.tipoDomanda || '',
                    'Tempo impiegato per rispondere': typeof entry.tempoRisposta === 'string' ? entry.tempoRisposta : '',
                    'Risposta è corretta': entry.isCorrect ? 'Sì' : 'No',
                    Domanda: entry.question,
                    Risposte: entry.risposteMostrate || '',
                    'Risposta utente': entry.selectedAnswer,
                    'Risposta corretta': entry.correctAnswer
                };
                return { ['Domanda nº ' + (index + 1)]: answer };
            }),
            Feedback: feedbackPayload
        };
    }

    global.LogicQuizReport = Object.freeze({
        buildReport,
        emptyFeedback,
        formatDateTime,
        institutionLabel,
        isStemRequired,
        readDemographics
    });
})(window);
