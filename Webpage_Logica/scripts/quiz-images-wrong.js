(function() {
    /**
     * Costruisce il descrittore immagini per il file "Risposta sbagliata".
     * @pre context contiene opzionalmente wrongFormulaText e wrongFormulaSteps.
     * @post Restituisce un descriptor con key, titolo, formula e passi normalizzati.
     */
    window.quizWrongImageFileBuilder = function(context) {
        return {
            key: 'wrong',
            title: 'Risposta sbagliata',
            formulaText: context && context.wrongFormulaText ? String(context.wrongFormulaText) : '',
            formulaSteps: context && Array.isArray(context.wrongFormulaSteps)
                ? context.wrongFormulaSteps.slice()
                : []
        };
    };
})();
