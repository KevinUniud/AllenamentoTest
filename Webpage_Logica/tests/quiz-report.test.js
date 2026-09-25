const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const context = {};
context.window = context;
vm.runInNewContext(fs.readFileSync('scripts/quiz-report.js', 'utf8'), context);
const report = context.LogicQuizReport;

test('STEM is required only for university choices', () => {
    assert.equal(report.isStemRequired('triennale'), true);
    assert.equal(report.isStemRequired('liceo-scientifico'), false);
});

test('demographics are read from current form controls only', () => {
    const demographics = report.readDemographics({
        age: { value: ' 22 ' },
        institution: { value: 'triennale' },
        stem: { value: 'STEM' }
    });

    assert.deepEqual({ ...demographics }, {
        age: '22',
        institution: 'triennale',
        stem: 'STEM'
    });
});

test('buildReport computes totals without DOM dependencies', () => {
    const output = report.buildReport({
        startedAt: 1000,
        now: 6000,
        results: [
            { isCorrect: true, question: 'Q1', selectedAnswer: 'A', correctAnswer: 'A' },
            { isCorrect: false, question: 'Q2', selectedAnswer: 'B', correctAnswer: 'C' }
        ],
        demographics: { age: '20', institution: 'triennale', stem: 'STEM' },
        feedback: { expectation: '5' },
        feedbackFields: [{ id: 'expectation', payloadKey: 'Aspettative test' }]
    });

    assert.equal(output['Initial Data']['Tempo totale'], '5.00s');
    assert.equal(output['Initial Data']['Totale domande corrette'], 1);
    assert.equal(output.Feedback['Aspettative test'], '5');
});

test('legacy report payload remains byte-for-byte guarded and structurally unchanged', () => {
    const source = fs.readFileSync('scripts/quiz-report.js');
    assert.equal(
        crypto.createHash('sha256').update(source).digest('hex'),
        'c86d59dcfb77eea9ec8a1dd739360a3a85475412abe40bb6e653ea9b7eb99003'
    );

    const startedAt = 1000;
    const options = {
        showFormulas: true,
        colorAtoms: false,
        spokenLanguage: false,
        showWrongActionImages: true
    };
    const output = report.buildReport({
        startedAt,
        now: 7250,
        demographics: { age: '22', institution: 'triennale', stem: 'STEM' },
        feedback: {
            expectation: '5',
            aidsUtility: '4',
            lessonsUtility: '3',
            testDifficulty: '2',
            control: '1'
        },
        feedbackFields: [
            { id: 'expectation', payloadKey: 'Aspettative test' },
            { id: 'aidsUtility', payloadKey: 'Utilità ausili' },
            { id: 'lessonsUtility', payloadKey: 'Utilità lezioni' },
            { id: 'testDifficulty', payloadKey: 'Difficoltà test' },
            { id: 'control', payloadKey: 'Controllo' }
        ],
        results: [
            {
                tipoDomanda: 'equivalence',
                tempoRisposta: '1.25s',
                isCorrect: true,
                question: 'p -> q',
                risposteMostrate: '¬p ∨ q; p ∧ q',
                selectedAnswer: '¬p ∨ q',
                correctAnswer: '¬p ∨ q',
                opzioniAttive: options
            },
            {
                tipoDomanda: 'truth-value',
                tempoRisposta: '5.00s',
                isCorrect: false,
                question: 'p è vero?',
                risposteMostrate: 'Vero; Falso',
                selectedAnswer: 'Falso',
                correctAnswer: 'Vero',
                opzioniAttive: options
            }
        ]
    });

    assert.deepEqual(JSON.parse(JSON.stringify(output)), {
        'Initial Data': {
            'Tempo inizio esercitazione': report.formatDateTime(startedAt),
            'Tempo totale': '6.25s',
            'Totale domande': 2,
            'Totale domande corrette': 1,
            'Totale domande errate': 1,
            'Opzioni attive': options,
            'Età': '22',
            'Istituto di appartenenza': 'Corso di laurea Triennale',
            'Indirizzo': 'STEM'
        },
        Domande: [
            {
                'Domanda nº 1': {
                    Tipologia: 'equivalence',
                    'Tempo impiegato per rispondere': '1.25s',
                    'Risposta è corretta': 'Sì',
                    Domanda: 'p -> q',
                    Risposte: '¬p ∨ q; p ∧ q',
                    'Risposta utente': '¬p ∨ q',
                    'Risposta corretta': '¬p ∨ q'
                }
            },
            {
                'Domanda nº 2': {
                    Tipologia: 'truth-value',
                    'Tempo impiegato per rispondere': '5.00s',
                    'Risposta è corretta': 'No',
                    Domanda: 'p è vero?',
                    Risposte: 'Vero; Falso',
                    'Risposta utente': 'Falso',
                    'Risposta corretta': 'Vero'
                }
            }
        ],
        Feedback: {
            'Aspettative test': '5',
            'Utilità ausili': '4',
            'Utilità lezioni': '3',
            'Difficoltà test': '2',
            Controllo: '1'
        }
    });
});
