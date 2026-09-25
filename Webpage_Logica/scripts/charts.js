/* Piccoli grafici SVG accessibili, sempre affiancati da una tabella dati. */
(function exposeCharts(global) {
    'use strict';
    const NS = 'http://www.w3.org/2000/svg';

    function renderBars(container, series, options) {
        if (!container) return null;
        container.innerHTML = '';
        const values = Array.isArray(series) ? series : [];
        const width = 640;
        const rowHeight = 42;
        const height = Math.max(80, values.length * rowHeight + 30);
        const svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', (options && options.label) || 'Grafico a barre dei risultati');
        svg.classList.add('chart-svg');
        const requestedMaximum = Number(options && options.maximum);
        const maximum = Number.isFinite(requestedMaximum) && requestedMaximum > 0
            ? requestedMaximum
            : Math.max(1, ...values.map(function(item) { return Number(item.value) || 0; }));
        values.forEach(function(item, index) {
            const y = index * rowHeight + 10;
            const label = document.createElementNS(NS, 'text');
            label.setAttribute('x', '4');
            label.setAttribute('y', String(y + 20));
            label.setAttribute('class', 'chart-label');
            label.textContent = String(item.label || '');
            const bar = document.createElementNS(NS, 'rect');
            bar.setAttribute('x', '145');
            bar.setAttribute('y', String(y));
            const numericValue = Math.max(0, Number(item.value) || 0);
            const boundedValue = Math.min(numericValue, maximum);
            bar.setAttribute('width', String(Math.max(2, (boundedValue / maximum) * 430)));
            bar.setAttribute('height', '25');
            bar.setAttribute('rx', '4');
            bar.setAttribute('class', 'chart-bar');
            const title = document.createElementNS(NS, 'title');
            title.textContent = String(item.label || '') + ': ' + String(item.displayValue == null ? item.value : item.displayValue);
            bar.appendChild(title);
            const value = document.createElementNS(NS, 'text');
            value.setAttribute('x', '585');
            value.setAttribute('y', String(y + 19));
            value.setAttribute('class', 'chart-label');
            value.textContent = String(item.displayValue == null ? item.value : item.displayValue);
            svg.appendChild(label);
            svg.appendChild(bar);
            svg.appendChild(value);
        });
        container.appendChild(svg);
        return svg;
    }

    function downloadSvg(svg, filename) {
        if (!svg) return false;
        const content = new XMLSerializer().serializeToString(svg);
        const blob = new Blob([content], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename || 'testlogica-grafico.svg';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        return true;
    }

    global.LogicCharts = Object.freeze({ downloadSvg: downloadSvg, renderBars: renderBars });
})(window);
