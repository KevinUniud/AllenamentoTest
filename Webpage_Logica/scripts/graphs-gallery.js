(function initializeGraphsGallery() {
    'use strict';

    const images = Array.from(document.querySelectorAll('.graph-card img'));
    const lightbox = document.getElementById('graphsLightbox');
    const lightboxImage = document.getElementById('graphsLightboxImage');
    const lightboxCaption = document.getElementById('graphsLightboxCaption');
    const lightboxClose = document.getElementById('graphsLightboxClose');
    const lightboxTitle = document.getElementById('graphsLightboxTitle');
    const activeImageClass = 'is-lightbox-active';
    let lastFocusedElement = null;
    let backgroundState = [];

    function focusableElements() {
        if (!lightbox) return [];
        return Array.from(lightbox.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
            + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(function(element) {
            return !element.hasAttribute('hidden');
        });
    }

    function makeBackgroundInert() {
        if (!lightbox || backgroundState.length > 0) return;
        // The Next island may nest the lightbox below main and its wrapper.
        // Hide siblings along that path; hiding an ancestor would hide the dialog.
        let branch = lightbox;
        while (branch && branch !== document.body) {
            const parent = branch.parentElement;
            if (!parent) break;
            Array.from(parent.children).forEach(function(element) {
                if (element === branch) return;
                backgroundState.push({
                    element: element,
                    inert: Boolean(element.inert),
                    ariaHidden: element.getAttribute('aria-hidden')
                });
                element.inert = true;
                element.setAttribute('aria-hidden', 'true');
            });
            branch = parent;
        }
    }

    function restoreBackground() {
        backgroundState.forEach(function(state) {
            state.element.inert = state.inert;
            if (state.ariaHidden === null) state.element.removeAttribute('aria-hidden');
            else state.element.setAttribute('aria-hidden', state.ariaHidden);
        });
        backgroundState = [];
    }

    function openLightbox(image) {
        if (!lightbox || !lightboxImage || !lightboxCaption || !lightboxClose || !lightboxTitle) return;
        if (!lightbox.hidden) return;
        lastFocusedElement = document.activeElement;
        lightboxImage.src = image.currentSrc || image.src;
        lightboxImage.alt = image.alt || '';
        lightboxCaption.textContent = image.alt || 'Grafico ingrandito';
        lightboxTitle.textContent = image.alt || 'Grafico ingrandito';
        lightbox.hidden = false;
        document.body.classList.add('graphs-modal-open');
        lightboxClose.focus();
        makeBackgroundInert();
        image.classList.add(activeImageClass);
        const card = image.closest('.graph-card');
        if (card) card.classList.add(activeImageClass);
    }

    function closeLightbox() {
        if (!lightbox || lightbox.hidden) return;
        lightbox.hidden = true;
        document.body.classList.remove('graphs-modal-open');
        restoreBackground();
        if (lightboxImage) {
            lightboxImage.src = '';
            lightboxImage.alt = '';
        }
        if (lastFocusedElement && lastFocusedElement.isConnected !== false
            && typeof lastFocusedElement.focus === 'function') lastFocusedElement.focus();
        images.forEach(function(image) { image.classList.remove(activeImageClass); });
        document.querySelectorAll('.graph-card.' + activeImageClass).forEach(function(card) {
            card.classList.remove(activeImageClass);
        });
        lastFocusedElement = null;
    }

    images.forEach(function(image) {
        const card = image.closest('.graph-card');
        if (!card) return;
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');
        card.setAttribute('aria-label', 'Ingrandisci grafico: ' + (image.alt || 'grafico'));
        card.addEventListener('click', function() { openLightbox(image); });
        card.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openLightbox(image);
            }
        });
    });

    if (lightbox) {
        lightbox.addEventListener('click', function(event) {
            if (event.target === lightbox) closeLightbox();
        });
    }
    if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
    document.addEventListener('keydown', function(event) {
        if (!lightbox || lightbox.hidden) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closeLightbox();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusables = focusableElements();
        if (focusables.length === 0) {
            event.preventDefault();
            const panel = lightbox.querySelector('[role="dialog"]');
            if (panel) panel.focus();
            return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (focusables.length === 1) {
            event.preventDefault();
            first.focus();
            return;
        }
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
})();
