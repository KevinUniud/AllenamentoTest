/*
 * Bootstrap globale della pagina.
 * - Inizializza impostazioni globali
 * - Garantisce un contenitore main accessibile
 * - Rimuove registrazioni e cache appartenenti alla precedente versione PWA
 * - Collega i controlli veloci delle espressioni logiche
 */
(function retireLegacyPwa() {
    const source = document.currentScript && document.currentScript.src;
    if (!source) return;
    const legacyScope = new URL('../', source).href;

    if ('serviceWorker' in navigator && typeof navigator.serviceWorker.getRegistrations === 'function') {
        navigator.serviceWorker.getRegistrations().then(function(registrations) {
            return Promise.all(registrations
                .filter(function(registration) { return registration.scope === legacyScope; })
                .map(function(registration) { return registration.unregister(); }));
        }).catch(function() {});
    }

    if ('caches' in globalThis && typeof globalThis.caches.keys === 'function') {
        globalThis.caches.keys().then(function(names) {
            return Promise.all(names
                .filter(function(name) { return name.startsWith('testlogica-'); })
                .map(function(name) { return globalThis.caches.delete(name); }));
        }).catch(function() {});
    }
})();

(function bootstrapAppPage() {
function initializeAppPage() {
    if (document.__logicAppInitialized || !document.body) return;
    // Controllers live for this document; Next pages navigate with normal links.
    document.__logicAppInitialized = true;
    /**
     * Assicura una struttura base accessibile della pagina.
     * @pre Il DOM principale della pagina e document.body sono disponibili.
     * @post Esiste sempre un elemento <main id="main-content" tabindex="-1">.
     */
    function ensureAccessibilityScaffold() {
        let main = document.querySelector('main');

        if (!main) {
            main = document.createElement('main');
            const children = Array.from(document.body.children);
            children.forEach(function(node) {
                if (node.tagName === 'SCRIPT') return;
                if (node.classList.contains('settings-trigger')) return;
                if (node.classList.contains('settings-overlay')) return;
                main.appendChild(node);
            });
            document.body.appendChild(main);
        }

        if (!main.id) {
            main.id = 'main-content';
        }
        if (!main.hasAttribute('tabindex')) {
            main.setAttribute('tabindex', '-1');
        }

    }

    if (typeof initGlobalSettings === 'function') {
        initGlobalSettings();
    }

    if (window.LogicAppStorage && typeof window.LogicAppStorage.instance.purgeExpired === 'function') {
        window.LogicAppStorage.instance.purgeExpired().catch(function() {});
    }

    ensureAccessibilityScaffold();

    // I pulsanti del tastierino sono azioni locali: il tipo esplicito evita
    // submit accidentali anche nelle pagine HTML meno recenti.
    document.querySelectorAll('.controls button').forEach(function(button) {
        button.type = 'button';
        if (button.classList.contains('deleteBtn')) {
            button.textContent = 'Cancella';
            button.title = 'Cancella l\'espressione';
            button.setAttribute('aria-label', 'Cancella l\'espressione');
        }
    });

    if (typeof initLessonRadioNavigation === 'function') {
        initLessonRadioNavigation();
    }

    // Gestione delegata dei pulsanti tastierino formula e reset riga.
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.btn-wide');
        if (btn) {
            const controls = btn.closest('.controls');
            if (!controls) return;
            e.preventDefault();
            const label = controls.closest('label');
            if (!label) return;
            if (label.dataset.expressionLocked === 'true') return;
            const input = label.querySelector('.expressionInput');
            if (!input) return;
            input.value = (input.value || '') + (btn.dataset.val || '');
            if (typeof window.clearExpressionFeedback === 'function') {
                window.clearExpressionFeedback(input);
            }
            return;
        }

        const del = e.target.closest('.deleteBtn');
        if (del) {
            e.preventDefault();
            const controls = del.closest('.controls');
            if (!controls) return;
            const label = controls.closest('label');
            if (!label) return;
            const input = label.querySelector('.expressionInput');
            if (input) {
                input.value = '';
                if (typeof window.clearExpressionFeedback === 'function') {
                    window.clearExpressionFeedback(input);
                }
                if (typeof window.unlockExpressionBuilder === 'function') {
                    window.unlockExpressionBuilder(input);
                }
            }

            const box = del.closest('.rounded-box');
            const checkBtn = box && box.querySelector('button[data-check-index], button[data-check-action]');
            if (checkBtn) {
                checkBtn.disabled = false;
                checkBtn.removeAttribute('aria-disabled');
            }
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAppPage, { once: true });
} else {
    initializeAppPage();
}
})();
