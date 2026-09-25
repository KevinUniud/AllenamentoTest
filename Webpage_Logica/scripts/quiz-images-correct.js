(function() {
    /**
     * Costruisce il descrittore immagini per il file "Risposta corretta".
     * @pre context contiene opzionalmente correctFormulaText e correctFormulaSteps.
     * @post Restituisce un descriptor con key, titolo, formula e passi normalizzati.
     */
    window.quizCorrectImageFileBuilder = function(context) {
        return {
            key: 'correct',
            title: 'Risposta corretta',
            formulaText: context && context.correctFormulaText ? String(context.correctFormulaText) : '',
            formulaSteps: context && Array.isArray(context.correctFormulaSteps)
                ? context.correctFormulaSteps.slice()
                : []
        };
    };
})();
