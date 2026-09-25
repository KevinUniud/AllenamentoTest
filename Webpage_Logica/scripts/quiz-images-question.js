(function() {
    // Estrae la formula principale dalla traccia testuale della domanda.
    function extractQuotedFormula(questionText) {
        const text = String(questionText || '');
        const match = text.match(/"([^"]+)"/);
        if (!match) return '';
        return String(match[1] || '').trim();
    }

    /**
     * Costruisce il descrittore immagini per il file "Domanda".
     * @pre context contiene opzionalmente questionText e questionFormulaSteps.
     * @post Restituisce un oggetto descriptor coerente usato dal renderer immagini quiz.
     */
    window.quizQuestionImageFileBuilder = function(context) {
        const formulaFromQuestion = extractQuotedFormula(context && context.questionText);
        return {
            key: 'question',
            title: 'Domanda',
            formulaText: formulaFromQuestion,
            formulaSteps: context && Array.isArray(context.questionFormulaSteps)
                ? context.questionFormulaSteps.slice()
                : []
        };
    };
})();
