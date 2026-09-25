(function bootstrapQuizPage() {
    function initializeQuizPage() {
        if (document.__logicQuizInitialized || typeof initEquivalentQuiz !== 'function') return;
        // Loading the bootstrap twice must not create duplicate timers/listeners.
        // The document is replaced on navigation; SPA reinitialization is unsupported.
        document.__logicQuizInitialized = true;
        initEquivalentQuiz('equivalenceQuiz');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeQuizPage, { once: true });
    } else {
        initializeQuizPage();
    }
})();
